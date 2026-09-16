"""The diagnosis agent: context in, validated and integrity-checked diagnosis out.

build context -> ask model -> (run_tests as needed) -> parse JSON
    -> invalid? retry once with the error -> check ids/lines/tests
    -> leak check on student-facing text -> DiagnosisResult
"""

from labassistant.context.builder import build_context
from labassistant.context.filtering import FilterLimits, filter_project
from labassistant.context.models import ContextMode, ContextRequest
from labassistant.diagnosis import prompts
from labassistant.diagnosis.cost import ModelPrice, estimate_cost_usd
from labassistant.diagnosis.leak_check import find_leaks
from labassistant.diagnosis.models import (
    Adjustment,
    DiagnosisOptions,
    DiagnosisOutput,
    DiagnosisResult,
    ToolCallRecord,
)
from labassistant.diagnosis.validation import (
    InvalidOutputError,
    check_against_project,
    parse_output,
)
from labassistant.knowledge.schema import ConceptGraph
from labassistant.llm.base import LLMClient, LLMResponse, Message, Usage
from labassistant.runner.sandbox import list_test_ids
from labassistant.runner.tool import RUN_TESTS_TOOL_NAME, RunTestsTool

UNPRICED = "unpriced"  # placeholder model name used when the client has none


class DiagnosisError(RuntimeError):
    """The diagnosis could not be completed (e.g. invalid output twice, refusal, too many turns)."""


class DiagnosisAgent:
    def __init__(
        self,
        client: LLMClient,
        graph: ConceptGraph,
        *,
        model_name: str = UNPRICED,
        context_mode: ContextMode = ContextMode.FULL,
        token_budget: int = 20_000,
        filter_limits: FilterLimits | None = None,
        runner_timeout_seconds: float = 10.0,
        max_output_tokens: int = 8_000,
        extra_prices: dict[str, ModelPrice] | None = None,
    ) -> None:
        self.client = client
        self.graph = graph
        self.model_name = model_name
        self.context_mode = context_mode
        self.token_budget = token_budget
        self.filter_limits = filter_limits or FilterLimits()
        self.runner_timeout_seconds = runner_timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.extra_prices = extra_prices

    def diagnose(
        self, request: ContextRequest, options: DiagnosisOptions | None = None
    ) -> DiagnosisResult:
        options = options or DiagnosisOptions()
        context = build_context(
            request,
            mode=self.context_mode,
            token_budget=self.token_budget,
            limits=self.filter_limits,
        )
        # The runner and validation use the same filtered files the context was built from.
        files = filter_project(request.files, request.selected_path, self.filter_limits).files
        tool = RunTestsTool(files, self.runner_timeout_seconds) if options.use_tool else None

        run = _Run(
            client=self.client,
            system=prompts.build_system_prompt(
                self.graph,
                context,
                use_tool=options.use_tool,
                include_concept_graph=options.include_concept_graph,
            ),
            tool=tool,
            options=options,
            max_output_tokens=self.max_output_tokens,
        )
        output, retried = run.until_valid_output(
            prompts.build_user_message(context, request.explanation)
        )

        # Test ids the model may cite: the project's tests plus any probe tests it ran.
        known_tests = set(list_test_ids(files)) | run.probe_test_ids
        checked, adjustments = check_against_project(output, self.graph, files, known_tests)
        clean, leak_adjustments = remove_leaks(checked)

        return DiagnosisResult(
            concept_gaps=clean.concept_gaps,
            quality_notes=clean.quality_notes,
            options=options,
            model=self.model_name,
            usage=run.usage,
            estimated_cost_usd=estimate_cost_usd(self.model_name, run.usage, self.extra_prices),
            turns=run.turns,
            tool_calls=run.tool_calls,
            adjustments=adjustments + leak_adjustments,
            context_summary=context.summary(),
            retried_invalid_output=retried,
        )


