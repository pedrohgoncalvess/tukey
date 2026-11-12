"""Attach normalized coverage without executing the analyzed project."""

import ast
from pathlib import Path

from .coverage_readers import load


def counts(executed, missing):
    total = len(executed) + len(missing)
    return {
        "covered": len(executed),
        "total": total,
        "coverage": len(executed) / total if total else None,
        "missing": sorted(missing),
    }


def empty(status="not_measured"):
    return {
        "status": status,
        "source": None,
        "executed": None,
        "execution_count": None,
        "execution_evidence": None,
        "lines": None,
        "branches": None,
    }


def aggregate(files):
    measured = [f for f in files if f["test_coverage"]["status"] == "measured"]
    covered = sum(f["test_coverage"]["lines"]["covered"] for f in measured)
    total = sum(f["test_coverage"]["lines"]["total"] for f in measured)
    return {
        "status": (
            "not_measured"
            if not measured
            else "measured" if len(measured) == len(files) else "partial"
        ),
        "measured_file_count": len(measured),
        "unmeasured_file_count": len(files) - len(measured),
        "lines": {
            "covered": covered,
            "total": total,
            "coverage": covered / total if total else None,
        },
    }


def attach(files, root, coverage_path=None, coverage_root=None):
    for file in files:
        file["test_coverage"] = empty()
        for declaration in file["declarations"]:
            declaration["test_coverage"] = (
                empty() if declaration["kind"] in {"function", "method"} else None
            )
    if coverage_path is None:
        return []
    data = load(coverage_path)
    base = Path(coverage_root).expanduser().resolve() if coverage_root else root
    by_path = {(root / f["path"]).resolve(): f for f in files}
    diagnostics = []
    matched = set()
    for name, item in data.files.items():
        destination = (base / Path(name.replace("\\", "/"))).resolve()
        file = by_path.get(destination)
        if file is None:
            diagnostics.append(
                {
                    "code": "coverage_unmatched_file",
                    "path": name,
                    "message": "Coverage file is outside the analyzed files; check --coverage-root and exclusions",
                }
            )
            continue
        if destination in matched:
            raise ValueError(f"Duplicate coverage paths resolve to {destination}")
        matched.add(destination)
        if file["language"] not in data.languages or file["diagnostics"]:
            continue
        excluded = set(item.get("excluded_lines", []))
        executed = set(item["executed_lines"]) - excluded
        missing = set(item["missing_lines"]) - excluded
        if any(n > file["size"]["lines"] for n in executed | missing | excluded):
            diagnostics.append(
                {
                    "code": "coverage_source_mismatch",
                    "path": file["path"],
                    "message": "Coverage contains lines beyond the current source; regenerate coverage",
                }
            )
            continue
        file["test_coverage"] = {
            **empty("measured"),
            "source": data.source,
            "lines": counts(executed, missing),
        }
        if data.source != "coverage.py":
            continue
        try:
            raw_source = destination.read_bytes()
            source = raw_source.decode("utf-8-sig")
            tree = ast.parse(source)
        except (OSError, UnicodeError, SyntaxError) as error:
            file["test_coverage"] = empty()
            diagnostics.append(
                {
                    "code": "coverage_source_error",
                    "path": file["path"],
                    "message": str(error),
                }
            )
            continue
        offsets = []
        offset = 3 if raw_source.startswith(b"\xef\xbb\xbf") else 0
        for line in source.encode("utf-8").splitlines(keepends=True):
            offsets.append(offset)
            offset += len(line)
        callable_nodes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
        nodes = {
            offsets[n.lineno - 1] + n.col_offset: n
            for n in ast.walk(tree)
            if isinstance(n, callable_nodes)
        }
        for declaration in file["declarations"]:
            if declaration["kind"] not in {"function", "method"}:
                continue
            node = nodes.get(int(declaration["id"].rsplit(":", 2)[-2]))
            if node is None:
                continue
            body_start = (
                node.body.lineno
                if isinstance(node, ast.Lambda)
                else node.body[0].lineno
            )
            own = set(range(body_start, node.end_lineno + 1))
            # Nested bodies belong to their own declarations. Class bodies execute
            # separately and must not be attributed to the surrounding callable.
            for child in ast.walk(node):
                if child is not node and isinstance(
                    child, (*callable_nodes, ast.ClassDef)
                ):
                    start = min(
                        [child.lineno]
                        + [d.lineno for d in getattr(child, "decorator_list", [])]
                    )
                    own.difference_update(range(start, child.end_lineno + 1))
            hits, misses = executed & own, missing & own
            # A single-line def is executed on definition as well as on invocation.
            evidence_lines = own - {node.lineno}
            evidence = (executed | missing) & evidence_lines
            declaration["test_coverage"] = {
                **empty("measured"),
                "source": "coverage.py",
                "executed": bool(executed & evidence_lines) if evidence else None,
                "execution_evidence": "body_lines_inferred" if evidence else None,
                "lines": counts(hits, misses),
            }
    return diagnostics
