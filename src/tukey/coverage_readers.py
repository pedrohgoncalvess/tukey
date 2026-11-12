"""Readers normalize external reports to executable-line sets."""

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CoverageReport:
    source: str
    languages: frozenset[str]
    files: dict[str, dict]


def load_coverage_py(text):
    try:
        data = json.loads(text)
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"Invalid coverage JSON: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("meta"), dict):
        raise ValueError("Expected a Coverage.py JSON report with meta and files")
    if not isinstance(data.get("files"), dict):
        raise ValueError("Coverage.py files must be an object")
    for name, item in data["files"].items():
        if not isinstance(item, dict):
            raise ValueError(f"Invalid coverage entry: {name}")
        for key in ("executed_lines", "missing_lines", "excluded_lines"):
            values = item.get(key, [] if key == "excluded_lines" else None)
            if not isinstance(values, list) or any(
                type(n) is not int or n < 1 for n in values
            ):
                raise ValueError(f"Invalid {key} for {name}")
        if set(item["executed_lines"]) & set(item["missing_lines"]):
            raise ValueError(f"Overlapping executed and missing lines: {name}")
    return data


def load_lcov(text):
    files = {}
    current = None
    saw_record = False
    # Other LCOV records describe functions, branches or summary counters.
    ignored = {
        "TN",
        "VER",
        "FN",
        "FNDA",
        "FNF",
        "FNH",
        "FNL",
        "FNA",
        "BRDA",
        "BRF",
        "BRH",
        "LF",
        "LH",
    }
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line == "end_of_record":
            if current is None:
                raise ValueError(f"LCOV record without SF at line {number}")
            current = None
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"Invalid LCOV record at line {number}")
        if key == "SF":
            if current is not None or not value.strip():
                raise ValueError(f"Invalid LCOV SF at line {number}")
            current = files.setdefault(value, {})
            saw_record = True
        elif key == "DA":
            if current is None:
                raise ValueError(f"LCOV DA without SF at line {number}")
            parts = value.split(",")
            if (
                len(parts) not in {2, 3}
                or not re.fullmatch(r"[0-9]+", parts[0])
                or not re.fullmatch(r"[0-9]+", parts[1])
                or int(parts[0]) < 1
            ):
                raise ValueError(f"Invalid LCOV DA at line {number}")
            row, hits = int(parts[0]), int(parts[1])
            current[row] = current.get(row, 0) + hits
        elif key not in ignored:
            raise ValueError(f"Unsupported LCOV record {key!r} at line {number}")
        elif key != "TN" and current is None:
            raise ValueError(f"LCOV {key} without SF at line {number}")
    if current is not None:
        raise ValueError("Unterminated LCOV record: expected end_of_record")
    if not saw_record:
        raise ValueError("Expected a Coverage.py JSON or LCOV report with SF records")
    return CoverageReport(
        "lcov",
        frozenset({"javascript", "typescript", "rust"}),
        {
            name: {
                "executed_lines": {row for row, hits in lines.items() if hits > 0},
                "missing_lines": {row for row, hits in lines.items() if hits == 0},
            }
            for name, lines in files.items()
        },
    )


def load(path):
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeError as error:
        raise ValueError(f"Invalid coverage encoding: {error}") from error
    if text.lstrip().startswith(("{", "[")):
        data = load_coverage_py(text)
        return CoverageReport("coverage.py", frozenset({"python"}), data["files"])
    return load_lcov(text)
