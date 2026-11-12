"""Project discovery, dependency resolution and report aggregation."""

import fnmatch
import os
import posixpath
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .syntax import EXTENSIONS, parse
from .relations import call_graph
from .usage import attach as attach_usage
from .coverage import aggregate as coverage_aggregate, attach as attach_coverage

IGNORED = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "vendor",
    "target",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".next",
    ".idea",
    ".bzr",
    ".tox",
    ".nox",
    ".ruff_cache",
    ".uv-cache",
    ".cache",
    ".gradle",
    ".sbt",
    ".bloop",
    ".metals",
    ".bsp",
    ".scala-build",
    ".turbo",
    ".parcel-cache",
    ".nuxt",
    ".svelte-kit",
    ".angular",
    ".yarn",
    ".pnpm-store",
    ".npm",
    "npm_modules",
    "bower_components",
    "jspm_packages",
    "coverage",
    "htmlcov",
    "site-packages",
    ".eggs",
    "*.egg-info",
    ".vscode",
}

IGNORED_FILES = {
    ".dockerignore",
    ".gitignore",
    ".gitattributes",
    ".gitmodules",
    ".hgignore",
    ".npmignore",
    ".eslintignore",
    ".prettierignore",
    ".ignore",
    ".env",
    ".env.*",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "Dockerfile",
    "Dockerfile.*",
    "docker-compose.*",
    "compose.yaml",
    "compose.yml",
    "*.lock",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "*.pyc",
    "*.pyo",
    "*.class",
    "*.jar",
    "*.war",
    "*.ear",
    "*.o",
    "*.obj",
    "*.so",
    "*.dll",
    "*.exe",
    "*.a",
    "*.lib",
    "*.min.js",
    "*.min.mjs",
    "*.min.cjs",
    "*.map",
}


def csv_items(values: list[str] | str | None) -> list[str]:
    """Split comma-separated values, trimming whitespace and discarding empty items."""
    if isinstance(values, str):
        values = [values]
    return list(
        dict.fromkeys(
            item.strip()
            for value in values or []
            for item in value.split(",")
            if item.strip()
        )
    )


def default_exclusions(
    no_exclusion: list[str] | str | bool | None = None,
) -> tuple[set[str], set[str]]:
    """Remove all built-ins, or only built-in names matching the supplied globs."""
    if (
        no_exclusion is True
        or no_exclusion == ""
        or (isinstance(no_exclusion, list) and "" in no_exclusion)
    ):
        return set(), set()
    selectors = csv_items(no_exclusion) if no_exclusion else []

    def retained(defaults):
        return {
            name
            for name in defaults
            if not any(fnmatch.fnmatchcase(name, selector) for selector in selectors)
        }

    return retained(IGNORED), retained(IGNORED_FILES)


def discover(
    path: Path,
    excludes: list[str],
    progress: Callable[[str], None] | None = None,
    ignore_dirs: list[str] | None = None,
    ignore_extensions: list[str] | None = None,
    no_exclusion: list[str] | str | bool | None = None,
):
    default_dirs, default_files = default_exclusions(no_exclusion)
    ignored_dirs = set(ignore_dirs or [])

    def matches_default(name, patterns):
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)

    def excluded(relative):
        return any(fnmatch.fnmatchcase(relative, pattern) for pattern in excludes)

    def supported(file):
        return file.suffix.lower() in EXTENSIONS and not any(
            file.name.lower().endswith(extension)
            for extension in ignore_extensions or []
        )

    if path.is_file():
        if matches_default(path.name, default_files) or excluded(path.name):
            return [], []
        if path.suffix.lower() not in EXTENSIONS:
            raise ValueError(f"Unsupported source extension: {path.suffix}")
        return ([path] if supported(path) and not excluded(path.name) else []), []
    files, errors = [], []

    def onerror(error):
        if progress:
            progress(f"Cannot scan directory {error.filename}: {error}")
        errors.append(
            {
                "code": "discovery_error",
                "path": str(error.filename),
                "message": str(error),
            }
        )

    for directory, dirs, names in os.walk(path, followlinks=False, onerror=onerror):
        base = Path(directory)
        if progress:
            progress(f"Scanning directory: {base.relative_to(path).as_posix()}")
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in ignored_dirs
            and not matches_default(d, default_dirs)
            and not (base / d).is_symlink()
            and not excluded((base / d).relative_to(path).as_posix())
            and not excluded((base / d).relative_to(path).as_posix() + "/")
        )
        for name in sorted(names):
            file = base / name
            if (
                supported(file)
                and not matches_default(name, default_files)
                and not file.is_symlink()
                and not excluded(file.relative_to(path).as_posix())
            ):
                files.append(file)
    return sorted(files), errors


def path_aliases(file):
    path = file["path"]
    stem = str(Path(path).with_suffix("")).replace("\\", "/")
    aliases = {stem}
    if stem.endswith(("/__init__", "/index", "/mod")):
        aliases.add(stem.rsplit("/", 1)[0])
    for prefix in ("src/", "lib/"):
        if stem.startswith(prefix):
            aliases |= {
                a[len(prefix) :] for a in tuple(aliases) if a.startswith(prefix)
            }
    return aliases


