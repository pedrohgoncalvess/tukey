import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from tukey.analyzer import analyze
from tukey.syntax import parse

SAMPLES = {
    "python": (
        ".py",
        "import os as unused\nclass C:\n def f(self, x: int) -> str:\n  return str(x)\ndef g(x):\n return x\n",
    ),
    "rust": (
        ".rs",
        "use std::collections::HashMap;\nstruct C { x: i32 }\nimpl C { fn f(&self, x:i32)->i32 { x } }\nfn g(x:i32) {}",
    ),
    "scala": (
        ".scala",
        "import java.util.HashMap\nclass C { def f(x: Int): String = x.toString }\ndef g(x: Int) = x",
    ),
    "java": (
        ".java",
        'import java.util.HashMap; class C { String f(int x) { return "x"; } C() {} }',
    ),
    "typescript": (
        ".ts",
        "import {Foo as Unused} from './foo'; class C { f(x: number): string { return 'x'; } } const g = (x: number): number => x;",
    ),
    "javascript": (
        ".js",
        "import Unused from './foo'; class C { f(x) { return x; } } const g = x => x;",
    ),
    "php": (
        ".php",
        "<?php use App\\Foo as Unused; class C { function f(int $x): string { return 'x'; } } function g($x) {return $x;}",
    ),
}


@pytest.mark.parametrize("language", SAMPLES)
def test_languages(language):
    extension, source = SAMPLES[language]
    result = parse(source.encode(), language, extension)
    assert not result["diagnostics"]
    assert any(
        d["kind"] == "class" and d["name"] == "C" for d in result["declarations"]
    )
    method = next(d for d in result["declarations"] if d["name"] == "f")
    assert method["kind"] == "method"
    assert method["size"]["lines"] > 0
    assert method["parent_id"]
    assert result["imports"][0]["usage"] == "unused_candidate"
    assert method["types"]["coverage"] == (None if language == "javascript" else 1)
    if language not in {"java"}:
        assert any(
            d["name"] == "g" and d["kind"] == "function" for d in result["declarations"]
        )


def write(root, path, source):
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source, encoding="utf-8", newline="")


def test_python_coupling_and_aliases(tmp_path):
    write(
        tmp_path,
        "app/main.py",
        "from ..core.model import Model as M\nimport os as system\nx: M = M()\n# system\ntext = 'system'\n",
    )
    write(tmp_path, "core/model.py", "class Model:\n pass\n")
    report = analyze(tmp_path)
    file = next(f for f in report["files"] if f["path"] == "app/main.py")
    assert file["imports"][0]["resolved_files"] == ["core/model.py"]
    assert file["imports"][0]["usage"] == "referenced"
    assert file["imports"][1]["usage"] == "unused_candidate"
    assert report["dependency_graph"]["edges"][0]["source"] == "app"
    assert report["dependency_graph"]["edges"][0]["target"] == "core"
    assert report["modules"][0]["coupling"]["instability"] == 1
    assert report["modules"][1]["coupling"]["afferent"] == 1


@pytest.mark.parametrize(
    "extension,main,dependency",
    [
        (
            ".ts",
            "import {f} from '../core/model.js'; f();",
            "export function f(): void {}",
        ),
        (
            ".js",
            "const f = require('../core/model'); f();",
            "module.exports = () => 1;",
        ),
        (
            ".rs",
            "use crate::core::model::{Model, f as run}; fn main() { run(); }",
            "pub struct Model {} pub fn f() {}",
        ),
        (
            ".java",
            "package app; import core.Model; class Main { Model m; }",
            "package core; class Model {}",
        ),
        (
            ".scala",
            "package app\nimport core.Model\nclass Main { val m: Model = new Model }",
            "package core\nclass Model {}",
        ),
        (
            ".php",
            "<?php namespace App; use Core\\Model as M; $x = new M();",
            "<?php namespace Core; class Model {}",
        ),
    ],
)
def test_local_resolution(tmp_path, extension, main, dependency):
    prefix = "src/" if extension == ".rs" else ""
    write(tmp_path, prefix + "app/main" + extension, main)
    write(tmp_path, prefix + "core/model" + extension, dependency)
    report = analyze(tmp_path)
    assert report["summary"]["error_count"] == 0
    file = next(f for f in report["files"] if "/app/" in "/" + f["path"])
    assert file["imports"][0]["resolution"] == "resolved"
    assert len(report["dependency_graph"]["edges"]) == 1


