import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from tukey.analyzer import analyze


def coverage_file(root, files):
    path = root / "coverage.json"
    path.write_text(
        json.dumps(
            {"meta": {"version": "7.6", "branch_coverage": False}, "files": files}
        ),
        encoding="utf-8",
    )
    return path


def entry(executed, missing, excluded=()):
    return {
        "executed_lines": executed,
        "missing_lines": missing,
        "excluded_lines": list(excluded),
    }


def validate(report):
    schema = json.loads(
        (Path(__file__).parents[1] / "docs/report.schema.json").read_text()
    )
    jsonschema.validate(report, schema)


def test_methods_nested_and_weighted_aggregate(tmp_path):
    (tmp_path / "a.py").write_text(
        "def outer():\n    def inner():\n        return 1\n    return inner\n\nclass C:\n    def method(self):\n        return 2\n"
    )
    (tmp_path / "b.py").write_text("def unused():\n    return 3\n")
    data = coverage_file(
        tmp_path, {"a.py": entry([1, 2, 4, 6, 7], [3, 8]), "b.py": entry([1], [2])}
    )
    report = analyze(tmp_path, coverage=data)
    validate(report)
    declarations = {
        d["name"]: d["test_coverage"]
        for f in report["files"]
        for d in f["declarations"]
    }
    assert declarations["outer"]["lines"] == {
        "covered": 1,
        "total": 1,
        "coverage": 1,
        "missing": [],
    }
    assert declarations["outer"]["executed"] is True
    assert declarations["inner"]["executed"] is False
    assert declarations["method"]["lines"]["missing"] == [8]
    assert declarations["method"]["executed"] is False
    assert declarations["C"] is None
    assert declarations["unused"]["execution_evidence"] == "body_lines_inferred"
    assert declarations["unused"]["execution_count"] is None
    assert report["summary"]["test_coverage"]["lines"]["coverage"] == pytest.approx(
        6 / 9
    )
    assert report["modules"][0]["test_coverage"] == report["summary"]["test_coverage"]


def test_missing_excluded_and_single_line(tmp_path):
    (tmp_path / "a.py").write_text(
        "def single(): return 1\n\nasync def skip():\n    return 2\n"
    )
    (tmp_path / "b.js").write_text("function f() {}")
    data = coverage_file(tmp_path, {"a.py": entry([1, 3], [], [4])})
    report = analyze(tmp_path, coverage=data)
    validate(report)
    file = report["files"][0]
    assert file["declarations"][0]["test_coverage"]["executed"] is None
    assert file["declarations"][1]["test_coverage"]["lines"]["coverage"] is None
    assert report["files"][1]["test_coverage"]["status"] == "not_measured"
    assert report["summary"]["test_coverage"]["status"] == "partial"
    plain = analyze(tmp_path)
    validate(plain)
    assert plain["summary"]["test_coverage"]["lines"]["coverage"] is None


def test_relative_absolute_windows_and_root_paths(tmp_path):
    source = tmp_path / "src" / "a.py"
    source.parent.mkdir()
    source.write_text("def f():\n    return 1\n")
    for name in [str(source), "src\\a.py", "src/a.py"]:
        data = coverage_file(tmp_path, {name: entry([1, 2], [])})
        report = analyze(source, coverage=data, coverage_root=tmp_path)
        assert report["files"][0]["test_coverage"]["lines"]["coverage"] == 1
    data = coverage_file(tmp_path, {"src/a.py": entry([1, 2], [])})
    report = analyze(source, coverage=data)
    assert report["diagnostics"][0]["code"] == "coverage_unmatched_file"


