"""Shared design tokens and a CSS export for any Tukey interface."""

import json
from importlib.resources import files


def tokens_css() -> str:
    tokens = json.loads(
        files("tukey").joinpath("design.tokens.json").read_text(encoding="utf-8")
    )
    properties = []
    for group, entries in tokens.items():
        if group.startswith("$"):
            continue
        for name, token in entries.items():
            value = token["$value"]
            if isinstance(value, dict):
                value = f"{value['value']}{value['unit']}"
            elif isinstance(value, list):
                value = ", ".join(value)
            properties.append(f"  --tukey-{group}-{name}: {value};")
    return ":root {\n" + "\n".join(properties) + "\n}\n"


if __name__ == "__main__":
    print(tokens_css(), end="")
