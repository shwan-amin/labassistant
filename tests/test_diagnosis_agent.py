import json
from pathlib import Path

import pytest

from labassistant.context import ContextMode, ContextRequest, LineRange
from labassistant.diagnosis import DiagnosisAgent, DiagnosisError, DiagnosisOptions
from labassistant.diagnosis.cost import estimate_cost_usd
from labassistant.knowledge import load_topic
from labassistant.llm import FakeLLMClient, Usage
from tests.context_helpers import find_line, load_lab

GRAPH = load_topic("recursion", Path(__file__).parent.parent / "knowledge")
FAILING_TEST = "tests/test_metrics.py::test_count_files_ignores_directories"


@pytest.fixture(scope="module")
def seeded_lab():
    """file_tree with a seeded base_case_wrong_value bug in count_files."""
    return [
        f.model_copy(update={"content": f.content.replace("count = 0", "count = 1")})
        if f.path == "metrics.py"
        else f
        for f in load_lab("file_tree")
    ]


@pytest.fixture
def request_for(seeded_lab):
    line = find_line(seeded_lab, "metrics.py", "count = 1")
    return ContextRequest(
        files=seeded_lab,
        selected_path="metrics.py",
        selection=LineRange(start=line - 2, end=line + 3),
        explanation="I count the files inside each directory recursively.",
    )


def diagnosis_json(line: int, **gap_overrides) -> str:
    gap = {
        "concept_id": "base_case",
        "misconception_id": "base_case_wrong_value",
        "confidence": "high",
        "evidence": [
            {"path": "metrics.py", "start_line": line, "end_line": line, "test_ids": [FAILING_TEST]}
        ],
        "rationale": "An empty directory is counted as containing a file.",
    }
    gap.update(gap_overrides)
    note = {
        "category": "readability",
        "path": "metrics.py",
        "start_line": line,
        "end_line": line,
        "explanation": "The starting value's meaning is not obvious; a short comment would help.",
    }
    return json.dumps({"concept_gaps": [gap], "quality_notes": [note]})


def agent(fake: FakeLLMClient, **kwargs) -> DiagnosisAgent:
    return DiagnosisAgent(fake, GRAPH, **kwargs)


