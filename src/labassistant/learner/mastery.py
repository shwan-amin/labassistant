"""The learner model's update rule.

Each (student, concept) has a mastery state and a "clear streak":

    unknown   no evidence yet
    emerging  some evidence, but a gap has been confirmed or understanding
              has only been shown once
    secure    understanding shown repeatedly, with no confirmed gap since

Events and what they do:

    CONFIRMED  a suspected gap was confirmed by the student's answer
               -> state = emerging, streak = 0   (even from secure)
    CLEARED    a suspected gap was cleared: the student showed understanding
               -> streak += 1
                  unknown  -> emerging
                  emerging -> secure once streak >= SECURE_STREAK
                  secure   -> secure

Deliberately simple so a student, a marker or an interviewer can follow it. A
single confirmed gap outweighs earlier success because the goal is to catch
misconceptions, not to average them away.
"""

from enum import StrEnum

from pydantic import BaseModel

SECURE_STREAK = 2


class MasteryState(StrEnum):
    UNKNOWN = "unknown"
    EMERGING = "emerging"
    SECURE = "secure"


class MasteryEvent(StrEnum):
    CONFIRMED = "confirmed"
    CLEARED = "cleared"


class ConceptMastery(BaseModel):
    concept_id: str
    state: MasteryState = MasteryState.UNKNOWN
    clear_streak: int = 0


def apply_event(current: ConceptMastery, event: MasteryEvent) -> ConceptMastery:
    """Return the new mastery for one concept after one event. Pure function."""
    if event == MasteryEvent.CONFIRMED:
        return current.model_copy(update={"state": MasteryState.EMERGING, "clear_streak": 0})

    streak = current.clear_streak + 1
    if current.state == MasteryState.UNKNOWN:
        state = MasteryState.EMERGING
    elif current.state == MasteryState.EMERGING and streak >= SECURE_STREAK:
        state = MasteryState.SECURE
    else:
        state = current.state
    return current.model_copy(update={"state": state, "clear_streak": streak})
