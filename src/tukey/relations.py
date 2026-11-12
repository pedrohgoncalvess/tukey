"""Conservative syntactic call resolution, without executing project code."""


def call_graph(files):
    declarations = {d["id"]: d for f in files for d in f["declarations"]}
    by_file = {f["path"]: f for f in files}
    edges = {}
    unresolved = []

    def class_owner(declaration):
        while declaration:
            if declaration["kind"] in {"class", "implementation"}:
                return declaration
            declaration = declarations.get(declaration["parent_id"])
        return None

    def functions(file, name, parent=None):
        return [
            d
            for d in file["declarations"]
            if d["kind"] in {"function", "method"}
            and d["name"] == name
            and d["parent_id"] == parent
        ]

    for file in files:
        for call in file["calls"]:
            caller = declarations.get(call["caller_id"])
            source = call["caller_id"] or "module:" + file["module_id"]
            name, receiver = call["name"], call["receiver"]
            candidates = []
            shadowed = caller and any(
                p["name"].lstrip("$") == (receiver or name).lstrip("$")
                for p in caller["types"]["parameters"]
                if not p["implicit"]
            )
            if not shadowed and receiver in {"self", "cls", "this", "$this", "Self"}:
                owner = class_owner(caller)
                if owner:
                    candidates = functions(file, name, owner["id"])
            elif not shadowed and receiver is None:
                scope = caller
                # Nearest lexical scope wins, including recursion and nested functions.
                while scope:
                    candidates = (
                        functions(file, name, scope["id"])
                        if scope["kind"] not in {"class", "implementation"}
                        or file["language"] in {"java", "scala"}
                        else []
                    )
                    if candidates:
                        break
                    scope = declarations.get(scope["parent_id"])
                if not candidates:
                    candidates = functions(file, name)
            elif not shadowed and receiver:
                owners = [
                    d
                    for d in file["declarations"]
                    if d["kind"] in {"class", "implementation"}
                    and d["name"] == receiver
                ]
                for owner in owners:
                    candidates.extend(functions(file, name, owner["id"]))
            if not candidates and not shadowed:
                for item in file["imports"]:
                    binding = item["binding"]
                    if not binding or binding != (receiver or name):
                        continue
                    for path in item["resolved_files"]:
                        imported = by_file[path]
                        if receiver is None:
                            if item["kind"] == "symbol":
                                candidates.extend(
                                    functions(imported, item["imported_name"] or name)
                                )
                        elif item["kind"] in {"module", "namespace", "commonjs"} or (
                            file["language"] == "python"
                            and item["imported_name"]
                            == imported["path"].rsplit("/", 1)[-1].split(".")[0]
                        ):
                            candidates.extend(functions(imported, name))
                        else:
                            for owner in imported["declarations"]:
                                if (
                                    owner["kind"] in {"class", "implementation"}
                                    and owner["name"] == item["imported_name"]
                                ):
                                    candidates.extend(
                                        functions(imported, name, owner["id"])
                                    )
            candidates = {d["id"]: d for d in candidates}
            if len(candidates) != 1 or file["diagnostics"]:
                unresolved.append(
                    {
                        "source": source,
                        "file": file["path"],
                        **call,
                        "reason": (
                            "ambiguous"
                            if len(candidates) > 1
                            else (
                                "syntax_error"
                                if file["diagnostics"]
                                else "external_or_dynamic"
                            )
                        ),
                    }
                )
                continue
            target = next(iter(candidates))
            edge = edges.setdefault(
                (source, target),
                {"source": source, "target": target, "call_count": 0, "sites": []},
            )
            edge["call_count"] += 1
            edge["sites"].append(
                {
                    "file": file["path"],
                    "line": call["start_line"],
                    "expression": call["expression"],
                }
            )
    return {
        "edges": [edge for _, edge in sorted(edges.items())],
        "unresolved": unresolved,
        "method": "syntactic: lexical names, named imports, module aliases and explicit class receivers; no type inference",
    }
