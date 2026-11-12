"""Versioned, atomic cache of raw per-file parser results."""

import hashlib
import json
import tempfile
from importlib.metadata import version
from pathlib import Path

from . import __version__

CACHE_VERSION = 1


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encode(metrics: dict) -> str:
    return json.dumps(
        metrics,
        ensure_ascii=False,
        sort_keys=True,
        default=lambda value: sorted(value) if isinstance(value, set) else value,
    )


class ParseCache:
    def __init__(self, root: Path):
        self.directory = root / ".tukey"
        if self.directory.is_symlink():
            raise ValueError(f"Cache directory must not be a symlink: {self.directory}")
        self.path = self.directory / "cache.json"
        implementation = b"".join(
            Path(__file__).with_name(name).read_bytes()
            for name in ("syntax.py", "usage.py")
        )
        self.header = {
            "cache_version": CACHE_VERSION,
            "tool_version": __version__,
            "parser_signature": digest(
                implementation
                + (
                    version("tree-sitter-language-pack") + ":" + version("tree-sitter")
                ).encode()
            ),
            "root": str(root),
            "hash_algorithm": "sha256",
        }
        self.files = {}
        self.dirty = True
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                isinstance(data, dict)
                and all(data.get(key) == value for key, value in self.header.items())
                and isinstance(data.get("files"), dict)
            ):
                self.files = data["files"]
                self.dirty = False
        except (OSError, ValueError):
            pass

    def get(self, relative: str, source_hash: str) -> dict | None:
        entry = self.files.get(relative)
        if not isinstance(entry, dict) or entry.get("hash") != source_hash:
            return None
        try:
            encoded = _encode(entry["metrics"])
            if digest(encoded.encode("utf-8")) != entry.get("metrics_hash"):
                return None
            metrics = json.loads(encoded)
            if not all(
                isinstance(metrics[key], list)
                for key in ("declarations", "imports", "calls", "diagnostics")
            ):
                return None
            metrics["_usage"]["strings"] = set(metrics["_usage"]["strings"])
            return metrics
        except (KeyError, TypeError, ValueError):
            return None

    def put(self, relative: str, source_hash: str, metrics: dict) -> None:
        # Freeze before path IDs, coverage, and project-wide analysis mutate metrics.
        encoded = _encode(metrics)
        self.files[relative] = {
            "hash": source_hash,
            "metrics_hash": digest(encoded.encode("utf-8")),
            "metrics": json.loads(encoded),
        }
        self.dirty = True

    def save(self) -> None:
        if not self.dirty:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(
                    {**self.header, "files": self.files}, stream, ensure_ascii=False
                )
                stream.write("\n")
            temporary.replace(self.path)
            self.dirty = False
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
