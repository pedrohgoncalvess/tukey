import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .analyzer import analyze
from .config import resolve_options
from .html_report import render_html


def _log_progress(message: str) -> None:
    print(f"tukey: {message}", file=sys.stderr, flush=True)


class _ProgressPrinter:
    def __init__(self):
        self.stream = sys.stderr
        self.width = 0

    def __call__(self, message: str) -> None:
        if self.stream.isatty() and message.startswith(
            ("Scanning directory:", "Analyzing file ", "Cache hit:")
        ):
            line = f"tukey: {message}"
            columns = max(1, shutil.get_terminal_size().columns - 1)
            if len(line) > columns:
                line = line[: max(0, columns - 3)] + "." * min(3, columns)
            print("\r" + line.ljust(self.width), end="", file=self.stream, flush=True)
            self.width = len(line)
        else:
            self.finish()
            print(f"tukey: {message}", file=self.stream, flush=True)

    def finish(self) -> None:
        if self.width:
            print(file=self.stream, flush=True)
            self.width = 0


def _log_result(label: str, path: Path) -> None:
    absolute = path.resolve()
    uri = absolute.as_uri()
    if sys.stderr.isatty():
        link = f"\033]8;;{uri}\033\\{absolute}\033]8;;\033\\"
        _log_progress(f"{label}: {link}")
    else:
        _log_progress(f"{label}: {absolute}\n  {uri}")


def _file_identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino) if stat.st_ino else None


def _validate_output_paths(outputs: list[Path], inputs: list[Path]) -> None:
    if not outputs:
        return
    input_paths = {path.resolve() for path in inputs}
    input_ids = {
        identity
        for path in input_paths
        if (identity := _file_identity(path)) is not None
    }
    output_paths, output_ids = set(), set()
    for output in outputs:
        resolved = output.resolve()
        identity = _file_identity(resolved)
        if resolved in input_paths or (identity is not None and identity in input_ids):
            raise ValueError(f"Report output would overwrite an input file: {output}")
        if resolved in output_paths or (
            identity is not None and identity in output_ids
        ):
            raise ValueError("HTML and JSON outputs must use different paths")
        output_paths.add(resolved)
        if identity is not None:
            output_ids.add(identity)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze source code into structured JSON."
    )
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        help="Source file or project directory (default: preset path or .)",
    )
    parser.add_argument("--config", type=Path, help="Load a YAML configuration preset")
    parser.add_argument(
        "--cache",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Cache file analysis in project/.tukey (default: enabled; --no-cache disables it)",
    )
    parser.add_argument(
        "--format",
        choices=("json", "html", "both"),
        help="Report formats (default: both; JSON with --no-cache)",
    )
    parser.add_argument(
        "--output-dir", type=Path, help="Report directory; created if missing"
    )
    parser.add_argument(
        "--ignore-dirs",
        action="append",
        help="Ignore directory names at any depth, separated by commas (repeatable)",
    )
    parser.add_argument(
        "--ignore-extensions",
        action="append",
        help="Ignore extensions separated by commas, e.g. .js,.ts (repeatable)",
    )
    parser.add_argument(
        "--no-exclusion",
        nargs="?",
        const="",
        action="append",
        metavar="PATTERN",
        help="Disable all default exclusions without a value, or only matching default names (repeatable; comma-separated)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="JSON output (default: .tukey/report.json; - for stdout)",
    )
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
        "--html",
        type=Path,
        nargs="?",
        const=True,
        metavar="FILE",
        help="HTML output (default: .tukey/report.html with caching)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        help="Exclude a relative path glob (repeatable)",
    )
    parser.add_argument("--version", action="version", version=f"tukey {__version__}")
    parser.add_argument(
        "-q",
        "--quiet",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Suppress progress logs on stderr",
    )
    parser.add_argument(
        "--entry-point",
        action="append",
        default=None,
        metavar="GLOB[#NAME]",
        help="Usage entry point: relative file glob or file#symbol (repeatable; replaces auto detection)",
    )
    parser.add_argument(
        "--public-api",
        action="append",
        default=None,
        metavar="GLOB[#NAME]",
        help="Preserve externally used API files or symbols (repeatable)",
    )
    args = parser.parse_args(argv)
    progress = _ProgressPrinter()
    try:
        config_path = args.config.expanduser() if args.config else None
        args = resolve_options(args)
        source_path = args.path.expanduser().resolve()
        source_root = source_path.parent if source_path.is_file() else source_path
        cache_path = source_root / ".tukey/cache.json" if args.cache else None
        protected = [path for path in (args.coverage, config_path) if path is not None]
        if source_path.is_file():
            protected.append(source_path)
        outputs = [
            output
            for output in (args.html, args.output, cache_path)
            if output is not None
        ]
        _validate_output_paths(outputs, protected)
        report = analyze(
            args.path,
            args.exclude,
            args.coverage,
            args.coverage_root,
            args.entry_point,
            args.public_api,
            progress=None if args.quiet else progress,
            ignore_dirs=args.ignore_dirs,
            ignore_extensions=args.ignore_extensions,
            no_exclusion=args.no_exclusion,
            cache=args.cache,
        )
        root = Path(report["root"])
        inputs = [root / file["path"] for file in report["files"]]
        inputs.extend(
            root / diagnostic["path"]
            for diagnostic in report["diagnostics"]
            if diagnostic["code"] == "read_error"
        )
        if args.coverage:
            inputs.append(args.coverage)
        if config_path:
            inputs.append(config_path)
        _validate_output_paths(
            outputs,
            inputs,
        )
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
        if args.html:
            if not args.quiet:
                _log_progress(f"Writing HTML report: {args.html}")
            args.html.write_text(render_html(report), encoding="utf-8")
        if args.format != "html":
            payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            if args.output:
                if not args.quiet:
                    _log_progress(f"Writing JSON report: {args.output}")
                args.output.write_text(payload, encoding="utf-8")
            else:
                if hasattr(sys.stdout, "reconfigure"):
                    sys.stdout.reconfigure(encoding="utf-8")
                sys.stdout.write(payload)
        if not args.quiet:
            if args.html:
                _log_result("HTML report", args.html)
            if args.output:
                _log_result("JSON report", args.output)
            if cache_path:
                _log_result("Results directory", cache_path.parent)
        return 1 if report["summary"]["error_count"] else 0
    except (OSError, ValueError) as error:
        progress.finish()
        print(f"tukey: {error}", file=sys.stderr)
        return 2
    finally:
        progress.finish()