def resolve_import(file, item, files, aliases):
    target, language = item["target"], file["language"]
    keys = []
    relative = False
    if language in {"javascript", "typescript"}:
        relative = target.startswith(".")
        if relative:
            key = posixpath.normpath(
                posixpath.join(posixpath.dirname(file["path"]), target)
            )
            # TypeScript often imports .js names for .ts source files.
            keys = [key, str(Path(key).with_suffix("")).replace("\\", "/")]
    elif language == "python":
        relative = target.startswith(".")
        if relative:
            dots = len(target) - len(target.lstrip("."))
            base = posixpath.dirname(file["path"])
            for _ in range(dots - 1):
                base = posixpath.dirname(base) if base else ".."
            keys = [
                posixpath.normpath(
                    posixpath.join(base, target[dots:].replace(".", "/"))
                )
            ]
            if item["imported_name"]:
                keys.insert(0, posixpath.join(keys[0], item["imported_name"]))
        else:
            keys = [target.replace(".", "/")]
            if item["kind"] == "symbol" and item["imported_name"]:
                keys.insert(0, keys[0] + "/" + item["imported_name"])
    elif language == "rust":
        parts = target.split("::")
        relative = parts[0] in {"crate", "self", "super"}
        if parts[0] == "crate":
            base = "src" if file["path"].startswith("src/") else "."
            parts = parts[1:]
        else:
            base = posixpath.dirname(file["path"])
            if parts[0] == "self":
                parts = parts[1:]
            while parts and parts[0] == "super":
                base = posixpath.dirname(base)
                parts = parts[1:]
        for length in range(len(parts), 0, -1):
            keys.append(posixpath.normpath(posixpath.join(base, *parts[:length])))
    elif language in {"java", "scala", "php"}:
        separator = "\\" if language == "php" else "."
        matches = []
        for candidate in files:
            if candidate["language"] != language:
                continue
            package = candidate.get("package")
            if package:
                names = {
                    package + separator + d["name"]
                    for d in candidate["declarations"]
                    if d["parent_id"] is None
                }
                if target in names or (
                    item["kind"] == "wildcard" and target == package
                ):
                    matches.append(candidate["path"])
        if matches:
            return sorted(set(matches)), "resolved"
        keys = [target.replace(separator, "/")]
    for key in keys:
        matches = sorted(
            p
            for p in aliases.get(key, set())
            if next(f for f in files if f["path"] == p)["language"] == language
        )
        if len(matches) == 1:
            return matches, "resolved"
        if len(matches) > 1:
            return [], "ambiguous"
    return [], "unresolved_local" if relative else "external_or_unresolved"


def total_size(files):
    return {
        key: sum(f["size"][key] for f in files)
        for key in ("bytes", "lines", "nonblank_lines")
    }


