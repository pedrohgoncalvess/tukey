import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analyzer import analyze


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze source code into structured JSON."
    )
    parser.add_argument("path", type=Path, help="Source file or project directory")
    parser.add_argument("-o", "--output", type=Path, help="Write JSON to this file")
    parser.add_argument(
        "--coverage",
        type=Path,
        help="Import a Coverage.py JSON or LCOV report (auto-detected)",
    )
    parser.add_argument(
        "--coverage-root",
        type=Path,
        help="Base directory for coverage paths (default: analyzed root)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude a relative path glob (repeatable)",
    )
    parser.add_argument("--version", action="version", version=f"tukey {__version__}")
    parser.add_argument(
        "--entry-point",
        action="append",
        default=[],
        metavar="GLOB[#NAME]",
        help="Usage entry point: relative file glob or file#symbol (repeatable; replaces auto detection)",
    )
    parser.add_argument(
        "--public-api",
        action="append",
        default=[],
        metavar="GLOB[#NAME]",
        help="Preserve externally used API files or symbols (repeatable)",
    )
    args = parser.parse_args(argv)
    try:
        report = analyze(
            args.path,
            args.exclude,
            args.coverage,
            args.coverage_root,
            args.entry_point,
            args.public_api,
        )
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(payload, encoding="utf-8")
        else:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            sys.stdout.write(payload)
        return 1 if report["summary"]["error_count"] else 0
    except (OSError, ValueError) as error:
        print(f"tukey: {error}", file=sys.stderr)
        return 2
