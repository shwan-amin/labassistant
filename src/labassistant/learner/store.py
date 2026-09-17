"""SQLite persistence for mastery, its change history, and saved sessions.

Uses the standard library's sqlite3 so there is nothing extra to learn: three
small tables, plain SQL, and Pydantic models at the boundary.
"""

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from labassistant.knowledge.schema import ConceptGraph
from labassistant.learner.mastery import ConceptMastery, MasteryEvent, MasteryState, apply_event

SCHEMA = """
CREATE TABLE IF NOT EXISTS mastery (
    student_id   TEXT NOT NULL,
    concept_id   TEXT NOT NULL,
    state        TEXT NOT NULL,
    clear_streak INTEGER NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (student_id, concept_id)
);

-- Every change, so the learner model can be explained and evaluated later.
CREATE TABLE IF NOT EXISTS mastery_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT NOT NULL,
    concept_id  TEXT NOT NULL,
    session_id  TEXT,
    event       TEXT NOT NULL,
    old_state   TEXT NOT NULL,
    new_state   TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    student_id  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    data        TEXT NOT NULL
);

-- A marker's decision on one diagnosis item, kept for evaluation.
CREATE TABLE IF NOT EXISTS marker_reviews (
    session_id  TEXT NOT NULL,
    item_type   TEXT NOT NULL,     -- "gap" or "note"
    item_index  INTEGER NOT NULL,
    data        TEXT NOT NULL,     -- the review as JSON
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (session_id, item_type, item_index)
);
"""


class MasteryUpdate(BaseModel):
    student_id: str
    concept_id: str
    event: MasteryEvent
    old_state: MasteryState
    new_state: MasteryState
    session_id: str | None = None


class LearnerStore:
    def __init__(self, path: Path | str, graph: ConceptGraph) -> None:
        # ":memory:" gives a throwaway database, which the tests use.
        # The API serves requests from several threads. One shared connection guarded
        # by a lock is the simplest safe option for a single-user local prototype.
        self.connection = sqlite3.connect(str(path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.graph = graph
        self._lock = threading.RLock()

    def close(self) -> None:
        self.connection.close()

    # --- mastery ---

    def get_mastery(self, student_id: str) -> dict[str, ConceptMastery]:
        """Mastery for every concept in the graph; concepts never seen are `unknown`."""
        with self._lock:
            rows = self.connection.execute(
                "SELECT concept_id, state, clear_streak FROM mastery WHERE student_id = ?",
                (student_id,),
            ).fetchall()
        stored = {
            row["concept_id"]: ConceptMastery(
                concept_id=row["concept_id"],
                state=MasteryState(row["state"]),
                clear_streak=row["clear_streak"],
            )
            for row in rows
        }
        return {
            concept.id: stored.get(concept.id, ConceptMastery(concept_id=concept.id))
            for concept in self.graph.concepts
        }

    def record_event(
        self,
        student_id: str,
        concept_id: str,
        event: MasteryEvent,
        session_id: str | None = None,
    ) -> MasteryUpdate:
        if self.graph.get_concept(concept_id) is None:
            raise ValueError(f"unknown concept {concept_id!r}")

        now = _now()
        # Read, update and write under one lock (so two answers can't race) and in
        # one transaction (so the mastery row and its event log always agree).
        with self._lock, self.connection:
            current = self.get_mastery(student_id)[concept_id]
            updated = apply_event(current, event)
            self.connection.execute(
                """
                INSERT INTO mastery (student_id, concept_id, state, clear_streak, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (student_id, concept_id)
                DO UPDATE SET state = excluded.state,
                              clear_streak = excluded.clear_streak,
                              updated_at = excluded.updated_at
                """,
                (student_id, concept_id, updated.state.value, updated.clear_streak, now),
            )
            self.connection.execute(
                """
                INSERT INTO mastery_events
                    (student_id, concept_id, session_id, event, old_state, new_state, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    student_id,
                    concept_id,
                    session_id,
                    event.value,
                    current.state.value,
                    updated.state.value,
                    now,
                ),
            )
        return MasteryUpdate(
            student_id=student_id,
            concept_id=concept_id,
            event=event,
            old_state=current.state,
            new_state=updated.state,
            session_id=session_id,
        )

    def get_events(self, student_id: str) -> list[MasteryUpdate]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT student_id, concept_id, session_id, event, old_state, new_state
                FROM mastery_events WHERE student_id = ? ORDER BY id
                """,
                (student_id,),
            ).fetchall()
        return [MasteryUpdate(**dict(row)) for row in rows]

    # --- sessions ---

    def save_session(self, session_id: str, student_id: str, data: dict) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO sessions (id, student_id, created_at, data) VALUES (?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET data = excluded.data
                """,
                (session_id, student_id, _now(), json.dumps(data)),
            )

    def load_session(self, session_id: str) -> dict | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT data FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return json.loads(row["data"]) if row else None

    def list_sessions(self, student_id: str | None = None) -> list[dict]:
        """Session ids with their student and creation time, newest first."""
        query = "SELECT id, student_id, created_at FROM sessions"
        params: tuple = ()
        if student_id is not None:
            query += " WHERE student_id = ?"
            params = (student_id,)
        with self._lock:
            rows = self.connection.execute(
                query + " ORDER BY created_at DESC, id", params
            ).fetchall()
        return [dict(row) for row in rows]

    def list_students(self) -> list[str]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT student_id FROM mastery UNION SELECT student_id FROM sessions ORDER BY 1"
            ).fetchall()
        return [row[0] for row in rows]

    # --- marker reviews ---

    def save_review(self, session_id: str, item_type: str, item_index: int, data: dict) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO marker_reviews (session_id, item_type, item_index, data, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (session_id, item_type, item_index)
                DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
                """,
                (session_id, item_type, item_index, json.dumps(data), _now()),
            )

    def get_reviews(self, session_id: str) -> list[dict]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT data FROM marker_reviews WHERE session_id = ?
                ORDER BY item_type, item_index
                """,
                (session_id,),
            ).fetchall()
        return [json.loads(row["data"]) for row in rows]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