def test_discovery_excludes_empty_and_utf8(tmp_path):
    write(tmp_path, "node_modules/bad.js", "(")
    write(tmp_path, "ignored/bad.py", "(")
    write(tmp_path, "empty.py", "")
    write(tmp_path, "valid.py", "# café\n\nx = 1\n")
    report = analyze(tmp_path, ["ignored/*"])
    assert report["summary"]["file_count"] == 2
    assert report["summary"]["size"] == {"lines": 3, "nonblank_lines": 2, "bytes": 15}
    assert analyze(tmp_path / "empty.py")["files"][0]["size"]["lines"] == 0


def test_errors_and_nested_functions(tmp_path):
    write(tmp_path, "broken.py", "import os\ndef f(:\n pass\n")
    (tmp_path / "binary.py").write_bytes(b"\xff")
    report = analyze(tmp_path)
    assert report["summary"]["error_count"] >= 2
    assert report["files"][0]["imports"][0]["usage"] == "unknown"
    source = b"class C:\n def f(self):\n  def nested():\n   pass\n  return nested\n"
    declarations = parse(source, "python", ".py")["declarations"]
    assert declarations[-1]["kind"] == "function"
    assert declarations[-1]["parent_id"] == declarations[1]["id"]


def test_wildcard_and_side_effect_not_unused():
    for language, extension, source in [
        ("python", ".py", "from foo import *"),
        ("javascript", ".js", "import './init';"),
        ("java", ".java", "import java.util.*; class C {}"),
    ]:
        result = parse(source.encode(), language, extension)
        assert result["imports"][0]["usage"] == "unknown"


def test_cli_and_schema(tmp_path):
    for lang, (extension, source) in SAMPLES.items():
        write(tmp_path, lang + "/sample" + extension, source)
    result = subprocess.run(
        [sys.executable, "-m", "tukey", str(tmp_path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    schema = json.loads(
        (Path(__file__).parents[1] / "docs/report.schema.json").read_text()
    )
    jsonschema.validate(report, schema)
    output = tmp_path / "output with spaces.json"
    result = subprocess.run(
        [sys.executable, "-m", "tukey", str(tmp_path), "-o", str(output)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert json.loads(output.read_text())["schema_version"] == "1.4.0"
    result = subprocess.run(
        [sys.executable, "-m", "tukey", str(tmp_path / "missing")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert not result.stdout


def test_ambiguous_resolution(tmp_path):
    write(tmp_path, "main.py", "import foo")
    write(tmp_path, "foo.py", "")
    write(tmp_path, "src/foo.py", "")
    report = analyze(tmp_path)
    main = next(f for f in report["files"] if f["path"] == "main.py")
    assert main["imports"][0]["resolution"] == "ambiguous"
    assert not report["dependency_graph"]["edges"]


def test_abstract_classes_and_closures():
    source = b"abstract class C { abstract f(x:number):void; } interface I { f(x:number):void; }"
    result = parse(source, "typescript", ".ts")
    assert [d["kind"] for d in result["declarations"]] == [
        "class",
        "method",
        "class",
        "method",
    ]
    result = parse(b"fn f(){ let g = |x: i32| x; }", "rust", ".rs")
    closure = result["declarations"][1]
    assert closure["name"] == "g"
    assert closure["types"]["implicit_return"] is None
    assert closure["types"]["coverage"] == 0.5


def test_alias_to_python_submodule(tmp_path):
    write(tmp_path, "app/main.py", "from . import helper as h\nh.f()")
    write(tmp_path, "app/helper.py", "def f(): pass")
    file = next(f for f in analyze(tmp_path)["files"] if f["path"] == "app/main.py")
    assert file["imports"][0]["resolved_files"] == ["app/helper.py"]
    assert file["imports"][0]["usage"] == "referenced"


def test_reexport_and_commonjs_destructuring(tmp_path):
    write(
        tmp_path,
        "app/index.js",
        "export {f} from '../core/model'; const {g} = require('../core/model');",
    )
    write(tmp_path, "core/model.js", "export function f() {} export function g() {}")
    report = analyze(tmp_path)
    assert all(i["usage"] == "unknown" for i in report["files"][0]["imports"])
    assert report["dependency_graph"]["edges"][0]["import_count"] == 2


def test_cli_partial_report_and_unicode(tmp_path):
    write(tmp_path, "valid.py", "def função(): pass")
    write(tmp_path, "invalid.py", "def f(: pass")
    result = subprocess.run(
        [sys.executable, "-m", "tukey", str(tmp_path)],
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert "função" in result.stdout
    assert report["summary"]["error_count"] > 0
    schema = json.loads(
        (Path(__file__).parents[1] / "docs/report.schema.json").read_text()
    )
    jsonschema.validate(report, schema)