def test_stale_and_invalid_reports(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    data = coverage_file(tmp_path, {"a.py": entry([2], [])})
    report = analyze(tmp_path, coverage=data)
    assert report["diagnostics"][0]["code"] == "coverage_source_mismatch"
    assert report["files"][0]["test_coverage"]["status"] == "not_measured"
    for item in [{}, entry([True], []), entry([1], [1]), entry([-1], [])]:
        data = coverage_file(tmp_path, {"a.py": item})
        with pytest.raises(ValueError):
            analyze(tmp_path, coverage=data)
    data.write_text("{broken")
    with pytest.raises(ValueError, match="Invalid coverage JSON"):
        analyze(tmp_path, coverage=data)
    with pytest.raises(ValueError, match="requires"):
        analyze(tmp_path, coverage_root=tmp_path)


def test_cli_coverage(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    data = coverage_file(tmp_path, {"a.py": entry([1, 2], [])})
    result = subprocess.run(
        [sys.executable, "-m", "tukey", str(tmp_path), "--coverage", str(data)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    validate(report)
    assert report["files"][0]["declarations"][0]["test_coverage"]["executed"] is True
    data.write_text("{}")
    result = subprocess.run(
        [sys.executable, "-m", "tukey", str(tmp_path), "--coverage", str(data)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""


def test_decorators_multiline_unicode_lambda_and_bom(tmp_path):
    source = "def função(\n    x=1,\n):\n    return x\nf = lambda: 2; g = lambda: 3\n"
    (tmp_path / "a.py").write_bytes(b"\xef\xbb\xbf" + source.encode("utf-8"))
    data = coverage_file(tmp_path, {"a.py": entry([1, 5], [4])})
    report = analyze(tmp_path, coverage=data)
    validate(report)
    declarations = report["files"][0]["declarations"]
    assert declarations[0]["test_coverage"]["executed"] is False
    assert declarations[0]["test_coverage"]["lines"]["missing"] == [4]
    assert len(declarations) == 3
    assert all(d["test_coverage"]["status"] == "measured" for d in declarations)
    assert all(d["test_coverage"]["executed"] is None for d in declarations[1:])


def lcov_file(root, text):
    # Deliberately use a neutral extension: detection must use the content.
    path = root / "coverage.data"
    path.write_text(text, encoding="utf-8-sig")
    return path


def test_lcov_languages_modules_and_weighted_summary(tmp_path):
    sources = {
        "web/a.js": "function f() {\n  return 1;\n}\n",
        "web/b.ts": "function g(): number {\n  return 2;\n}\n",
        "native/lib.rs": "fn g() -> i32 {\n  3\n}\n",
        "native/empty.rs": "// no executable lines\n",
        "web/unmeasured.js": "function h() {}\n",
    }
    for name, source in sources.items():
        destination = tmp_path / name
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(source)
    data = lcov_file(
        tmp_path,
        "TN:unit\nSF:web/a.js\nFN:1,f\nFNDA:2,f\nFNF:1\nFNH:1\n"
        "DA:1,2,checksum\nDA:2,0\nLF:2\nLH:1\nend_of_record\n"
        "SF:web/b.ts\nDA:1,0\nDA:2,0\nend_of_record\n"
        "SF:native/lib.rs\nBRDA:2,0,0,-\nBRF:1\nBRH:0\n"
        "DA:2,4\nend_of_record\n"
        "SF:native/empty.rs\nLF:0\nLH:0\nend_of_record\n",
    )
    report = analyze(tmp_path, coverage=data)
    validate(report)
    assert not report["diagnostics"]
    files = {f["path"]: f for f in report["files"]}
    assert files["web/a.js"]["test_coverage"]["lines"] == {
        "covered": 1,
        "total": 2,
        "coverage": 0.5,
        "missing": [2],
    }
    assert files["web/b.ts"]["test_coverage"]["lines"]["coverage"] == 0
    assert files["native/lib.rs"]["test_coverage"]["lines"]["coverage"] == 1
    assert files["native/empty.rs"]["test_coverage"]["status"] == "measured"
    assert files["native/empty.rs"]["test_coverage"]["lines"]["coverage"] is None
    for file in files.values():
        coverage = file["test_coverage"]
        assert coverage["executed"] is None
        assert coverage["execution_count"] is None
        assert coverage["branches"] is None
        if coverage["status"] == "measured":
            assert coverage["source"] == "lcov"
        for declaration in file["declarations"]:
            coverage = declaration["test_coverage"]
            assert coverage is None or coverage["status"] == "not_measured"
    modules = {m["id"]: m["test_coverage"] for m in report["modules"]}
    assert modules["web"]["status"] == "partial"
    assert modules["web"]["lines"]["coverage"] == 0.25
    assert modules["native"]["status"] == "measured"
    assert modules["native"]["lines"]["coverage"] == 1
    assert report["summary"]["test_coverage"] == {
        "status": "partial",
        "measured_file_count": 4,
        "unmeasured_file_count": 1,
        "lines": {"covered": 2, "total": 5, "coverage": 0.4},
    }


def test_lcov_merges_repeated_records_and_lines(tmp_path):
    (tmp_path / "a.js").write_text("let a = 1;\nlet b = 2;\nlet c = 3;\n")
    data = lcov_file(
        tmp_path,
        "TN:first\nSF:a.js\nDA:1,0\nDA:2,1\nDA:2,0\nend_of_record\n"
        "TN:second\nSF:a.js\nDA:1,5\nDA:2,0\nDA:3,0\nend_of_record\n",
    )
    report = analyze(tmp_path, coverage=data)
    validate(report)
    assert report["files"][0]["test_coverage"]["lines"] == {
        "covered": 2,
        "total": 3,
        "coverage": 2 / 3,
        "missing": [3],
    }


@pytest.mark.parametrize("style", ["relative", "windows", "absolute"])
def test_lcov_paths_and_coverage_root(tmp_path, style):
    source = tmp_path / "src" / "a.ts"
    source.parent.mkdir()
    source.write_text("const a: number = 1;\n")
    name = {"relative": "src/a.ts", "windows": "src\\a.ts", "absolute": str(source)}[
        style
    ]
    data = lcov_file(tmp_path, f"SF:{name}\nDA:1,1\nend_of_record\n")
    report = analyze(source, coverage=data, coverage_root=tmp_path)
    validate(report)
    assert not report["diagnostics"]
    assert report["summary"]["test_coverage"]["lines"]["coverage"] == 1


def test_lcov_unmatched_stale_syntax_errors_and_unsupported_language(tmp_path):
    (tmp_path / "stale.js").write_text("let a = 1;\n")
    (tmp_path / "broken.ts").write_text("function {\n")
    (tmp_path / "a.py").write_text("x = 1\n")
    data = lcov_file(
        tmp_path,
        "SF:stale.js\nDA:2,1\nend_of_record\n"
        "SF:broken.ts\nDA:1,1\nend_of_record\n"
        "SF:a.py\nDA:1,1\nend_of_record\n"
        "SF:absent.rs\nDA:1,0\nend_of_record\n",
    )
    report = analyze(tmp_path, coverage=data)
    validate(report)
    codes = {d["code"] for d in report["diagnostics"]}
    assert "coverage_source_mismatch" in codes
    assert "coverage_unmatched_file" in codes
    assert all(f["test_coverage"]["status"] == "not_measured" for f in report["files"])


@pytest.mark.parametrize(
    "text",
    [
        "",
        "TN:empty\n",
        "garbage",
        "DA:1,1\n",
        "end_of_record\n",
        "SF:\nend_of_record\n",
        "SF:a.js\nDA:1,1\n",
        "SF:a.js\nSF:b.js\nend_of_record\n",
        "SF:a.js\nDA:0,1\nend_of_record\n",
        "SF:a.js\nDA:1,-1\nend_of_record\n",
        "SF:a.js\nDA:1,1.5\nend_of_record\n",
        "SF:a.js\nDA:1\nend_of_record\n",
        "SF:a.js\nDA:1,1,hash,extra\nend_of_record\n",
        "SF:a.js\nUNKNOWN:1\nend_of_record\n",
    ],
)
def test_invalid_lcov(tmp_path, text):
    (tmp_path / "a.js").write_text("let a = 1;\n")
    with pytest.raises(ValueError, match="LCOV"):
        analyze(tmp_path, coverage=lcov_file(tmp_path, text))


def test_lcov_cli_success_partial_and_invalid(tmp_path):
    (tmp_path / "a.rs").write_text("fn main() {}\n")
    data = lcov_file(tmp_path, "SF:a.rs\nDA:1,1\nend_of_record\n")
    command = [sys.executable, "-m", "tukey", str(tmp_path), "--coverage", str(data)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    validate(report)
    assert report["files"][0]["test_coverage"]["source"] == "lcov"
    data.write_text("SF:missing.rs\nDA:1,1\nend_of_record\n")
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1
    assert (
        json.loads(result.stdout)["diagnostics"][0]["code"] == "coverage_unmatched_file"
    )
    data.write_text("SF:a.rs\nDA:1,-1\nend_of_record\n")
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 2
    assert not result.stdout
    assert "LCOV" in result.stderr