def remove_leaks(output: DiagnosisOutput) -> tuple[DiagnosisOutput, list[Adjustment]]:
    """Blank leaking gap rationales (the gap itself is still useful) and drop leaking notes."""
    adjustments: list[Adjustment] = []
    gaps = []
    for gap in output.concept_gaps:
        if findings := find_leaks(gap.rationale):
            adjustments.append(
                Adjustment(
                    action="leak_removed",
                    detail=f"rationale of {gap.concept_id}: "
                    f"{findings[0].reason}: {findings[0].snippet}",
                )
            )
            gap = gap.model_copy(update={"rationale": ""})
        gaps.append(gap)

    notes = []
    for note in output.quality_notes:
        if findings := find_leaks(note.explanation):
            adjustments.append(
                Adjustment(
                    action="leak_removed",
                    detail=f"{note.category} note at {note.path}:{note.start_line}: "
                    f"{findings[0].reason}: {findings[0].snippet}",
                )
            )
            continue
        notes.append(note)
    return DiagnosisOutput(concept_gaps=gaps, quality_notes=notes), adjustments


class _Run:
    """State for one diagnosis conversation: messages, usage and tool calls."""

    def __init__(
        self,
        *,
        client: LLMClient,
        system: str,
        tool: RunTestsTool | None,
        options: DiagnosisOptions,
        max_output_tokens: int,
    ) -> None:
        self.client = client
        self.system = system
        self.tool = tool
        self.options = options
        self.max_output_tokens = max_output_tokens
        self.messages: list[Message] = []
        self.usage = Usage()
        self.turns = 0
        self.tool_calls: list[ToolCallRecord] = []
        self.probe_test_ids: set[str] = set()

    def until_valid_output(self, user_message: str) -> tuple[DiagnosisOutput, bool]:
        """Returns (parsed output, whether a retry was needed)."""
        self.messages.append({"role": "user", "content": user_message})
        reply = self._converse()
        try:
            return parse_output(reply.text), False
        except InvalidOutputError as first_error:
            # One retry, telling the model exactly what was wrong.
            self.messages.append(
                {"role": "user", "content": prompts.RETRY_TEMPLATE.format(error=first_error)}
            )
            reply = self._converse()
            try:
                return parse_output(reply.text), True
            except InvalidOutputError as second_error:
                raise DiagnosisError(
                    f"model output was invalid twice; last error: {second_error}"
                ) from second_error

    def _converse(self) -> LLMResponse:
        """Call the model, running tools, until it stops with a final reply."""
        while True:
            if self.turns >= self.options.max_turns:
                raise DiagnosisError(f"no final answer after {self.options.max_turns} model calls")
            response = self.client.complete(
                system=self.system,
                messages=self.messages,
                tools=[self.tool.definition] if self.tool else None,
                max_tokens=self.max_output_tokens,
            )
            self.turns += 1
            self.usage = self.usage + response.usage
            # Append the content blocks unchanged: they carry tool ids and provider
            # details (e.g. Gemini thought signatures) needed on the next call.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                raise DiagnosisError("the model declined to diagnose this code")
            if response.stop_reason != "tool_use" or not response.tool_calls:
                return response
            self.messages.append({"role": "user", "content": self._run_tools(response)})

    def _run_tools(self, response: LLMResponse) -> list[dict]:
        results = []
        for call in response.tool_calls:
            if self.tool is None or call.name != RUN_TESTS_TOOL_NAME:
                content, is_error = f"Unknown tool {call.name!r}.", True
            elif len(self.tool_calls) >= self.options.max_tool_calls:
                content, is_error = prompts.TOOL_LIMIT_MESSAGE, True
            else:
                execution = self.tool.execute(call.input)
                content, is_error = execution.content, execution.is_error
                if execution.result is not None and execution.result.probe:
                    self.probe_test_ids.update(t.test_id for t in execution.result.tests)
                self.tool_calls.append(
                    ToolCallRecord(
                        input={k: v for k, v in call.input.items() if k != "probe_test_code"},
                        is_error=execution.is_error,
                        status=execution.result.status.value if execution.result else None,
                        probe_code=execution.probe_code,
                    )
                )
            # Every tool call must get a result, even refused ones.
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
        return results
