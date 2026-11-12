import json

import pytest

from tukey.analyzer import analyze, default_exclusions
from tukey.cli import main
from .test_config import preset, write


@pytest.fixture
def project(tmp_path):
    for name in (
        "main.py",
        "app/__pycache__/cached.py",
        "app/target/generated.py",
        "app/node_modules/dependency.py",
        "app/npm_modules/dependency.py",
        ".uv-cache/cached.py",
        "example.egg-info/generated.py",
    ):
        write(tmp_path, name)
    write(tmp_path, "bundle.min.js", "const value = 1;")
    write(tmp_path, "main.js", "const value = 1;")
    write(tmp_path, ".gitignore", "ignored")
    write(tmp_path, ".dockerignore", "ignored")
    return tmp_path


def paths(report):
    return {file["path"] for file in report["files"]}


def test_defaults_prune_directories_and_filter_files(project):
    messages = []
    report = analyze(project, progress=messages.append)
    assert paths(report) == {"main.py", "main.js"}
    assert not any("Scanning directory: app/" in message for message in messages)
    assert "target" in report["analysis"]["ignored_directories"]
    assert ".gitignore" in report["analysis"]["excludes"]
    assert ".dockerignore" in report["analysis"]["excludes"]


def test_bare_cli_flag_removes_all_defaults(project, capsys):
    assert main([str(project), "--no-exclusion", "-q", "-o", "-"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(paths(report)) == 9
    assert "bundle.min.js" in paths(report)
    assert report["analysis"]["ignored_directories"] == [".tukey"]
    assert report["analysis"]["excludes"] == []


def test_pattern_cli_flag_removes_only_matching_defaults(project, capsys):
    assert main([str(project), "--no-exclusion", "**pycache**", "-q", "-o", "-"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert paths(report) == {"main.py", "main.js", "app/__pycache__/cached.py"}
    assert "__pycache__" not in report["analysis"]["ignored_directories"]
    assert "target" in report["analysis"]["ignored_directories"]
    assert ".gitignore" in report["analysis"]["excludes"]


def test_repeatable_comma_separated_selectors(project, capsys):
    assert (
        main(
            [
                str(project),
                "--no-exclusion",
                " target, node_modules, , ",
                "--no-exclusion",
                "**pycache**",
                "-q",
                "-o",
                "-",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert paths(report) == {
        "main.py",
        "main.js",
        "app/__pycache__/cached.py",
        "app/target/generated.py",
        "app/node_modules/dependency.py",
    }
    assert "npm_modules" in report["analysis"]["ignored_directories"]


def test_selective_file_rule_override_and_single_file(project):
    source = project / "bundle.min.js"
    assert analyze(source)["files"] == []
    assert paths(analyze(source, no_exclusion="*.min.js")) == {"bundle.min.js"}
    assert paths(analyze(project, no_exclusion="*.min.js")) == {
        "main.py",
        "main.js",
        "bundle.min.js",
    }


@pytest.mark.parametrize("override", [True, "**pycache**"])
def test_explicit_filters_survive_default_overrides(project, override):
    report = analyze(
        project,
        no_exclusion=override,
        ignore_dirs=["__pycache__"],
        excludes=["*.js"],
        ignore_extensions=[".py"],
    )
    assert report["files"] == []
    assert "__pycache__" in report["analysis"]["ignored_directories"]
    assert "*.js" in report["analysis"]["excludes"]


@pytest.mark.parametrize(
    "value,expected",
    [
        (False, {"main.py", "main.js"}),
        ("**pycache**", {"main.py", "main.js", "app/__pycache__/cached.py"}),
        (["**pycache**"], {"main.py", "main.js", "app/__pycache__/cached.py"}),
    ],
)
def test_yaml_selective_override(project, capsys, value, expected):
    config = preset(project, no_exclusion=value, quiet=True)
    assert main(["--config", str(config), "-o", "-"]) == 0
    assert paths(json.loads(capsys.readouterr().out)) == expected


def test_cli_can_replace_yaml_selectors_with_disable_all(project, capsys):
    config = preset(project, no_exclusion=["**pycache**"], quiet=True)
    assert main(["--config", str(config), "--no-exclusion", "-o", "-"]) == 0
    assert len(paths(json.loads(capsys.readouterr().out))) == 9


def test_cli_selectors_replace_yaml_disable_all(project, capsys):
    config = preset(project, no_exclusion=True, quiet=True)
    assert (
        main(["--config", str(config), "--no-exclusion", "**pycache**", "-o", "-"]) == 0
    )
    assert paths(json.loads(capsys.readouterr().out)) == {
        "main.py",
        "main.js",
        "app/__pycache__/cached.py",
    }


@pytest.mark.parametrize("value", [42, [True], {"target": True}])
def test_invalid_yaml_override_is_rejected(tmp_path, capsys, value):
    config = preset(tmp_path, no_exclusion=value)
    assert main(["--config", str(config)]) == 2
    assert "no_exclusion" in capsys.readouterr().err


def test_overrides_do_not_mutate_defaults():
    original = default_exclusions()
    assert default_exclusions(True) == (set(), set())
    assert "__pycache__" not in default_exclusions("**pycache**")[0]
    assert default_exclusions() == original
