"""Portable, offline HTML report. All user data is inert JSON or textContent."""

import json
from importlib.resources import files

from .design import tokens_css


def graph_data(report: dict) -> dict:
    nodes = []
    edges = []
    declarations = {d["id"]: d for f in report["files"] for d in f["declarations"]}
    call_edges = report["call_graph"]["edges"]
    for module in report["modules"]:
        members = [
            d
            for f in report["files"]
            if f["module_id"] == module["id"]
            for d in f["declarations"]
            if d["complexity"]
        ]
        nodes.append(
            {
                "id": "module:" + module["id"],
                "name": module["id"],
                "kind": "module",
                "module": module["id"],
                "lines": module["size"]["lines"],
                "complexity": sum(d["complexity"]["cyclomatic"] for d in members),
                "coupling": module["coupling"],
                "file_count": len(module["files"]),
                "callable_count": len(members),
            }
        )
    for file in report["files"]:
        file_id = "file:" + file["path"]
        nodes.append(
            {
                "id": file_id,
                "name": file["path"].rsplit("/", 1)[-1],
                "kind": "file",
                "module": file["module_id"],
                "file": file["path"],
                "lines": file["size"]["lines"],
                "start_line": 1,
                "end_line": file["size"]["lines"],
                "language": file["language"],
                "usage": file.get("usage"),
                "complexity": sum(
                    d["complexity"]["cyclomatic"]
                    for d in file["declarations"]
                    if d["complexity"]
                ),
                "declaration_count": len(file["declarations"]),
            }
        )
        edges.append(
            {
                "source": "module:" + file["module_id"],
                "target": file_id,
                "kind": "contains",
                "weight": 1,
            }
        )
        for item in file["imports"]:
            for target in item["resolved_files"]:
                edges.append(
                    {
                        "source": file_id,
                        "target": "file:" + target,
                        "kind": "import",
                        "weight": 1,
                    }
                )
        for declaration in file["declarations"]:
            if declaration["kind"] not in {"function", "method", "class"}:
                continue
            parent = declarations.get(declaration["parent_id"])
            nodes.append(
                {
                    "id": declaration["id"],
                    "name": declaration["name"],
                    "kind": declaration["kind"],
                    "usage": declaration.get("usage"),
                    "module": file["module_id"],
                    "lines": declaration["size"]["lines"],
                    "complexity": (
                        declaration["complexity"]["cyclomatic"]
                        if declaration["complexity"]
                        else None
                    ),
                    "file": file["path"],
                    "start_line": declaration["start_line"],
                    "end_line": declaration["end_line"],
                    "owner": parent["name"] if parent else None,
                    "language": file["language"],
                    "type_coverage": (
                        declaration["types"]["coverage"]
                        if declaration["types"]
                        else None
                    ),
                    "member_count": sum(
                        d["parent_id"] == declaration["id"]
                        for d in file["declarations"]
                    ),
                    "fan_in": len(
                        {
                            e["source"]
                            for e in call_edges
                            if e["target"] == declaration["id"]
                        }
                    ),
                    "fan_out": len(
                        {
                            e["target"]
                            for e in call_edges
                            if e["source"] == declaration["id"]
                        }
                    ),
                }
            )
            edges.append(
                {
                    "source": file_id,
                    "target": declaration["id"],
                    "kind": "contains",
                    "weight": 1,
                }
            )
            if parent and parent["kind"] == "class":
                edges.append(
                    {
                        "source": parent["id"],
                        "target": declaration["id"],
                        "kind": "contains",
                        "weight": 1,
                    }
                )
            edges.append(
                {
                    "source": "module:" + file["module_id"],
                    "target": declaration["id"],
                    "kind": "contains",
                    "weight": 1,
                }
            )
    edges.extend(
        {
            "source": "module:" + e["source"],
            "target": "module:" + e["target"],
            "kind": "import",
            "weight": e["import_count"],
        }
        for e in report["dependency_graph"]["edges"]
    )
    edges.extend(
        {
            "source": e["source"],
            "target": e["target"],
            "kind": "call",
            "weight": e["call_count"],
            "sites": e["sites"],
        }
        for e in call_edges
    )
    # Collapse repeated imports into a single file pair, preserving their weight.
    combined = {}
    for edge in edges:
        key = edge["source"], edge["target"], edge["kind"]
        if key in combined:
            combined[key]["weight"] += edge["weight"]
        else:
            combined[key] = dict(edge)
    edges = list(combined.values())
    for node in nodes:
        if node["kind"] in {"file", "class"}:
            node["fan_in"] = len(
                {
                    e["source"]
                    for e in edges
                    if e["target"] == node["id"] and e["kind"] != "contains"
                }
            )
            node["fan_out"] = len(
                {
                    e["target"]
                    for e in edges
                    if e["source"] == node["id"] and e["kind"] != "contains"
                }
            )
    return {
        "usage_analysis": report["analysis"].get("usage"),
        "usage_items": [
            {
                "id": "file:" + f["path"],
                "name": f["path"],
                "kind": "file",
                "file": f["path"],
                "line": 1,
                "usage": f.get("usage"),
            }
            for f in report["files"]
        ]
        + [
            {
                "id": d["id"],
                "name": d["name"],
                "kind": d["kind"],
                "file": f["path"],
                "line": d["start_line"],
                "usage": d.get("usage"),
            }
            for f in report["files"]
            for d in f["declarations"]
        ],
        "nodes": nodes,
        "edges": edges,
        "summary": report["summary"],
        "root": report["root"],
        "unresolved_calls": len(report["call_graph"]["unresolved"]),
        "schema_version": report["schema_version"],
    }


def render_html(report: dict) -> str:
    data = json.dumps(graph_data(report), ensure_ascii=False)
    # Prevent script termination and HTML interpretation, including malicious file names.
    for character in "<>&\u2028\u2029":
        data = data.replace(character, f"\\u{ord(character):04x}")
    template = files("tukey").joinpath("report.html").read_text(encoding="utf-8")
    return template.replace("__TUKEY_TOKENS__", tokens_css()).replace(
        "__TUKEY_DATA__", data
    )