def analyze(
    path: Path | str,
    excludes: list[str] | None = None,
    coverage: Path | str | None = None,
    coverage_root: Path | str | None = None,
    entry_points: list[str] | None = None,
    public_api: list[str] | None = None,
    progress: Callable[[str], None] | None = None,
    ignore_dirs: list[str] | str | None = None,
    ignore_extensions: list[str] | str | None = None,
    no_exclusion: list[str] | str | bool | None = None,
) -> dict:
    """Analyze source code; optionally emit progress messages as work proceeds."""
    if coverage_root is not None and coverage is None:
        raise ValueError("--coverage-root requires --coverage")
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Path does not exist: {path}")
    if not path.is_file() and not path.is_dir():
        raise ValueError(f"Expected a file or directory: {path}")
    root = path.parent if path.is_file() else path
    if progress:
        progress(f"Starting analysis: {path}")
    ignore_dirs = csv_items(ignore_dirs)
    ignore_extensions = [
        "." + extension.lower().removeprefix("*").lstrip(".")
        for extension in csv_items(ignore_extensions)
    ]
    discovered, errors = discover(
        path, excludes or [], progress, ignore_dirs, ignore_extensions, no_exclusion
    )
    default_dirs, default_files = default_exclusions(no_exclusion)
    total = len(discovered)
    if progress:
        progress(f"Discovery complete: {total} source files")
    files = []
    for index, file in enumerate(discovered, start=1):
        relative = file.relative_to(root).as_posix()
        if progress:
            progress(
                f"Analyzing file [{index}/{total}] ({index / total:.0%}): {relative}"
            )
        try:
            source = file.read_bytes()
            source.decode("utf-8")
            metrics = parse(
                source, EXTENSIONS[file.suffix.lower()], file.suffix.lower()
            )
            for declaration in metrics["declarations"]:
                if declaration["parent_id"]:
                    declaration["parent_id"] = relative + "#" + declaration["parent_id"]
                declaration["id"] = relative + "#" + declaration["id"]
            for call in metrics["calls"]:
                if call["caller_id"]:
                    call["caller_id"] = relative + "#" + call["caller_id"]
            meta = metrics["_usage"]
            for ref in meta["references"]:
                if ref["source"]:
                    ref["source"] = relative + "#" + ref["source"]
            meta["protected"] = {
                relative + "#" + k: v for k, v in meta["protected"].items()
            }
            meta["entries"] = [
                relative + "#" + identifier for identifier in meta["entries"]
            ]
            files.append(
                {
                    "path": relative,
                    "language": EXTENSIONS[file.suffix.lower()],
                    "module_id": file.relative_to(root).parent.as_posix(),
                    **metrics,
                }
            )
        except (OSError, UnicodeError) as error:
            if progress:
                progress(f"Cannot read file {relative}: {error}")
            errors.append(
                {"code": "read_error", "path": relative, "message": str(error)}
            )
    if progress and coverage is not None:
        progress(f"Importing coverage: {coverage}")
    errors.extend(attach_coverage(files, root, coverage, coverage_root))
    if progress:
        progress("Resolving imports and module dependencies")
    aliases = {}
    for file in files:
        for alias in path_aliases(file):
            aliases.setdefault(alias, set()).add(file["path"])
    by_path = {f["path"]: f for f in files}
    edges = {}
    for file in files:
        for item in file["imports"]:
            matches, resolution = resolve_import(file, item, files, aliases)
            item["resolution"], item["resolved_files"] = resolution, matches
            for destination in matches:
                target_module = by_path[destination]["module_id"]
                if target_module == file["module_id"]:
                    continue
                pair = file["module_id"], target_module
                edge = edges.setdefault(
                    pair,
                    {
                        "source": pair[0],
                        "target": pair[1],
                        "import_count": 0,
                        "file_pairs": set(),
                    },
                )
                edge["import_count"] += 1
                edge["file_pairs"].add((file["path"], destination))
    modules = []
    if progress:
        progress("Aggregating module metrics")
    for module_id in sorted({f["module_id"] for f in files}):
        members = [f for f in files if f["module_id"] == module_id]
        outgoing = sorted({b for a, b in edges if a == module_id})
        incoming = sorted({a for a, b in edges if b == module_id})
        unresolved = sorted(
            {
                i["target"]
                for f in members
                for i in f["imports"]
                if i["resolution"] != "resolved"
            }
        )
        ce, ca = len(outgoing), len(incoming)
        modules.append(
            {
                "id": module_id,
                "files": [f["path"] for f in members],
                "size": total_size(members),
                "test_coverage": coverage_aggregate(members),
                "coupling": {
                    "efferent": ce,
                    "afferent": ca,
                    "instability": ce / (ce + ca) if ce + ca else None,
                    "dependencies": outgoing,
                    "dependents": incoming,
                    "unresolved_dependencies": unresolved,
                },
            }
        )
    edge_list = []
    for _, edge in sorted(edges.items()):
        edge["file_pairs"] = [
            {"source": a, "target": b} for a, b in sorted(edge["file_pairs"])
        ]
        edge_list.append(edge)
    syntax_errors = sum(len(f["diagnostics"]) for f in files)
    kinds = Counter(d["kind"] for f in files for d in f["declarations"])
    if progress:
        progress("Building call graph")
    calls = call_graph(files)
    if progress:
        progress("Analyzing symbol usage")
    usage_analysis, unused_counts = attach_usage(
        files,
        calls,
        entry_points,
        public_api,
        incomplete=bool(errors or syntax_errors),
    )
    if progress:
        progress(
            f"Analysis complete: {len(files)}/{total} files analyzed, "
            f"{len(modules)} modules, {len(errors) + syntax_errors} diagnostics"
        )
    return {
        "schema_version": "1.4.0",
        "tool": {"name": "tukey", "version": __version__},
        "root": str(root),
        "analysis": {
            "usage": usage_analysis,
            "module_definition": "directory (direct files only)",
            "size_units": ["lines", "nonblank_lines", "bytes"],
            "unused_imports": "identifier-based candidates; no scope or compiler resolution",
            "coupling": "distinct directory modules connected by resolved local imports",
            "ignored_directories": sorted(default_dirs | set(ignore_dirs)),
            "excludes": sorted(default_files)
            + (excludes or [])
            + ["*" + ext for ext in ignore_extensions],
        },
        "summary": {
            "unused_candidates": unused_counts,
            "test_coverage": coverage_aggregate(files),
            "discovered_file_count": len(discovered),
            "file_count": len(files),
            "module_count": len(modules),
            "languages": dict(sorted(Counter(f["language"] for f in files).items())),
            "size": total_size(files),
            "declarations": {
                k: kinds[k] for k in ("class", "implementation", "function", "method")
            },
            "unused_import_candidates": sum(
                i["usage"] == "unused_candidate" for f in files for i in f["imports"]
            ),
            "error_count": len(errors) + syntax_errors,
        },
        "modules": modules,
        "files": files,
        "dependency_graph": {"nodes": [m["id"] for m in modules], "edges": edge_list},
        "call_graph": calls,
        "diagnostics": errors,
    }
