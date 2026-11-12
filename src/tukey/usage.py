"""Conservative reference and reachability analysis; never executes source code."""

import fnmatch
from collections import Counter, defaultdict
from pathlib import PurePosixPath


def syntax_usage(nodes, declarations, import_ranges, language):
    """Collect identifiers while the syntax tree and byte ranges are available."""
    refs, protected, entries = [], {}, []
    strings = set()
    declaration_nodes = {d["_start"]: d for d in declarations}
    declaration_types = {n.type for n in nodes if n.start_byte in declaration_nodes}
    for node in nodes:
        if node.type in {
            "string",
            "string_literal",
            "interpreted_string_literal",
            "string_content",
        }:
            strings.add(node.text.decode("utf-8").strip("\"'"))
        declaration = declaration_nodes.get(node.start_byte)
        if declaration and node.end_byte == declaration["_end"]:
            ancestors, parent = [], node.parent
            inherited_contract = False
            while parent:
                ancestors.append(parent.type)
                inherited_contract |= any(
                    parent.child_by_field_name(name) is not None
                    for name in ("superclasses", "superclass", "interfaces", "trait")
                ) or any(
                    child.type
                    in {
                        "class_heritage",
                        "extends_clause",
                        "extends_type_clause",
                        "superclass",
                        "super_interfaces",
                    }
                    for child in parent.named_children
                )
                parent = parent.parent
            header = node.text.decode("utf-8").split("{", 1)[0].split("\n", 1)[0]
            if (
                "export_statement" in ancestors
                or "pub " in header
                or "pub(" in header
                or "public " in header
            ):
                protected[declaration["id"]] = "public_api"
            if (
                "decorated_definition" in ancestors
                or any(word in header for word in ("override", "@", "abstract "))
                or declaration["name"].startswith("__")
                or (declaration["kind"] == "method" and inherited_contract)
                or any("interface" in a or "trait" in a for a in ancestors)
                or node.type
                in {
                    "method_signature",
                    "abstract_method_signature",
                    "function_signature",
                }
            ):
                protected[declaration["id"]] = "framework_or_protocol"
            if declaration["name"] == "main" and language in {"rust", "java", "scala"}:
                entries.append(declaration["id"])
        if (
            node.type
            not in {
                "identifier",
                "type_identifier",
                "property_identifier",
                "field_identifier",
                "name",
                "simple_identifier",
                "variable_name",
            }
            or node.named_children
        ):
            continue
        if any(a <= node.start_byte < b for a, b in import_ranges):
            continue
        parent = node.parent
        if parent is None:
            continue
        name_node = parent.child_by_field_name("name")
        if (
            name_node is not None
            and name_node.id == node.id
            and (
                parent.type in declaration_types
                or "parameter" in parent.type
                or parent.type in {"variable_declarator", "let_declaration"}
            )
        ):
            continue
        if parent.type in {"parameters", "formal_parameters", "lambda_parameters"}:
            continue
        containers = [
            d for d in declarations if d["_start"] <= node.start_byte < d["_end"]
        ]
        owner = min(containers, key=lambda d: d["_end"] - d["_start"], default=None)
        receiver = parent.child_by_field_name("object") or parent.child_by_field_name(
            "value"
        )
        refs.append(
            {
                "name": node.text.decode("utf-8").lstrip("$"),
                "receiver": (
                    receiver.text.decode("utf-8")
                    if receiver is not None and receiver.id != node.id
                    else None
                ),
                "source": owner["id"] if owner else None,
                "line": node.start_point.row + 1,
            }
        )
    return {
        "references": refs,
        "protected": protected,
        "entries": entries,
        "strings": strings,
        "python_main": (
            any(
                n.type == "if_statement"
                and b"__name__" in n.text.split(b":", 1)[0]
                and b"__main__" in n.text.split(b":", 1)[0]
                for n in nodes
            )
            if language == "python"
            else False
        ),
    }


