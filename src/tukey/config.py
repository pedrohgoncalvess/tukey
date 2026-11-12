"""Load validated YAML presets and merge explicit CLI overrides."""

from argparse import Namespace
from pathlib import Path

import yaml


PATH_KEYS = {"path", "output", "output_dir", "coverage", "coverage_root"}
LIST_KEYS = {"exclude", "ignore_dirs", "ignore_extensions", "entry_point", "public_api"}
KEYS = PATH_KEYS | LIST_KEYS | {"html", "format", "quiet", "no_exclusion"}


def load_config(path: Path) -> dict:
    path = path.expanduser()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML config {path}: {error}") from error
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Config must be a YAML mapping of option names to values")
    for key, value in data.items():
        if not isinstance(key, str) or key not in KEYS:
            raise ValueError(f"Unknown config option: {key}")
        if key in PATH_KEYS:
            valid = value is None or isinstance(value, str) and bool(value.strip())
        elif key in LIST_KEYS:
            valid = isinstance(value, list) and all(
                isinstance(item, str) and item.strip() for item in value
            )
            if key in {"ignore_dirs", "ignore_extensions"} and isinstance(value, str):
                valid = True
                data[key] = [value]
        elif key == "html":
            valid = (
                isinstance(value, bool)
                or isinstance(value, str)
                and bool(value.strip())
            )
        elif key == "quiet":
            valid = isinstance(value, bool)
        elif key == "no_exclusion":
            valid = isinstance(value, (bool, str)) or (
                isinstance(value, list)
                and all(isinstance(item, str) and item.strip() for item in value)
            )
        else:
            valid = isinstance(value, str) and value in {"json", "html", "both"}
        if not valid:
            raise ValueError(f"Invalid value for config option '{key}'")
    return data


def resolve_options(cli: Namespace) -> Namespace:
    """CLI values replace preset values, including lists; preset paths use its directory."""
    preset = load_config(cli.config) if cli.config else {}
    base = cli.config.expanduser().resolve().parent if cli.config else Path.cwd()
    values = {
        "path": None,
        "output": None,
        "output_dir": None,
        "html": None,
        "format": None,
        "coverage": None,
        "coverage_root": None,
        "exclude": [],
        "ignore_dirs": [],
        "ignore_extensions": [],
        "entry_point": [],
        "public_api": [],
        "quiet": False,
        "no_exclusion": False,
        **preset,
    }
    explicit = {key: value for key, value in vars(cli).items() if value is not None}
    values.update(explicit)
    if "format" not in explicit:
        if (explicit.get("html") and values["format"] == "json") or (
            explicit.get("output") and values["format"] == "html"
        ):
            values["format"] = "both"
    if explicit.get("format") == "json" and "html" not in explicit:
        values["html"] = None
    if explicit.get("format") == "html" and "output" not in explicit:
        values["output"] = None
    for key in PATH_KEYS - {"output"}:
        if values[key] is not None:
            path = Path(values[key]).expanduser()
            values[key] = base / path if key not in explicit else path
    values["path"] = values["path"] or (base if cli.config else Path("."))
    output_base = values["output_dir"]
    if values["html"] is True:
        values["html"] = "report.html"
    elif values["html"] is False:
        values["html"] = None
    if values["format"] is None:
        values["format"] = "both" if values["html"] else "json"
    if values["format"] in {"html", "both"}:
        values["html"] = values["html"] or "report.html"
    elif values["html"]:
        raise ValueError(
            "--format json conflicts with an HTML output; use --format both"
        )
    if values["format"] == "html" and values["output"]:
        raise ValueError(
            "--format html conflicts with a JSON output; use --format both"
        )
    if output_base is not None and values["format"] != "html":
        values["output"] = values["output"] or "report.json"
    for key in ("output", "html"):
        if values[key] is not None:
            path = Path(values[key]).expanduser()
            if not path.is_absolute():
                path = (output_base or (Path.cwd() if key in explicit else base)) / path
            values[key] = path
    return Namespace(**values)
