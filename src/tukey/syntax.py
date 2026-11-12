"""Tree-sitter adapters. Source code is never imported or executed."""

from collections import Counter
from tree_sitter_language_pack import get_parser

EXTENSIONS = {
    ".py": "python",
    ".pyi": "python",
    ".rs": "rust",
    ".scala": "scala",
    ".java": "java",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".php": "php",
}
CLASS_NODES = {
    "class_definition",
    "class_declaration",
    "abstract_class_declaration",
    "trait_definition",
    "object_definition",
    "interface_declaration",
    "trait_item",
    "struct_item",
    "enum_item",
    "enum_declaration",
    "record_declaration",
    "trait_declaration",
    "enum_definition",
}
CALLABLE_NODES = {
    "function_definition",
    "function_declaration",
    "function_item",
    "method_declaration",
    "method_definition",
    "constructor_declaration",
    "arrow_function",
    "function_expression",
    "anonymous_function",
    "lambda",
    "function_signature",
    "abstract_method_signature",
    "method_signature",
    "lambda_expression",
    "closure_expression",
}
IMPORT_NODES = {
    "import_statement",
    "import_from_statement",
    "import_declaration",
    "use_declaration",
    "namespace_use_declaration",
}
IDENTIFIERS = {
    "identifier",
    "type_identifier",
    "property_identifier",
    "field_identifier",
    "name",
}


def walk(root):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.named_children))


def text(node) -> str:
    return node.text.decode("utf-8") if node else ""


def field(node, name):
    return node.child_by_field_name(name)


def line_range(node) -> dict:
    end = node.end_point.row + (1 if node.end_point.column else 0)
    return {
        "start_line": node.start_point.row + 1,
        "end_line": max(node.start_point.row + 1, end),
    }


def size(source: bytes, node=None) -> dict:
    chunk = source if node is None else source[node.start_byte : node.end_byte]
    lines = chunk.decode("utf-8").splitlines()
    count = (
        len(lines)
        if node is None
        else line_range(node)["end_line"] - node.start_point.row
    )
    return {
        "bytes": len(chunk),
        "lines": count,
        "nonblank_lines": sum(bool(line.strip()) for line in lines),
    }


def annotation(node):
    return text(field(node, "type") or field(node, "return_type")) or None


def callable_types(node, language, kind):
    candidates = [
        child
        for params in node.children_by_field_name("parameters")
        for child in params.named_children
    ]
    if field(node, "parameter"):
        candidates = [field(node, "parameter")]
    result = []
    for param in candidates:
        if param.type in {"comment", "positional_separator", "keyword_separator"}:
            continue
        name_node = field(param, "name") or field(param, "pattern")
        if name_node is None:
            name_node = next(
                (
                    c
                    for c in param.named_children
                    if c.type in IDENTIFIERS or c.type == "variable_name"
                ),
                param,
            )
        name = text(name_node)
        implicit = param.type == "self_parameter" or (
            language == "python" and kind == "method" and name in {"self", "cls"}
        )
        result.append(
            {"name": name, "annotation": annotation(param), "implicit": implicit}
        )
    return_node = field(node, "return_type")
    if language == "java":
        return_node = field(node, "type")
    return_type = text(return_node) or None
    implicit_return = (
        language == "rust"
        and return_type is None
        and node.type in {"function_item", "function_signature"}
    )
    constructor = node.type == "constructor_declaration" or text(
        field(node, "name")
    ) in {"constructor", "__construct"}
    applicable = language != "javascript"
    eligible = [p for p in result if not p["implicit"]]
    slots = len(eligible) + (0 if constructor else 1)
    annotated = sum(p["annotation"] is not None for p in eligible) + int(
        not constructor and (return_type is not None or implicit_return)
    )
    return {
        "policy": (
            "not_applicable"
            if not applicable
            else "best_practice" if language in {"python", "php"} else "static"
        ),
        "parameters": result,
        "return_annotation": return_type,
        "implicit_return": "()" if implicit_return else None,
        "eligible_slots": slots if applicable else 0,
        "annotated_slots": annotated if applicable else 0,
        "coverage": annotated / slots if slots and applicable else None,
    }


