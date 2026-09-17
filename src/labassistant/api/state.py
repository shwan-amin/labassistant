"""Long-lived objects shared by all requests: settings, graph, store, LLM client."""

from labassistant.config import Settings
from labassistant.diagnosis.agent import DiagnosisAgent
from labassistant.knowledge.loader import load_topic
from labassistant.learner.store import LearnerStore
from labassistant.llm.base import LLMClient
from labassistant.llm.factory import create_llm_client
from labassistant.materials.retrieval import load_all_tag_files
from labassistant.tutoring.service import TutoringService


class AppState:
    def __init__(self, settings: Settings, client: LLMClient | None = None) -> None:
        self.settings = settings
        self.graph = load_topic(settings.topic, settings.knowledge_dir)
        self.store = LearnerStore(settings.database_path, self.graph)
        self.tag_files = load_all_tag_files(settings.materials_dir)
        self._client = client

    @property
    def client(self) -> LLMClient:
        # Created on first use, so the server starts (and /health works) without a
        # key; a missing key is reported when a check actually needs the LLM.
        if self._client is None:
            self._client = create_llm_client(self.settings)
        return self._client

    def tutor(self) -> TutoringService:
        agent = DiagnosisAgent(
            self.client,
            self.graph,
            model_name=self.settings.model_name,
            context_mode=self.settings.context_mode,
            token_budget=self.settings.context_token_budget,
            runner_timeout_seconds=self.settings.runner_timeout_seconds,
        )
        return TutoringService(self.client, self.graph, agent, self.store)
