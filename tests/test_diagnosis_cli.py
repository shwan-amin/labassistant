import json

from labassistant.diagnosis import cli
from labassistant.llm import FakeLLMClient
from tests.context_helpers import SAMPLE_LABS


def test_parse_lines() -> None:
    assert (cli.parse_lines("12-20").start, cli.parse_lines("12-20").end) == (12, 20)
    assert cli.parse_lines("7").end == 7


def test_read_project_skips_caches_and_binary(tmp_path) -> None:
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_bytes(b"\x00\xff")
    (tmp_path / "image.bin").write_bytes(b"\xff\xfe\x00")
    (tmp_path / "main.py").write_text("x = 1\n")
    assert [f.path for f in cli.read_project(tmp_path)] == ["main.py"]


def test_main_prints_json_without_probe_code(monkeypatch, capsys) -> None:
    probe = "def test_probe():\n    assert True\n"
    fake = FakeLLMClient(
        [
            FakeLLMClient.tool_use("run_tests", {"probe_test_code": probe}),
            FakeLLMClient.text('{"concept_gaps": [], "quality_notes": []}'),
        ]
    )
    monkeypatch.setattr(cli, "create_llm_client", lambda settings: fake)

    code = cli.main([str(SAMPLE_LABS / "file_tree"), "metrics.py", "20-27"])

    output = capsys.readouterr().out
    assert code == 0
    assert json.loads(output)["concept_gaps"] == []
    assert "assert True" not in output