def rust_paths(node, prefix=""):
    if node.type == "scoped_use_list":
        yield from rust_paths(
            field(node, "list"), prefix + text(field(node, "path")) + "::"
        )
    elif node.type == "use_list":
        for child in node.named_children:
            yield from rust_paths(child, prefix)
    elif node.type == "use_as_clause":
        yield prefix + text(field(node, "path")), text(field(node, "alias"))
    else:
        target = prefix + text(node)
        yield target, None if target.endswith("*") else target.split("::")[-1]


def extract_imports(node, language):
    if language == "python":
        module = text(field(node, "module_name"))
        for name in node.children_by_field_name("name"):
            original = (
                text(field(name, "name"))
                if name.type == "aliased_import"
                else text(name)
            )
            alias = text(field(name, "alias")) if name.type == "aliased_import" else ""
            yield module or original, alias or (
                original.split(".")[0] if not module else original
            ), ("symbol" if module else "module")
        if any(c.type == "wildcard_import" for c in node.named_children):
            yield module, None, "wildcard"
    elif language in {"javascript", "typescript"}:
        target = text(field(node, "source")).strip("\"'")
        clause = next(
            (c for c in node.named_children if c.type == "import_clause"), None
        )
        if clause is None:
            yield target, None, "side_effect"
        else:
            for child in clause.named_children:
                if child.type == "identifier":
                    yield target, text(child), "default"
                elif child.type == "namespace_import":
                    yield target, text(child.named_children[-1]), "namespace"
                elif child.type == "named_imports":
                    for spec in child.named_children:
                        yield target, text(
                            field(spec, "alias") or field(spec, "name")
                        ), "symbol"
    elif language == "rust":
        for target, binding in rust_paths(field(node, "argument")):
            yield target, binding, "wildcard" if binding is None else "symbol"
    elif language == "java":
        target = next(
            (
                text(c)
                for c in node.named_children
                if c.type in {"identifier", "scoped_identifier"}
            ),
            "",
        )
        wildcard = any(c.type == "asterisk" for c in node.named_children)
        yield target, None if wildcard else target.split(".")[-1], (
            "wildcard" if wildcard else "symbol"
        )
    elif language == "scala":
        prefix = ".".join(
            text(c) for c in node.children_by_field_name("path") if c.is_named
        )
        selectors = next(
            (c for c in node.named_children if c.type == "namespace_selectors"), None
        )
        if selectors:
            for child in selectors.named_children:
                name = text(field(child, "name")) or text(child)
                alias = text(field(child, "alias")) or name
                yield prefix + "." + name, None if alias in {"_", "*"} else alias, (
                    "wildcard" if alias in {"_", "*"} else "symbol"
                )
        else:
            wildcard = text(node).rstrip().endswith(("._", ".*"))
            yield prefix, None if wildcard else prefix.split(".")[-1], (
                "wildcard" if wildcard else "symbol"
            )
    elif language == "php":
        group_prefix = next(
            (text(c) for c in node.named_children if c.type == "namespace_name"), ""
        )
        for clause in walk(node):
            if clause.type == "namespace_use_clause":
                name = next(
                    (
                        text(c)
                        for c in clause.named_children
                        if c.type in {"qualified_name", "namespace_name", "name"}
                    ),
                    "",
                )
                target = (group_prefix + "\\" + name).strip("\\")
                yield target, text(field(clause, "alias")) or target.split("\\")[
                    -1
                ], "symbol"


DECISIONS = {
    "if_statement",
    "elif_clause",
    "if_expression",
    "conditional_expression",
    "ternary_expression",
    "for_statement",
    "for_expression",
    "for_in_statement",
    "while_statement",
    "while_expression",
    "do_statement",
    "catch_clause",
    "except_clause",
    "case_clause",
    "switch_case",
    "match_arm",
}
CALL_NODES = {
    "call",
    "call_expression",
    "method_invocation",
    "function_call_expression",
    "scoped_call_expression",
    "member_call_expression",
}


