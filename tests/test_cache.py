import hashlib
import json
import os

import pytest

from tukey import analyzer
from tukey.cli import main
from .test_analyzer import SAMPLES
from .test_config import preset, write


def manifest(root):
    return json.loads((root / ".tukey/cache.json").read_text(encoding="utf-8"))


def test_cache_reuses_raw_metrics_for_all_languages(tmp_path, monkeypatch):
    for language, (extension, source) in SAMPLES.items():
        write(tmp_path, language + "/sample" + extension, source)
    original = analyzer.parse
    calls = []

    def parse(*args):
        calls.append(args[0])
        return original(*args)

    monkeypatch.setattr(analyzer, "parse", parse)
    first = analyzer.analyze(tmp_path)
    assert len(calls) == len(SAMPLES)
    calls.clear()
    second = analyzer.analyze(tmp_path)
    assert calls == []
    assert second == first
    assert analyzer.analyze(tmp_path, cache=False) == first
    assert len(calls) == len(SAMPLES)
    for path, entry in manifest(tmp_path)["files"].items():
        assert (
            entry["hash"] == hashlib.sha256((tmp_path / path).read_bytes()).hexdigest()
        )


def test_only_changed_content_is_reparsed_even_with_same_size_and_mtime(
    tmp_path, monkeypatch
):
    source = write(tmp_path, "changed.py", "def first(): pass\n")
    write(tmp_path, "unchanged.py", "def same(): pass\n")
    analyzer.analyze(tmp_path)
    old_hash = manifest(tmp_path)["files"]["changed.py"]["hash"]
    stat = source.stat()
    source.write_text("def other(): pass\n", encoding="utf-8")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert source.stat().st_size == stat.st_size
    original = analyzer.parse
    calls = []

    def parse(*args):
        calls.append(args[0])
        return original(*args)

    monkeypatch.setattr(analyzer, "parse", parse)
    report = analyzer.analyze(tmp_path)
    assert calls == [source.read_bytes()]
    assert report["files"][0]["declarations"][0]["name"] == "other"
    assert manifest(tmp_path)["files"]["changed.py"]["hash"] != old_hash


def test_project_relations_and_removed_files_are_recomputed(tmp_path, monkeypatch):
    write(tmp_path, "main.py", "from helper import work\nwork()\n")
    helper = write(tmp_path, "helper.py", "def work(): pass\n")
    analyzer.analyze(tmp_path)
    helper.unlink()

    def unexpected_parse(*args):
        pytest.fail("The unchanged importer should use cached syntax")

    monkeypatch.setattr(analyzer, "parse", unexpected_parse)
    report = analyzer.analyze(tmp_path)
    assert [file["path"] for file in report["files"]] == ["main.py"]
    assert report["files"][0]["imports"][0]["resolved_files"] == []
    assert report["files"][0]["imports"][0]["resolution"] != "resolved"
    assert "helper.py" not in json.dumps(report["call_graph"])