def test_tool_loop_runs_real_tests_and_returns_validated_diagnosis(request_for) -> None:
    line = find_line(request_for.files, "metrics.py", "count = 1")
    fake = FakeLLMClient(
        [
            FakeLLMClient.tool_use("run_tests", {"test_ids": [FAILING_TEST]}),
            FakeLLMClient.text(diagnosis_json(line)),
        ]
    )
    result = agent(fake).diagnose(request_for)

    # The fake model saw a real sandbox run of the seeded bug.
    tool_result = fake.calls[1].messages[-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert json.loads(tool_result["content"])["status"] == "failed"

    [gap] = result.concept_gaps
    assert gap.misconception_id == "base_case_wrong_value"
    assert gap.evidence[0].test_ids == [FAILING_TEST]
    assert len(result.quality_notes) == 1
    assert result.turns == 2
    assert result.tool_calls[0].status == "failed"
    assert result.adjustments == []
    assert result.usage.input_tokens > 0  # the fake estimates usage
    assert result.estimated_cost_usd is None  # no price for the placeholder model


def test_prompt_layout_stable_system_and_changing_user_message(request_for) -> None:
    fake = FakeLLMClient([FakeLLMClient.text('{"concept_gaps": [], "quality_notes": []}')])
    agent(fake).diagnose(request_for)

    call = fake.calls[0]
    assert "ACADEMIC INTEGRITY" in call.system
    assert "base_case_wrong_value" in call.system  # full concept graph
    assert "### Map of metrics.py" in call.system  # stable project overview
    assert "Selected code" not in call.system
    user = call.messages[0]["content"]
    assert "Selected code: metrics.py" in user
    assert "I count the files inside each directory recursively." in user
    assert call.tools and call.tools[0]["name"] == "run_tests"


def test_flags_remove_tool_and_concept_graph(request_for) -> None:
    fake = FakeLLMClient([FakeLLMClient.text('{"concept_gaps": [], "quality_notes": []}')])
    options = DiagnosisOptions(use_tool=False, include_concept_graph=False)
    result = agent(fake).diagnose(request_for, options)

    call = fake.calls[0]
    assert call.tools is None
    assert "TOOLS: none are available" in call.system
    assert "- base_case: Base case" in call.system
    assert "base_case_wrong_value" not in call.system  # no misconception catalogue
    assert result.options == options


def test_invalid_output_is_retried_once_with_the_error(request_for) -> None:
    line = find_line(request_for.files, "metrics.py", "count = 1")
    fake = FakeLLMClient(
        [
            FakeLLMClient.text("I think it's the base case."),
            FakeLLMClient.text(diagnosis_json(line)),
        ]
    )
    result = agent(fake).diagnose(request_for)

    assert result.retried_invalid_output
    assert "could not be used: no JSON object" in fake.calls[1].messages[-1]["content"]
    assert len(result.concept_gaps) == 1


def test_invalid_output_twice_fails_clearly(request_for) -> None:
    fake = FakeLLMClient([FakeLLMClient.text("nope"), FakeLLMClient.text("{still not json")])
    with pytest.raises(DiagnosisError, match="invalid twice"):
        agent(fake).diagnose(request_for)


def test_refusal_fails_clearly(request_for) -> None:
    refusal = FakeLLMClient.text("")
    refusal.stop_reason = "refusal"
    with pytest.raises(DiagnosisError, match="declined"):
        agent(FakeLLMClient([refusal])).diagnose(request_for)


def test_tool_call_limit_is_enforced(request_for) -> None:
    fake = FakeLLMClient(
        [
            FakeLLMClient.tool_use("run_tests", {"test_ids": [FAILING_TEST]}, call_id="a"),
            FakeLLMClient.tool_use("run_tests", {}, call_id="b"),
            FakeLLMClient.text('{"concept_gaps": [], "quality_notes": []}'),
        ]
    )
    result = agent(fake).diagnose(request_for, DiagnosisOptions(max_tool_calls=1))

    assert len(result.tool_calls) == 1
    second_result = fake.calls[2].messages[-1]["content"][0]
    assert second_result["is_error"] and "limit reached" in second_result["content"]


def test_too_many_turns_fails(request_for) -> None:
    calls = [FakeLLMClient.tool_use("run_tests", {}, call_id=str(i)) for i in range(3)]
    with pytest.raises(DiagnosisError, match="no final answer"):
        agent(FakeLLMClient(calls)).diagnose(
            request_for, DiagnosisOptions(max_turns=3, max_tool_calls=0)
        )


def test_unknown_tool_gets_error_result(request_for) -> None:
    fake = FakeLLMClient(
        [
            FakeLLMClient.tool_use("delete_files", {}),
            FakeLLMClient.text('{"concept_gaps": [], "quality_notes": []}'),
        ]
    )
    agent(fake).diagnose(request_for)
    result = fake.calls[1].messages[-1]["content"][0]
    assert result["is_error"] and "Unknown tool" in result["content"]


def test_probe_tests_can_be_cited_and_probe_code_stays_internal(request_for) -> None:
    probe = (
        "from metrics import count_files\nfrom tree import Node\n\n"
        "def test_empty_directory_has_no_files():\n"
        "    assert count_files(Node.directory('d')) == 0\n"
    )
    probe_id = "test_labassistant_probe.py::test_empty_directory_has_no_files"
    line = find_line(request_for.files, "metrics.py", "count = 1")
    fake = FakeLLMClient(
        [
            FakeLLMClient.tool_use("run_tests", {"probe_test_code": probe}),
            FakeLLMClient.text(
                diagnosis_json(
                    line,
                    evidence=[
                        {
                            "path": "metrics.py",
                            "start_line": line,
                            "end_line": line,
                            "test_ids": [probe_id],
                        }
                    ],
                )
            ),
        ]
    )
    result = agent(fake).diagnose(request_for)

    assert result.concept_gaps[0].evidence[0].test_ids == [probe_id]
    assert result.tool_calls[0].probe_code == probe  # internal record for logs
    assert "probe_test_code" not in result.tool_calls[0].input
    student_facing = result.model_dump_json(include={"concept_gaps", "quality_notes"})
    assert "count_files(Node.directory" not in student_facing


def test_leaks_are_removed_from_student_facing_text(request_for) -> None:
    line = find_line(request_for.files, "metrics.py", "count = 1")
    leaky = json.loads(diagnosis_json(line, rationale="Change the start to `count = 0`."))
    leaky["quality_notes"][0]["explanation"] = (
        "Write it as:\n```\nreturn sum(count_files(c) for c in node.children)\n```"
    )
    fake = FakeLLMClient([FakeLLMClient.text(json.dumps(leaky))])
    result = agent(fake).diagnose(request_for)

    assert result.concept_gaps[0].rationale == ""  # gap kept, text removed
    assert result.quality_notes == []
    assert result.leaks_removed == 2


def test_context_mode_is_applied(request_for) -> None:
    fake = FakeLLMClient([FakeLLMClient.text('{"concept_gaps": [], "quality_notes": []}')])
    result = agent(fake, context_mode=ContextMode.SELECTION_ONLY).diagnose(request_for)

    assert result.context_summary["mode"] == "selection_only"
    assert "Rest of metrics.py" not in fake.calls[0].messages[0]["content"]


def test_cost_estimate_for_priced_model(request_for) -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000)
    fake = FakeLLMClient(
        [FakeLLMClient.text('{"concept_gaps": [], "quality_notes": []}', usage=usage)]
    )
    result = agent(fake, model_name="claude-sonnet-5").diagnose(request_for)

    assert result.estimated_cost_usd == pytest.approx(3.0)
    assert estimate_cost_usd("gemini-3.6-flash", usage) is None