def complexity(node):
    count = 1
    stack = list(node.named_children)
    while stack:
        current = stack.pop()
        if current.type in CALLABLE_NODES or current.type in CLASS_NODES:
            continue
        count += int(current.type in DECISIONS)
        if current.type in {
            "boolean_operator",
            "binary_expression",
            "infix_expression",
        }:
            count += sum(
                text(c) in {"and", "or", "&&", "||"}
                for c in current.children
                if not c.is_named or c == field(current, "operator")
            )
        stack.extend(current.named_children)
    return {"cyclomatic": count, "method": "syntax_estimate"}


def extract_calls(nodes, declarations):
    calls = []
    for node in nodes:
        if node.type not in CALL_NODES:
            continue
        callee = field(node, "function")
        name = field(node, "name")
        receiver = field(node, "object") or field(node, "scope")
        if callee:
            name = (
                field(callee, "attribute")
                or field(callee, "property")
                or field(callee, "field")
                or field(callee, "name")
                or callee
            )
            receiver = (
                field(callee, "object")
                or field(callee, "value")
                or field(callee, "path")
            )
        if not name:
            continue
        owners = [
            d
            for d in declarations
            if d["kind"] in {"function", "method"}
            and d["_start"] <= node.start_byte < d["_end"]
        ]
        owner = min(owners, key=lambda d: d["_end"] - d["_start"]) if owners else None
        calls.append(
            {
                "caller_id": owner["id"] if owner else None,
                "name": text(name),
                "receiver": text(receiver) or None,
                "expression": (
                    text(callee)
                    if callee
                    else ((text(receiver) + ".") if receiver else "") + text(name)
                ),
                **line_range(node),
            }
        )
    return calls


