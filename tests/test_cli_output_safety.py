import json
from pathlib import Path

import pytest

from tukey.cli import main


def alias_to(path, alias, kind):
    try:
        if kind == "symlink":
            alias.symlink_to(path)
        else:
            alias.hardlink_to(path)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"{kind} is not available: {error}")
    return alias


@pytest.mark.parametrize("analysis", ["file", "directory"])
@pytest.mark.parametrize("flag", ["--output", "--html"])
@pytest.mark.parametrize("alias", ["direct", "relative", "symlink", "hardlink"])
def test_source_output_conflicts_preserve_all_files(
    tmp_path, monkeypatch, capsys, analysis, flag, alias
):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "sample.py"
    original = b"def main():\n    return 42\n"
    source.write_bytes(original)
    monkeypatch.chdir(tmp_path)
    output = source
    if alias == "relative":
        output = Path("project/../project/sample.py")
    elif alias in {"symlink", "hardlink"}:
        output = alias_to(source, tmp_path / "report-alias", alias)
    other = tmp_path / ("other.html" if flag == "--output" else "other.json")
    other.write_bytes(b"existing report must be preserved")
    other_flag = "--html" if flag == "--output" else "--output"

    result = main(
        [
            str(source if analysis == "file" else project),
            flag,
            str(output),
            other_flag,
            str(other),
        ]
    )

    assert result == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "would overwrite an input file" in captured.err
    assert source.read_bytes() == original
    assert output.read_bytes() == original
    assert other.read_bytes() == b"existing report must be preserved"


@pytest.mark.parametrize("flag", ["--output", "--html"])
def test_unreadable_utf8_source_is_protected(tmp_path, capsys, flag):
    source = tmp_path / "invalid.py"
    source.write_bytes(b"\xff\xfe\x00")
    assert main([str(tmp_path), flag, str(source)]) == 2
    assert source.read_bytes() == b"\xff\xfe\x00"
    assert "would overwrite an input file" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--output", "--html"])
@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink"])
def test_coverage_input_is_protected(tmp_path, capsys, flag, alias):
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    coverage = tmp_path / "coverage.json"
    original = json.dumps(
        {
            "meta": {},
            "files": {"sample.py": {"executed_lines": [1], "missing_lines": []}},
        }
    ).encode()
    coverage.write_bytes(original)
    output = coverage
    if alias != "direct":
        output = alias_to(coverage, tmp_path / "coverage-alias", alias)
    other = tmp_path / "other-report"
    other_flag = "--html" if flag == "--output" else "--output"

    assert (
        main(
            [
                str(source),
                "--coverage",
                str(coverage),
                flag,
                str(output),
                other_flag,
                str(other),
            ]
        )
        == 2
    )
    assert "would overwrite an input file" in capsys.readouterr().err
    assert coverage.read_bytes() == original
    assert not other.exists()


@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink"])
def test_outputs_cannot_alias_each_other(tmp_path, capsys, alias):
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    output = tmp_path / "existing-report"
    output.write_bytes(b"original report")
    html = output if alias == "direct" else alias_to(output, tmp_path / "alias", alias)

    assert main([str(source), "--output", str(output), "--html", str(html)]) == 2
    assert "must use different paths" in capsys.readouterr().err
    assert output.read_bytes() == b"original report"


def test_reports_inside_analyzed_directory_remain_supported(tmp_path, capsys):
    source = tmp_path / "sample.py"
    original = b"value = 1\n"
    source.write_bytes(original)
    output = tmp_path / "report.json"
    html = tmp_path / "report.html"

    assert main([str(tmp_path), "--output", str(output), "--html", str(html)]) == 0
    assert capsys.readouterr().out == ""
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["file_count"] == 1
    assert '<svg id="graph"' in html.read_text(encoding="utf-8")
    assert source.read_bytes() == original
