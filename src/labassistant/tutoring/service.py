"""Ties diagnosis, questions, answers and the learner model into sessions.

    start()  -> diagnose -> questions for all gaps (one call) -> save
    answer() -> judge reply (one call) -> update gap + mastery -> save

With skip_questioning, feedback is shown directly: no questions are asked, and only
high-confidence gaps count as confirmed in the learner model (lower-confidence
gaps are too uncertain to count against the student without asking).
"""

from labassistant.context.filtering import filter_project
from labassistant.context.models import ContextRequest
from labassistant.diagnosis.agent import DiagnosisAgent
from labassistant.diagnosis.models import Confidence, DiagnosisOptions
from labassistant.knowledge.schema import ConceptGraph
from labassistant.learner.mastery import MasteryEvent
from labassistant.learner.store import LearnerStore
from labassistant.llm.base import LLMClient
from labassistant.tutoring.answers import MAX_ANSWER_CHARS, evaluate_answer
from labassistant.tutoring.models import GapState, GapStatus, TutoringSession, Verdict
from labassistant.tutoring.questions import evidence_excerpt, generate_questions


class TutoringError(ValueError):
    """Invalid use of a session, e.g. answering a gap that is not waiting for an answer."""


class TutoringService:
    def __init__(
        self,
        client: LLMClient,
        graph: ConceptGraph,
        agent: DiagnosisAgent,
        store: LearnerStore,
    ) -> None:
        self.client = client
        self.graph = graph
        self.agent = agent
        self.store = store

    def start(
        self,
        student_id: str,
        request: ContextRequest,
        *,
        skip_questioning: bool = False,
        options: DiagnosisOptions | None = None,
    ) -> TutoringSession:
        diagnosis = self.agent.diagnose(request, options)
        files = filter_project(request.files, request.selected_path, self.agent.filter_limits).files
        gaps = [
            GapState(index=i, gap=gap, status=GapStatus.SUSPECTED)
            for i, gap in enumerate(diagnosis.concept_gaps)
        ]
        for state in gaps:
            state.evidence_excerpt = evidence_excerpt(state, files)

        session = TutoringSession(
            student_id=student_id,
            selected_path=request.selected_path,
            selection=request.selection,
            explanation=request.explanation,
            skip_questioning=skip_questioning,
            diagnosis=diagnosis,
            gaps=gaps,
        )

        if skip_questioning:
            for state in gaps:
                state.status = GapStatus.SHOWN
                if state.gap.confidence == Confidence.HIGH:
                    state.mastery_update = self.store.record_event(
                        student_id, state.gap.concept_id, MasteryEvent.CONFIRMED, session.id
                    )
        else:
            usage, adjustments = generate_questions(
                self.client, self.graph, gaps, request.explanation
            )
            session.question_usage = usage
            session.adjustments.extend(adjustments)

        self.save(session)
        return session

    def answer(self, session: TutoringSession, gap_index: int, answer: str) -> GapState:
        state = next((g for g in session.gaps if g.index == gap_index), None)
        if state is None:
            raise TutoringError(f"session has no gap {gap_index}")
        if state.status != GapStatus.SUSPECTED:
            raise TutoringError(f"gap {gap_index} is not waiting for an answer ({state.status})")
        answer = answer.strip()
        if not answer:
            raise TutoringError("the answer is empty")
        if len(answer) > MAX_ANSWER_CHARS:
            raise TutoringError(f"the answer is longer than {MAX_ANSWER_CHARS} characters")

        evaluation, usage = evaluate_answer(self.client, self.graph, state, answer)
        session.answer_usage = session.answer_usage + usage

        confirmed = evaluation.verdict == Verdict.CONFIRMED
        state.answer = answer
        state.evaluation_rationale = evaluation.rationale
        state.status = GapStatus.CONFIRMED if confirmed else GapStatus.CLEARED
        state.mastery_update = self.store.record_event(
            session.student_id,
            state.gap.concept_id,
            MasteryEvent.CONFIRMED if confirmed else MasteryEvent.CLEARED,
            session.id,
        )
        self.save(session)
        return state

    def save(self, session: TutoringSession) -> None:
        self.store.save_session(session.id, session.student_id, session.model_dump(mode="json"))

    def load(self, session_id: str) -> TutoringSession | None:
        data = self.store.load_session(session_id)
        return TutoringSession.model_validate(data) if data else None