def attach(files, calls, entry_points=None, public_api=None, incomplete=False):
    entry_points, public_api = entry_points or [], public_api or []
    graph, evidence, uncertain = defaultdict(set), defaultdict(list), defaultdict(set)
    declarations = {d["id"]: d for f in files for d in f["declarations"]}
    by_path = {f["path"]: f for f in files}
    roots, root_reasons = set(), {}
    metadata = {f["path"]: f.pop("_usage") for f in files}
    names = defaultdict(list)
    for d in declarations.values():
        names[d["name"].lstrip("$")].append(d["id"])
    if any(
        i["resolution"] in {"ambiguous", "unresolved_local"}
        for f in files
        for i in f["imports"]
    ):
        incomplete = True

    def link(source, target, reason, path, line):
        graph[source].add(target)
        evidence[target].append(
            {"source": source, "file": path, "line": line, "kind": reason}
        )

    def root(identifier, reason):
        roots.add(identifier)
        root_reasons[identifier] = reason

    def match(pattern, file):
        path_pattern, separator, symbol = pattern.partition("#")
        if not fnmatch.fnmatchcase(file["path"], path_pattern):
            return []
        return (
            [
                d["id"]
                for d in file["declarations"]
                if fnmatch.fnmatchcase(d["name"], symbol)
            ]
            if separator
            else ["file:" + file["path"]]
        )

    for pattern in entry_points + public_api:
        if not any(match(pattern, f) for f in files):
            raise ValueError(
                f"Usage entry point does not match analyzed code: {pattern}"
            )
    for f in files:
        path, meta = f["path"], metadata[f["path"]]
        fid = "file:" + path
        test = (
            PurePosixPath(path).name.startswith("test_")
            or "tests" in PurePosixPath(path).parts
        )
        if not entry_points and (
            meta["python_main"]
            or PurePosixPath(path).stem in {"main", "__main__"}
            or test
        ):
            root(fid, "conventional_entry_point")
        if not entry_points:
            for identifier in meta["entries"]:
                root(identifier, "conventional_entry_point")
            if test:
                for d in f["declarations"]:
                    if d["name"].startswith("test"):
                        root(d["id"], "test_entry_point")
        for pattern in entry_points:
            for identifier in match(pattern, f):
                root(identifier, "configured_entry_point")
        for pattern in public_api:
            for identifier in match(pattern, f):
                root(identifier, "configured_public_api")
                if identifier == fid:
                    for d in f["declarations"]:
                        root(d["id"], "configured_public_api")
        for d in f["declarations"]:
            # Calling a declaration loads its file, but loading a file does not call every function.
            graph[d["id"]].add(fid)
            if d["parent_id"]:
                graph[d["id"]].add(d["parent_id"])
            if f["diagnostics"] or incomplete:
                uncertain[d["id"]].add("incomplete_analysis")
        if f["diagnostics"] or incomplete:
            uncertain[fid].add("incomplete_analysis")
        for identifier, reason in meta["protected"].items():
            uncertain[identifier].add(reason)
        for name in meta["strings"]:
            for identifier in names[name]:
                uncertain[identifier].add("dynamic_reference")
        for item in f["imports"]:
            for target in item["resolved_files"]:
                link(fid, "file:" + target, "import", path, item["start_line"])
                if item["kind"] in {"reexport", "wildcard"}:
                    for d in by_path[target]["declarations"]:
                        uncertain[d["id"]].add("wildcard_or_reexport")
        local = defaultdict(list)
        for d in f["declarations"]:
            local[d["name"].lstrip("$")].append(d["id"])
        for ref in meta["references"]:
            candidates = local.get(ref["name"], [])[:]
            for item in f["imports"]:
                if item["binding"] == ref["name"]:
                    for target in item["resolved_files"]:
                        candidates.extend(
                            d["id"]
                            for d in by_path[target]["declarations"]
                            if d["name"] == item["imported_name"]
                        )
                if ref["receiver"] == item["binding"]:
                    for target in item["resolved_files"]:
                        candidates.extend(
                            d["id"]
                            for d in by_path[target]["declarations"]
                            if d["name"] == ref["name"]
                        )
            if ref["receiver"] and not candidates:
                candidates = names[ref["name"]][:]
                for target in candidates:
                    uncertain[target].add("ambiguous_reference")
            candidates = set(candidates)
            # Identifier matching cannot establish lexical scope or receiver types.
            # Keep possible references as conservative edges, flag ambiguity explicitly.
            for target in candidates:
                link(
                    ref["source"] or fid,
                    target,
                    "identifier_reference",
                    path,
                    ref["line"],
                )
                if len(candidates) > 1:
                    uncertain[target].add("ambiguous_reference")
    for edge in calls["edges"]:
        for site in edge["sites"]:
            source = edge["source"]
            if source.startswith("module:"):
                source = "file:" + site["file"]
            link(source, edge["target"], "call", site["file"], site["line"])
    for call in calls["unresolved"]:
        for d in declarations.values():
            if d["name"].lstrip("$") == call["name"].lstrip("$"):
                uncertain[d["id"]].add("unresolved_call")

    # Code that might be entered externally can in turn use otherwise unreachable helpers.
    uncertain_pending = [
        identifier for identifier in uncertain if uncertain[identifier]
    ]
    visited = set(uncertain_pending)
    while uncertain_pending:
        identifier = uncertain_pending.pop()
        for target in graph[identifier]:
            if target not in visited:
                visited.add(target)
                uncertain[target].add("possible_external_use")
                uncertain_pending.append(target)

    reached, pending = set(), list(roots)
    while pending:
        identifier = pending.pop()
        if identifier not in reached:
            reached.add(identifier)
            pending.extend(graph[identifier] - reached)

    def usage(identifier):
        reachable = identifier in reached if roots else None
        reasons = sorted(uncertain[identifier])
        if identifier in roots:
            status, reasons = "referenced", [root_reasons[identifier]]
        elif reachable:
            status, reasons = "referenced", ["reachable_from_entry_point"]
        elif reasons:
            status = "unknown"
        elif reachable is False:
            status, reasons = "unused_candidate", ["unreachable_from_entry_points"]
        elif evidence[identifier]:
            status, reasons = "referenced", ["reference_found_without_entry_points"]
        else:
            status, reasons = "unused_candidate", ["no_reference_found"]
        return {
            "status": status,
            "reachable": reachable,
            "reasons": reasons,
            "evidence": sorted(
                evidence[identifier],
                key=lambda e: (e["file"], e["line"], e["source"], e["kind"]),
            ),
        }

    counts = Counter()
    for f in files:
        f["usage"] = usage("file:" + f["path"])
        counts["files"] += f["usage"]["status"] == "unused_candidate"
        for d in f["declarations"]:
            d["usage"] = usage(d["id"])
            counts[d["kind"]] += d["usage"]["status"] == "unused_candidate"
    return {
        "entry_points": sorted(roots),
        "entry_point_patterns": entry_points,
        "public_api_patterns": public_api,
        "method": "conservative syntactic references and reachability; identifier matches may overestimate usage; no type inference or execution",
        "mode": "reachability" if roots else "references_only",
    }, {
        kind: counts[kind]
        for kind in ("files", "function", "class", "method", "implementation")
    }
