from pathlib import Path

import pytest

from labassistant.knowledge import load_topic
from labassistant.learner import (
    ConceptMastery,
    LearnerStore,
    MasteryEvent,
    MasteryState,
    apply_event,
)

GRAPH = load_topic("recursion", Path(__file__).parent.parent / "knowledge")
C, X = MasteryEvent.CONFIRMED, MasteryEvent.CLEARED
U, E, S = MasteryState.UNKNOWN, MasteryState.EMERGING, MasteryState.SECURE


@pytest.mark.parametrize(
    ("events", "expected_state", "expected_streak"),
    [
        ([], U, 0),
        ([C], E, 0),
        ([X], E, 1),
        ([X, X], S, 2),
        ([X, X, X], S, 3),
        ([X, X, C], E, 0),  # a confirmed gap knocks secure back to emerging
        ([C, X], E, 1),
        ([C, X, X], S, 2),
        ([X, C, X], E, 1),  # the streak restarts after a confirmed gap
        ([C, C], E, 0),
    ],
)
def test_update_rule(events, expected_state, expected_streak) -> None:
    mastery = ConceptMastery(concept_id="base_case")
    for event in events:
        mastery = apply_event(mastery, event)
    assert (mastery.state, mastery.clear_streak) == (expected_state, expected_streak)


@pytest.fixture
def store():
    s = LearnerStore(":memory:", GRAPH)
    yield s
    s.close()


def test_every_concept_starts_unknown(store) -> None:
    mastery = store.get_mastery("alice")
    assert set(mastery) == GRAPH.concept_ids
    assert all(m.state == U for m in mastery.values())


def test_events_update_state_and_are_logged(store) -> None:
    first = store.record_event("alice", "base_case", C, session_id="s1")
    second = store.record_event("alice", "base_case", X, session_id="s2")

    assert (first.old_state, first.new_state) == (U, E)
    assert (second.old_state, second.new_state) == (E, E)
    assert store.get_mastery("alice")["base_case"].clear_streak == 1
    assert [e.session_id for e in store.get_events("alice")] == ["s1", "s2"]
    assert store.get_mastery("bob")["base_case"].state == U  # students are separate


def test_unknown_concept_rejected(store) -> None:
    with pytest.raises(ValueError, match="unknown concept"):
        store.record_event("alice", "pointers", C)


def test_state_persists_on_disk(tmp_path) -> None:
    path = tmp_path / "learner.db"
    first = LearnerStore(path, GRAPH)
    first.record_event("alice", "call_stack", X)
    first.record_event("alice", "call_stack", X)
    first.close()

    reopened = LearnerStore(path, GRAPH)
    assert reopened.get_mastery("alice")["call_stack"].state == S
    reopened.close()


def test_sessions_round_trip(store) -> None:
    store.save_session("s1", "alice", {"value": 1})
    store.save_session("s1", "alice", {"value": 2})  # update in place
    store.save_session("s2", "bob", {"value": 3})

    assert store.load_session("s1") == {"value": 2}
    assert store.load_session("missing") is None
    assert [s["id"] for s in store.list_sessions("alice")] == ["s1"]
    assert {s["id"] for s in store.list_sessions()} == {"s1", "s2"}
