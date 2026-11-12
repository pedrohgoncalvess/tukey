import json
import subprocess
import sys
from pathlib import Path

import pytest

from tukey.analyzer import analyze
from tukey.html_report import graph_data, render_html
from tukey.syntax import parse
from .test_analyzer import write


@pytest.mark.parametrize(
    "language,extension,source",
    [
        (
            "python",
            ".py",
            "def helper(): pass\ndef main(x):\n if x and x > 1:\n  helper()\n",
        ),
        ("rust", ".rs", "fn helper() {} fn main(x:bool) { if x && x { helper(); } }"),
        (
            "scala",
            ".scala",
            "def helper() = 1\ndef main(x: Boolean) = { if (x && x) helper() else 0 }",
        ),
        (
            "java",
            ".java",
            "class C { void helper() {} void main(boolean x) { if (x && x) helper(); } }",
        ),
        (
            "typescript",
            ".ts",
            "function helper():void {} function main(x:boolean):void { if(x && x) helper(); }",
        ),
        (
            "javascript",
            ".js",
            "function helper() {} function main(x) { if(x && x) helper(); }",
        ),
        (
            "php",
            ".php",
            "<?php function helper() {} function main($x) { if($x && $x) helper(); }",
        ),
    ],
)
def test_call_graph_and_complexity(tmp_path, language, extension, source):
    write(tmp_path, "main" + extension, source)
    report = analyze(tmp_path)
    main = next(d for d in report["files"][0]["declarations"] if d["name"] == "main")
    helper = next(
        d for d in report["files"][0]["declarations"] if d["name"] == "helper"
    )
    assert main["complexity"]["cyclomatic"] == 3
    edge = report["call_graph"]["edges"][0]
    assert edge["source"] == main["id"]
    assert edge["target"] == helper["id"]


def test_imported_calls_and_graph_sizes(tmp_path):
    write(
        tmp_path,
        "app/main.py",
        "from core.helper import run as go\ndef main():\n go()\n go()\n",
    )
    write(tmp_path, "core/helper.py", "def run():\n pass\n")
    report = analyze(tmp_path)
    edge = report["call_graph"]["edges"][0]
    assert edge["call_count"] == 2
    graph = graph_data(report)
    assert {n["kind"] for n in graph["nodes"]} == {"module", "file", "function"}
    assert {e["kind"] for e in graph["edges"]} == {"contains", "import", "call"}
    main = next(n for n in graph["nodes"] if n["name"] == "main")
    assert main["lines"] == 3
    assert main["fan_out"] == 1


def test_lexical_scope_and_receiver(tmp_path):
    write(
        tmp_path,
        "main.py",
        "def helper(): pass\nclass C:\n def helper(self): pass\n def run(self):\n  helper()\n  self.helper()\n  object.helper()\ndef f(helper):\n helper()\n",
    )
    report = analyze(tmp_path)
    edges = report["call_graph"]["edges"]
    assert len(edges) == 2
    targets = {e["target"] for e in edges}
    assert len(targets) == 2
    assert len(report["call_graph"]["unresolved"]) == 2


def test_files_classes_sizes_and_containment(tmp_path):
    write(
        tmp_path,
        "app.py",
        "from helper import run\nfrom helper import spare\nclass Outer:\n class Inner: pass\n def method(self):\n  run()\n",
    )
    write(tmp_path, "helper.py", "def run(): pass\ndef spare(): pass\n")
    report = analyze(tmp_path)
    graph = graph_data(report)
    nodes = {n["id"]: n for n in graph["nodes"]}
    for file in report["files"]:
        assert nodes["file:" + file["path"]]["lines"] == file["size"]["lines"]
        for declaration in file["declarations"]:
            node = nodes[declaration["id"]]
            assert node["lines"] == declaration["size"]["lines"]
            assert any(
                e["source"] == "file:" + file["path"] and e["target"] == node["id"]
                for e in graph["edges"]
            )
            if node["kind"] == "class":
                assert node["complexity"] is None
                assert node["type_coverage"] is None
    outer = next(n for n in nodes.values() if n["name"] == "Outer")
    assert outer["member_count"] == 2
    assert nodes["file:app.py"]["fan_out"] == 1
    assert nodes["file:helper.py"]["fan_in"] == 1
    imports = [
        e
        for e in graph["edges"]
        if e["source"] == "file:app.py" and e["kind"] == "import"
    ]
    assert len(imports) == 1 and imports[0]["weight"] == 2
    assert all(e["source"] in nodes and e["target"] in nodes for e in graph["edges"])
    html = render_html(report)
    assert '<option value="files">Files</option>' in html
    assert '<option value="classes">Classes</option>' in html


def test_nested_complexity_is_not_duplicated():
    result = parse(
        b"def outer():\n def inner(x):\n  if x: return 1\n return inner\n",
        "python",
        ".py",
    )
    assert [d["complexity"]["cyclomatic"] for d in result["declarations"]] == [1, 2]


def test_html_embedding_is_safe(tmp_path):
    report = analyze(tmp_path)
    report["root"] = '</script><script>alert("unsafe")</script>&\u2028'
    html = render_html(report)
    assert report["root"] not in html
    assert "\\u003c/script\\u003e" in html
    payload = html.split('<script type="application/json" id="report-data">')[1].split(
        "</script>"
    )[0]
    assert json.loads(payload)["root"] == report["root"]
    assert "__TUKEY_DATA__" not in html


def test_html_cli_keeps_json(tmp_path):
    write(tmp_path, "main.py", "def f(): pass")
    html_path = tmp_path / "map with spaces.html"
    json_path = tmp_path / "report.json"
    command = [
        sys.executable,
        "-m",
        "tukey",
        str(tmp_path),
        "--html",
        str(html_path),
        "-o",
        str(json_path),
    ]
    result = subprocess.run(command, capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert '<svg id="graph"' in html_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text())["call_graph"]
    result = subprocess.run(
        [sys.executable, "-m", "tukey", str(tmp_path), "--html"],
        cwd=tmp_path,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0
    assert (tmp_path / "report.html").exists()
    assert json.loads(result.stdout)["schema_version"] == "1.4.0"
    command[-1] = str(html_path)
    result = subprocess.run(command, capture_output=True, encoding="utf-8")
    assert result.returncode == 2
