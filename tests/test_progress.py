import json

import pytest

from tukey import analyzer
from tukey.cli import main


def test_progress_arrives_before_parsing_and_respects_exclusions(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app/main.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules/ignored.js").write_text("", encoding="utf-8")
    (tmp_path / "excluded").mkdir()
    (tmp_path / "excluded/ignored.py").write_text("", encoding="utf-8")
    messages = []
    original_parse = analyzer.parse

    def parse(*args):
        assert "Scanning directory: ." in messages
        assert "Scanning directory: app" in messages
        assert messages[-1] == "Analyzing file [1/1] (100%): app/main.py"
        return original_parse(*args)

    monkeypatch.setattr(analyzer, "parse", parse)
    report = analyzer.analyze(tmp_path, excludes=["excluded"], progress=messages.append)

    assert report["summary"]["file_count"] == 1
    assert not any(
        "node_modules" in message or "excluded" in message for message in messages
    )
    assert (
        messages[-1]
        == "Analysis complete: 1/1 files analyzed, 1 modules, 0 diagnostics"
    )


def test_progress_continues_after_unreadable_file(tmp_path):
    (tmp_path / "bad.py").write_bytes(b"\xff")
    (tmp_path / "good.py").write_text("value = 1\n", encoding="utf-8")
    messages = []

    analyzer.analyze(tmp_path, progress=messages.append)

    assert "Analyzing file [1/2] (50%): bad.py" in messages
    assert any(message.startswith("Cannot read file bad.py:") for message in messages)
    assert "Analyzing file [2/2] (100%): good.py" in messages
    assert (
        messages[-1]
        == "Analysis complete: 1/2 files analyzed, 1 modules, 1 diagnostics"
    )


def test_empty_directory_progress(tmp_path):
    messages = []
    analyzer.analyze(tmp_path, progress=messages.append)
    assert "Discovery complete: 0 source files" in messages
    assert (
        messages[-1]
        == "Analysis complete: 0/0 files analyzed, 0 modules, 0 diagnostics"
    )


@pytest.mark.parametrize("quiet", [[], ["--quiet"], ["-q"]])
def test_cli_progress_keeps_stdout_valid_json(tmp_path, capsys, quiet):
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")

    assert main([str(source), "-o", "-", *quiet]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["summary"]["file_count"] == 1
    if quiet:
        assert captured.err == ""
    else:
        assert "tukey: Analyzing file [1/1] (100%): sample.py" in captured.err
        assert "tukey: Analysis complete:" in captured.err


def test_quiet_keeps_cli_errors(tmp_path, capsys):
    assert main([str(tmp_path / "missing"), "--quiet"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Path does not exist:" in captured.err


def test_library_analysis_is_silent_by_default(tmp_path, capsys):
    analyzer.analyze(tmp_path)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