def parse(source: bytes, language: str, extension: str) -> dict:
    root = (
        get_parser("tsx" if extension == ".tsx" else language).parse(source).root_node
    )
    nodes = list(walk(root))
    imports = []
    for node in nodes:
        if node.type in IMPORT_NODES:
            for index, (target, binding, kind) in enumerate(
                extract_imports(node, language)
            ):
                imported_name = None
                names = node.children_by_field_name("name")
                if language == "python" and index < len(names):
                    name = names[index]
                    imported_name = (
                        text(field(name, "name"))
                        if name.type == "aliased_import"
                        else text(name)
                    )
                elif language in {"javascript", "typescript"} and kind == "symbol":
                    spec = next(
                        (
                            c
                            for c in walk(node)
                            if c.type == "import_specifier"
                            and text(field(c, "alias") or field(c, "name")) == binding
                        ),
                        None,
                    )
                    imported_name = text(field(spec, "name")) if spec else None
                elif language in {"rust", "java", "scala", "php"}:
                    imported_name = (
                        target.replace("::", ".").replace("\\", ".").split(".")[-1]
                    )
                imports.append(
                    {
                        "target": target,
                        "binding": binding,
                        "imported_name": imported_name,
                        "kind": kind,
                        **line_range(node),
                        "_node": node,
                    }
                )
        elif node.type == "export_statement" and field(node, "source"):
            imports.append(
                {
                    "target": text(field(node, "source")).strip("\"'"),
                    "binding": None,
                    "imported_name": None,
                    "kind": "reexport",
                    **line_range(node),
                    "_node": node,
                }
            )
        elif (
            language == "rust"
            and node.type == "mod_item"
            and field(node, "body") is None
        ):
            imports.append(
                {
                    "target": "self::" + text(field(node, "name")),
                    "binding": None,
                    "imported_name": None,
                    "kind": "module_declaration",
                    **line_range(node),
                    "_node": node,
                }
            )
    if language in {"javascript", "typescript"}:
        for node in nodes:
            if node.type != "call_expression" or text(field(node, "function")) not in {
                "require",
                "import",
            }:
                continue
            args = field(node, "arguments")
            if args and args.named_children and args.named_children[0].type == "string":
                parent = node.parent
                name_node = field(parent, "name")
                binding = (
                    text(name_node)
                    if parent.type == "variable_declarator"
                    and name_node is not None
                    and name_node.type == "identifier"
                    else None
                )
                imports.append(
                    {
                        "target": text(args.named_children[0]).strip("\"'"),
                        "binding": binding,
                        "imported_name": None,
                        "kind": "commonjs" if binding else "dynamic",
                        **line_range(node),
                        "_node": parent if binding else node,
                    }
                )
    references = Counter()
    ranges = [(i["_node"].start_byte, i["_node"].end_byte) for i in imports]
    for node in nodes:
        if node.type in IDENTIFIERS and not any(
            a <= node.start_byte < b for a, b in ranges
        ):
            references[text(node)] += 1
    for item in imports:
        binding = item["binding"]
        item["usage"] = (
            "unknown"
            if binding is None or root.has_error
            else "referenced" if references[binding] else "unused_candidate"
        )
        item.pop("_node")
    declarations, variables = [], []
    for node in nodes:
        if node.type in CLASS_NODES or node.type == "impl_item":
            kind = "implementation" if node.type == "impl_item" else "class"
        elif node.type in CALLABLE_NODES:
            kind = "function"
            parent = node.parent
            while parent:
                if parent.type in CALLABLE_NODES:
                    break
                if parent.type in CLASS_NODES or parent.type == "impl_item":
                    kind = "method"
                    break
                parent = parent.parent
            if node.type in {
                "method_definition",
                "method_declaration",
                "constructor_declaration",
                "abstract_method_signature",
            }:
                kind = "method"
        else:
            if node.type in {
                "variable_declarator",
                "assignment",
                "property_declaration",
                "field_declaration",
                "public_field_definition",
                "val_definition",
                "var_definition",
                "let_declaration",
            }:
                name = (
                    field(node, "name") or field(node, "left") or field(node, "pattern")
                )
                variables.append(
                    {
                        "name": text(name) or text(node).split("\n")[0],
                        "annotation": annotation(node),
                        **line_range(node),
                    }
                )
            continue
        name = text(
            field(node, "name")
            or (field(node, "type") if kind == "implementation" else None)
        )
        if not name and node.parent.type in {
            "variable_declarator",
            "pair",
            "assignment",
            "assignment_expression",
            "let_declaration",
        }:
            name = text(
                field(node.parent, "name")
                or field(node.parent, "key")
                or field(node.parent, "left")
                or field(node.parent, "pattern")
            )
        name = (
            name
            or f"<anonymous@{node.start_point.row + 1}:{node.start_point.column + 1}>"
        )
        parent, owner = node.parent, None
        while parent:
            owner = next(
                (
                    d["id"]
                    for d in declarations
                    if d["_start"] == parent.start_byte and d["_end"] == parent.end_byte
                ),
                None,
            )
            if owner:
                break
            parent = parent.parent
        declarations.append(
            {
                "id": f"{kind}:{node.start_byte}:{node.end_byte}",
                "name": name,
                "kind": kind,
                "syntax_kind": node.type,
                "parent_id": owner,
                **line_range(node),
                "size": size(source, node),
                "types": (
                    callable_types(node, language, kind)
                    if kind in {"method", "function"}
                    else None
                ),
                "complexity": (
                    complexity(node) if kind in {"function", "method"} else None
                ),
                "_start": node.start_byte,
                "_end": node.end_byte,
            }
        )
    calls = extract_calls(nodes, declarations)
    from .usage import syntax_usage

    usage_metadata = syntax_usage(nodes, declarations, ranges, language)
    for declaration in declarations:
        declaration.pop("_start")
        declaration.pop("_end")
    slots = sum(d["types"]["eligible_slots"] for d in declarations if d["types"])
    typed = sum(d["types"]["annotated_slots"] for d in declarations if d["types"])
    errors = []
    error_stack = [root]
    while error_stack:
        current = error_stack.pop()
        if current.type == "ERROR" or current.is_missing:
            errors.append(
                {
                    "code": "syntax_error",
                    "message": "Incomplete or invalid syntax",
                    **line_range(current),
                }
            )
        error_stack.extend(reversed(current.children))
    package = next(
        (
            text(field(n, "name")) or text(n).removeprefix("package ").rstrip(";")
            for n in nodes
            if n.type
            in {"package_declaration", "package_clause", "namespace_definition"}
        ),
        None,
    )
    return {
        "_usage": usage_metadata,
        "size": size(source),
        "declarations": declarations,
        "imports": imports,
        "calls": calls,
        "types": {
            "eligible_slots": slots,
            "annotated_slots": typed,
            "coverage": typed / slots if slots else None,
            "variables": variables,
        },
        "package": package,
        "diagnostics": errors,
    }
