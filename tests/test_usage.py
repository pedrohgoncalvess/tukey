import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from tukey.analyzer import analyze
from tukey.html_report import graph_data, render_html
from .test_analyzer import write


def statuses(report):
    return {d["name"]: d["usage"] for f in report["files"] for d in f["declarations"]}


def test_callbacks_types_methods_and_disconnected_cycle(tmp_path):
    write(
        tmp_path,
        "app.py",
        "from helper import callback as cb\nclass C:\n def run(self): pass\n def spare(self): pass\ndef start():\n register(cb)\n C().run()\ndef a(): b()\ndef b(): a()\n",
    )
    write(tmp_path, "helper.py", "def callback(): pass\ndef spare_function(): pass\n")
    write(tmp_path, "orphan.py", "class Orphan: pass\n")
    report = analyze(tmp_path, entry_points=["app.py#start"])
    usage = statuses(report)
    for name in ("start", "callback", "C", "run"):
        assert usage[name]["status"] == "referenced"
        assert usage[name]["reachable"] is True
    for name in ("a", "b", "spare", "spare_function", "Orphan"):
        assert usage[name]["status"] == "unused_candidate"
        assert usage[name]["reachable"] is False
    assert (
        next(f for f in report["files"] if f["path"] == "orphan.py")["usage"]["status"]
        == "unused_candidate"
    )
    assert report["summary"]["unused_candidates"]["files"] == 1
    jsonschema.validate(
        report,
        json.loads((Path(__file__).parents[1] / "docs/report.schema.json").read_text()),
    )


def test_namespace_callback_and_type_reference(tmp_path):
    write(
        tmp_path,
        "app.py",
        "import helpers as h\nfrom models import Entity as E\ndef start(x: E):\n register(h.callback)\n",
    )
    write(tmp_path, "helpers.py", "def callback(): pass\n")
    write(tmp_path, "models.py", "class Entity: pass\n")
    usage = statuses(analyze(tmp_path, entry_points=["app.py#start"]))
    assert usage["callback"]["status"] == "referenced"
    assert usage["Entity"]["status"] == "referenced"


def test_no_roots_and_self_recursion(tmp_path):
    write(tmp_path, "lib.py", "def recur(): recur()\ndef orphan(): pass\n")
    report = analyze(tmp_path)
    assert report["analysis"]["usage"]["mode"] == "references_only"
    assert all(u["reachable"] is None for u in statuses(report).values())
    assert statuses(report)["orphan"]["status"] == "unused_candidate"
    assert statuses(report)["recur"]["status"] == "referenced"


def test_public_api_protects_helpers_and_configuration(tmp_path):
    write(
        tmp_path,
        "main.ts",
        "export function api() { helper(); }\nfunction helper() {}\nfunction dead() {}\n",
    )
    report = analyze(tmp_path)
    assert statuses(report)["api"]["status"] == "unknown"
    assert statuses(report)["helper"]["status"] == "unknown"
    report = analyze(tmp_path, public_api=["main.ts#api"])
    assert statuses(report)["api"]["status"] == "referenced"
    assert statuses(report)["helper"]["reachable"] is True
    assert statuses(report)["dead"]["status"] == "unused_candidate"


def test_dynamic_framework_and_incomplete(tmp_path):
    write(
        tmp_path,
        "main.py",
        "class C:\n def __enter__(self): pass\n @route\n def handler(self): helper()\ndef helper(): pass\ndef start():\n getattr(C(), 'handler')()\n",
    )
    report = analyze(tmp_path, entry_points=["main.py#start"])
    assert statuses(report)["handler"]["status"] == "unknown"
    assert statuses(report)["helper"]["status"] == "unknown"
    assert statuses(report)["__enter__"]["status"] == "unknown"
    write(tmp_path, "broken.py", "def bad(:\n")
    report = analyze(tmp_path, entry_points=["main.py#start"])
    assert statuses(report)["helper"]["status"] == "unknown"


def test_same_directory_file_import_and_roots(tmp_path):
    write(tmp_path, "main.py", "import helper\n")
    write(tmp_path, "helper.py", "def f(): pass\n")
    report = analyze(tmp_path)
    assert report["dependency_graph"]["edges"] == []
    assert (
        next(f for f in report["files"] if f["path"] == "helper.py")["usage"][
            "reachable"
        ]
        is True
    )
    assert statuses(report)["f"]["status"] == "unused_candidate"
    with pytest.raises(ValueError, match="does not match"):
        analyze(tmp_path, entry_points=["missing.py"])
    assert (
        statuses(analyze(tmp_path, public_api=["helper.py"]))["f"]["reachable"] is True
    )


def test_inherited_contract_and_python_guard(tmp_path):
    write(
        tmp_path,
        "app.py",
        "class Child(Base):\n def overridden(self): pass\ndef start(): pass\nif __name__ == '__main__':\n start()\n",
    )
    usage = statuses(analyze(tmp_path))
    assert usage["start"]["reachable"] is True
    assert usage["overridden"]["status"] == "unknown"


@pytest.mark.parametrize(
    "filename,source,name",
    [
        ("main.rs", "fn main() {} fn dead() {}", "dead"),
        (
            "main.java",
            "class App { public static void main(String[] args) {} private void dead() {} }",
            "dead",
        ),
        (
            "main.scala",
            "object App { def main(args: Array[String]): Unit = {} ; def dead(): Unit = {} }",
            "dead",
        ),
        ("main.js", "function start() {} function dead() {}", "dead"),
        ("main.php", "<?php function start() {} function dead() {}", "dead"),
    ],
)
def test_languages(tmp_path, filename, source, name):
    write(tmp_path, filename, source)
    assert statuses(analyze(tmp_path))[name]["status"] == "unused_candidate"


def test_html_all_kinds_and_cli(tmp_path):
    write(tmp_path, "app.py", "class C:\n def method(self): pass\ndef start(): pass\n")
    report = analyze(tmp_path, entry_points=["app.py#start"])
    graph = graph_data(report)
    assert {n["kind"] for n in graph["usage_items"]} == {
        "file",
        "class",
        "method",
        "function",
    }
    assert 'id="usage-status"' in render_html(report)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tukey",
            str(tmp_path),
            "--entry-point",
            "app.py#start",
            "--public-api",
            "app.py#C",
            "-o",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert statuses(json.loads(result.stdout))["C"]["reachable"] is True