def test_coverage_is_refreshed_on_cache_hits(tmp_path, monkeypatch):
    write(tmp_path, "main.py", "value = 1\n")
    coverage = tmp_path / "coverage.json"

    def set_coverage(executed, missing):
        coverage.write_text(
            json.dumps(
                {
                    "meta": {},
                    "files": {
                        "main.py": {
                            "executed_lines": executed,
                            "missing_lines": missing,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    set_coverage([], [1])
    first = analyzer.analyze(tmp_path, coverage=coverage)
    assert first["summary"]["test_coverage"]["lines"]["covered"] == 0
    set_coverage([1], [])
    monkeypatch.setattr(
        analyzer, "parse", lambda *args: pytest.fail("Unexpected parsing")
    )
    second = analyzer.analyze(tmp_path, coverage=coverage)
    assert second["summary"]["test_coverage"]["lines"]["covered"] == 1


def test_entry_points_and_filters_do_not_pollute_cached_metrics(tmp_path, monkeypatch):
    write(tmp_path, "main.py", "def start(): pass\ndef other(): pass\n")
    write(tmp_path, "extra.py")
    analyzer.analyze(tmp_path, entry_points=["main.py#start"])
    expected = analyzer.analyze(tmp_path, entry_points=["main.py#other"], cache=False)
    monkeypatch.setattr(
        analyzer, "parse", lambda *args: pytest.fail("Unexpected parsing")
    )
    assert analyzer.analyze(tmp_path, entry_points=["main.py#other"]) == expected
    assert (
        analyzer.analyze(tmp_path, excludes=["extra.py"])["summary"]["file_count"] == 1
    )
    assert analyzer.analyze(tmp_path)["summary"]["file_count"] == 2


@pytest.mark.parametrize("corruption", ["truncated", "version", "metrics"])
def test_bad_cache_is_rebuilt(tmp_path, monkeypatch, corruption):
    write(tmp_path, "main.py")
    expected = analyzer.analyze(tmp_path)
    path = tmp_path / ".tukey/cache.json"
    data = manifest(tmp_path)
    if corruption == "truncated":
        path.write_text("{", encoding="utf-8")
    else:
        if corruption == "version":
            data["cache_version"] = -1
        else:
            data["files"]["main.py"]["metrics"]["size"]["lines"] = 999
        path.write_text(json.dumps(data), encoding="utf-8")
    original = analyzer.parse
    calls = []

    def parse(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(analyzer, "parse", parse)
    assert analyzer.analyze(tmp_path) == expected
    assert calls == [1]
    assert manifest(tmp_path)["cache_version"] == 1


def test_cache_disabled_does_not_read_or_write_cache(tmp_path, monkeypatch):
    write(tmp_path, "main.py")
    monkeypatch.setattr(
        analyzer, "ParseCache", lambda *args: pytest.fail("Cache was accessed")
    )
    analyzer.analyze(tmp_path, cache=False)
    assert not (tmp_path / ".tukey").exists()


def test_no_cache_leaves_existing_cache_untouched(tmp_path, capsys):
    write(tmp_path, "main.py")
    analyzer.analyze(tmp_path)
    cache_path = tmp_path / ".tukey/cache.json"
    original = cache_path.read_bytes()
    timestamp = cache_path.stat().st_mtime_ns
    write(tmp_path, "main.py", "def changed(): pass\n")
    assert main([str(tmp_path), "--no-cache", "-q"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["files"][0]["declarations"][0]["name"]
        == "changed"
    )
    assert cache_path.read_bytes() == original
    assert cache_path.stat().st_mtime_ns == timestamp


def test_forced_html_format_uses_internal_default_destination(tmp_path, capsys):
    write(tmp_path, "main.py")
    config = preset(tmp_path, format="both", html=False, quiet=True)
    assert main(["--config", str(config)]) == 0
    assert (tmp_path / ".tukey/report.html").is_file()
    assert not (tmp_path / "report.html").exists()


def test_cached_file_is_not_reused_when_unreadable(tmp_path, monkeypatch):
    source = write(tmp_path, "main.py")
    analyzer.analyze(tmp_path)
    original = type(source).read_bytes

    def read_bytes(path):
        if path == source:
            raise PermissionError("unreadable source")
        return original(path)

    monkeypatch.setattr(type(source), "read_bytes", read_bytes)
    report = analyzer.analyze(tmp_path)
    assert report["files"] == []
    assert report["diagnostics"][0]["code"] == "read_error"


def test_internal_directory_is_never_analyzed(tmp_path):
    write(tmp_path, "main.py")
    write(tmp_path, ".tukey/internal.py", "def f(:\n")
    report = analyzer.analyze(tmp_path, no_exclusion=True)
    assert [file["path"] for file in report["files"]] == ["main.py"]


def test_cli_defaults_save_reports_and_print_portable_links(tmp_path, capsys):
    project = tmp_path / "project with spaces"
    write(project, "main.py")
    assert main([str(project)]) == 0
    output = project / ".tukey"
    assert (output / "cache.json").is_file()
    assert (
        json.loads((output / "report.json").read_text(encoding="utf-8"))["summary"][
            "file_count"
        ]
        == 1
    )
    assert '<svg id="graph"' in (output / "report.html").read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (output / "report.html").as_uri() in captured.err
    assert str(output / "report.json") in captured.err
    assert output.as_uri() in captured.err
    assert main([str(project)]) == 0
    assert "Cache hit: main.py" in capsys.readouterr().err


def test_no_cache_cli_and_yaml_do_not_create_internal_directory(tmp_path, capsys):
    write(tmp_path, "main.py")
    config = preset(tmp_path, cache=True, quiet=True)
    assert main(["--config", str(config), "--no-cache"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["file_count"] == 1
    assert not (tmp_path / ".tukey").exists()
    config = preset(tmp_path, cache=False, quiet=True)
    assert main(["--config", str(config)]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["file_count"] == 1
    assert not (tmp_path / ".tukey").exists()


def test_stdout_is_explicitly_available_with_caching(tmp_path, capsys):
    write(tmp_path, "main.py")
    assert main([str(tmp_path), "-o", "-", "-q"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["file_count"] == 1
    assert (tmp_path / ".tukey/report.html").is_file()


def test_reports_cannot_replace_cache_manifest(tmp_path, capsys):
    write(tmp_path, "main.py")
    assert main([str(tmp_path), "-o", str(tmp_path / ".tukey/cache.json")]) == 2
    assert not (tmp_path / ".tukey").exists()
    assert "different paths" in capsys.readouterr().err


def test_yaml_input_cannot_be_overwritten_by_cache(tmp_path, capsys):
    write(tmp_path, "main.py")
    config = write(tmp_path, ".tukey/cache.json", json.dumps({"path": str(tmp_path)}))
    original = config.read_bytes()
    assert main(["--config", str(config)]) == 2
    assert config.read_bytes() == original
    assert "would overwrite an input file" in capsys.readouterr().err
