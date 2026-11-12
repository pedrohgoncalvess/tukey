import json
from pathlib import Path

import pytest
import yaml

from tukey.analyzer import analyze
from tukey.cli import main
from tukey.config import load_config


def write(root, relative, source="value = 1\n"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def preset(root, **options):
    return write(root, "tukey.yaml", yaml.safe_dump(options))


def test_preset_resolves_paths_from_config_and_creates_reports(
    tmp_path, monkeypatch, capsys
):
    project = tmp_path / "project"
    write(project, "src/main.py")
    config = preset(
        project,
        path="src",
        format="both",
        output_dir="reports",
        output="metrics.json",
        html="map.html",
        quiet=True,
    )
    monkeypatch.chdir(tmp_path)

    assert main(["--config", str(config)]) == 0
    report = json.loads((project / "reports/metrics.json").read_text(encoding="utf-8"))
    assert report["root"] == str((project / "src").resolve())
    assert report["files"][0]["path"] == "main.py"
    assert '<svg id="graph"' in (project / "reports/map.html").read_text(
        encoding="utf-8"
    )
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_config_filters_nested_directories_extensions_and_pages(tmp_path, capsys):
    for file in (
        "main.py",
        "database/bad.py",
        "app/database/bad.py",
        "app/log/bad.py",
        "app/keep.py",
        "src/pages/old.py",
    ):
        write(tmp_path, file)
    write(tmp_path, "types.d.ts", "declare const value: number;")
    write(tmp_path, "main.ts", "const value = 1;")
    config = preset(
        tmp_path,
        ignore_dirs=" database, log, , ",
        ignore_extensions=["*.d.ts"],
        exclude=["src/pages/*"],
        quiet=True,
    )

    assert main(["--config", str(config), "-o", "-"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [file["path"] for file in report["files"]] == [
        "app/keep.py",
        "main.py",
        "main.ts",
    ]
    assert {"database", "log"} <= set(report["analysis"]["ignored_directories"])
    assert "*.d.ts" in report["analysis"]["excludes"]


def test_cli_replaces_preset_lists_and_can_enable_logs(tmp_path, capsys):
    write(tmp_path, "database/file.py")
    write(tmp_path, "log/file.py")
    write(tmp_path, "cache/file.py")
    config = preset(tmp_path, ignore_dirs=["database"], quiet=True)

    assert (
        main(
            [
                "--config",
                str(config),
                "--ignore-dirs",
                " log, , ",
                "--ignore-dirs",
                " cache ",
                "--no-quiet",
                "-o",
                "-",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert [file["path"] for file in json.loads(captured.out)["files"]] == [
        "database/file.py"
    ]
    assert "Scanning directory: database" in captured.err
    assert "Scanning directory: log" not in captured.err


@pytest.mark.parametrize("format", ["json", "html", "both"])
def test_cli_format_overrides_preset_outputs(tmp_path, capsys, format):
    write(tmp_path, "main.py")
    config = preset(
        tmp_path, format="both", output="report.json", html="report.html", quiet=True
    )

    assert main(["--config", str(config), "--format", format]) == 0
    assert (tmp_path / "report.json").exists() == (format != "html")
    assert (tmp_path / "report.html").exists() == (format != "json")
    assert capsys.readouterr().out == ""


def test_cli_paths_override_preset_and_use_current_directory(
    tmp_path, monkeypatch, capsys
):
    write(tmp_path, "app/main.py")
    config = preset(
        tmp_path / "config",
        path="missing",
        output_dir="old",
        output="old.json",
        quiet=True,
    )
    monkeypatch.chdir(tmp_path)

    assert (
        main(["app", "--config", str(config), "--output-dir", "new", "-o", "new.json"])
        == 0
    )
    assert (tmp_path / "new/new.json").is_file()
    assert not (config.parent / "old").exists()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("format,flag", [("json", "--html"), ("html", "--output")])
def test_cli_report_flag_enables_format_disabled_in_preset(
    tmp_path, capsys, format, flag
):
    write(tmp_path, "main.py")
    config = preset(tmp_path, format=format, output_dir="reports", quiet=True)
    name = "extra.html" if flag == "--html" else "extra.json"
    assert main(["--config", str(config), flag, name]) == 0
    assert (tmp_path / "reports" / name).is_file()
    other = "report.json" if flag == "--html" else "report.html"
    assert (tmp_path / "reports" / other).is_file()
    assert capsys.readouterr().out == ""


def test_cli_output_directory_uses_default_filenames(tmp_path, capsys):
    source = write(tmp_path, "main.py")
    output_dir = tmp_path / "nested/reports"
    assert (
        main([str(source), "--format", "both", "--output-dir", str(output_dir), "-q"])
        == 0
    )
    assert (
        json.loads((output_dir / "report.json").read_text(encoding="utf-8"))["summary"][
            "file_count"
        ]
        == 1
    )
    assert (output_dir / "report.html").is_file()
    assert capsys.readouterr().out == ""


def test_html_filename_override_preserves_html_only_preset(tmp_path, capsys):
    write(tmp_path, "main.py")
    config = preset(tmp_path, format="html", quiet=True)
    html = tmp_path / "custom.html"
    assert main(["--config", str(config), "--html", str(html)]) == 0
    assert html.is_file()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("extension", ["ts", ".ts", "*.ts", " .TS, , "])
def test_ignore_extensions_cli_and_single_file(tmp_path, capsys, extension):
    source = write(tmp_path, "main.TS", "const value = 1;")
    assert main([str(source), "--ignore-extensions", extension, "-q", "-o", "-"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["file_count"] == 0


def test_excluded_single_file_and_ignored_directory_are_not_scanned(tmp_path):
    source = write(tmp_path, "main.py")
    assert analyze(source, excludes=["*.py"])["files"] == []
    write(tmp_path, "database/broken.py", "\ufffd")
    messages = []
    report = analyze(tmp_path, ignore_dirs="database, log", progress=messages.append)
    assert report["summary"]["file_count"] == 1
    assert not any("Scanning directory: database" in message for message in messages)


@pytest.mark.parametrize(
    "content",
    [
        "[unclosed",
        "- not a mapping",
        "unknown_option: true",
        "quiet: yesplease",
        "exclude: '*.py'",
        "ignore_dirs: [12]",
        "output: false",
        "format: pdf",
        "path: []",
        "html: 5",
        "!!python/object/apply:os.system ['echo unsafe']",
    ],
)
def test_invalid_config_returns_cli_error(tmp_path, capsys, content):
    config = write(tmp_path, "invalid.yaml", content)
    assert main(["--config", str(config)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "tukey:" in captured.err


def test_config_cannot_be_overwritten_by_report(tmp_path, capsys):
    write(tmp_path, "main.py")
    config = preset(tmp_path, output="tukey.yaml", quiet=True)
    original = config.read_bytes()
    assert main(["--config", str(config)]) == 2
    assert "would overwrite an input file" in capsys.readouterr().err
    assert config.read_bytes() == original


def test_missing_config_and_default_current_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "main.py")
    assert main(["--config", "missing.yaml"]) == 2
    assert capsys.readouterr().out == ""
    assert main(["-q", "-o", "-"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["file_count"] == 1


def test_example_is_a_valid_preset():
    options = load_config(Path(__file__).parents[1] / "tukey.example.yaml")
    assert options["format"] == "both"
    assert options["ignore_dirs"] == ["database", "log", "generated"]
