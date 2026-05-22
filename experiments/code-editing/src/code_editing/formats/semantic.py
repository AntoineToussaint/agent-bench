"""`semantic` edit format — language-agnostic intent-named tools.

Tool names describe ENGINEERING INTENT, not the underlying AST mechanism.
Dispatch happens by file extension:
  - `.py`  → libcst-backed implementations
  - `.ts`  → ts-morph subprocess shim (TODO, raises clear error for now)

Tools (9):
  - rename(paths, old_name, new_name)
  - replace(path, name, new_source)
  - change_value_of(path, target, new_value)
  - add(path, new_source, position?)
  - remove(path, name)
  - move(from_path, to_path, name)
  - add_parameter(path, callable, param_name, default?, annotation?, position?)
  - add_import(path, source, names?)
  - create_file(path, content)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import libcst as cst

from code_editing.formats.base import (
    DONE_TOOL,
    LIST_FILES_TOOL,
    VIEW_FILE_TOOL,
    EditFormat,
    apply_common,
    register_format,
)
from code_editing.types import ToolCall, ToolResult


@register_format
class SemanticFormat(EditFormat):
    name = "semantic"
    description = (
        "Intent-named refactor tools (rename, replace, change_value_of, add, "
        "remove, move, add_parameter, add_import, create_file). Language-"
        "agnostic API; Python today via libcst."
    )

    def tools(self) -> list[dict[str, Any]]:
        return [
            VIEW_FILE_TOOL,
            LIST_FILES_TOOL,
            {
                "name": "rename",
                "description": (
                    "Rename a symbol (function, class, variable, parameter) "
                    "across all listed files. Updates identifier references "
                    "AND any textual mentions in docstrings/comments/strings."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "old_name": {"type": "string"},
                        "new_name": {"type": "string"},
                    },
                    "required": ["paths", "old_name", "new_name"],
                },
            },
            {
                "name": "replace",
                "description": (
                    "Replace a named top-level definition (function, class, "
                    "constant) in a file. Use dotted names for nested members: "
                    "`MyClass.method` to replace a method. `new_source` is the "
                    "full new source of that definition only (def line / class "
                    "line / `NAME = ...` line)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "name": {"type": "string"},
                        "new_source": {"type": "string"},
                    },
                    "required": ["path", "name", "new_source"],
                },
            },
            {
                "name": "change_value_of",
                "description": (
                    "Change the value of a named binding without rewriting "
                    "its declaration. `new_value` is the SOURCE TEXT of a "
                    "language expression — exactly what you'd type on the "
                    "right-hand side of an assignment. Examples:\n"
                    "  new_value=`42`              → integer literal\n"
                    "  new_value=`\"hello\"`        → string literal (quotes "
                    "are PART of the value)\n"
                    "  new_value=`\"  \"`           → two-space string\n"
                    "  new_value=`[1, 2, 3]`        → list literal\n"
                    "  new_value=`compute(x) + 1`   → an expression\n"
                    "Do NOT pass bare strings without quotes (`hello`, `  `) — "
                    "those are not valid Python expressions."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "target": {"type": "string"},
                        "new_value": {"type": "string"},
                    },
                    "required": ["path", "target", "new_value"],
                },
            },
            {
                "name": "add",
                "description": (
                    "Add one or more new top-level definitions (functions, "
                    "classes, constants) to a file. `new_source` may contain "
                    "multiple statements separated by blank lines. `position`: "
                    "`end` (default), `after:NAME`, or `before:NAME` where "
                    "NAME is an existing top-level definition."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "new_source": {"type": "string"},
                        "position": {"type": "string", "default": "end"},
                    },
                    "required": ["path", "new_source"],
                },
            },
            {
                "name": "remove",
                "description": (
                    "Remove a named top-level definition (function, class, "
                    "method, constant). Dotted names supported for nested members."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "name": {"type": "string"},
                    },
                    "required": ["path", "name"],
                },
            },
            {
                "name": "move",
                "description": (
                    "Move a top-level named definition from one file to another. "
                    "Does not rewrite imports; call `add_import`/`remove` "
                    "separately if needed."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "from_path": {"type": "string"},
                        "to_path": {"type": "string"},
                        "name": {"type": "string"},
                    },
                    "required": ["from_path", "to_path", "name"],
                },
            },
            {
                "name": "add_parameter",
                "description": (
                    "Add a parameter to a callable. `callable` is a dotted name "
                    "(`foo` or `MyClass.method`). `default` and `annotation` "
                    "are source expressions. `position`: `end` (default) or "
                    "`start`."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "callable": {"type": "string"},
                        "param_name": {"type": "string"},
                        "default": {"type": "string"},
                        "annotation": {"type": "string"},
                        "position": {"type": "string", "default": "end"},
                    },
                    "required": ["path", "callable", "param_name"],
                },
            },
            {
                "name": "add_import",
                "description": (
                    "Add an import to a file. If `names` is provided, emits "
                    "`from <source> import <names>`; otherwise `import "
                    "<source>`. Inserts at the top of the file (after the "
                    "module docstring, before any other code)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "source": {"type": "string"},
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["path", "source"],
                },
            },
            {
                "name": "create_file",
                "description": "Create a new file with the given content.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            DONE_TOOL,
        ]

    def system_prompt(self) -> str:
        return (
            "You edit code using intent-named refactor operations. Prefer the "
            "most specific tool for the job:\n"
            "  - `rename` for symbol renames\n"
            "  - `change_value_of` for changing the value of a constant/binding\n"
            "  - `replace` for swapping a whole named definition\n"
            "  - `add` / `remove` / `move` for structural changes\n"
            "  - `add_parameter`, `add_import` for targeted additions\n"
            "Methods and nested items use dotted names (e.g. `MyClass.method`)."
        )

    def apply(self, call: ToolCall, workdir: Path) -> ToolResult:
        common = apply_common(call, workdir)
        if common is not None:
            return common
        dispatch = {
            "rename": _do_rename,
            "replace": _do_replace,
            "change_value_of": _do_change_value,
            "add": _do_add,
            "remove": _do_remove,
            "move": _do_move,
            "add_parameter": _do_add_param,
            "add_import": _do_add_import,
            "create_file": _do_create_file,
        }
        handler = dispatch.get(call.name)
        if handler is None:
            return ToolResult(call.call_id, "error", f"unknown tool: {call.name}")
        return handler(call, workdir)


# ============ language dispatch ============


def _check_python(path: Path) -> str | None:
    if path.suffix != ".py":
        return f"only `.py` is supported in v1 (got {path.suffix})"
    return None


def _parse_module(target: Path) -> cst.Module | str:
    try:
        return cst.parse_module(target.read_text(encoding="utf-8"))
    except cst.ParserSyntaxError as e:
        return f"existing file has syntax error: {e}"


def _parse_statement(src: str) -> cst.BaseStatement | str:
    """Parse `src` as a single top-level Python statement."""
    src = _dedent_to_zero(src)
    try:
        mod = cst.parse_module(src)
    except cst.ParserSyntaxError as e:
        return f"new_source parse error: {e}"
    body = [s for s in mod.body if not isinstance(s, cst.EmptyLine)]
    if len(body) != 1:
        return f"new_source must contain exactly one top-level statement (got {len(body)})"
    return body[0]


def _parse_statements(src: str) -> list[cst.BaseStatement] | str:
    """Parse `src` as one or more top-level Python statements."""
    src = _dedent_to_zero(src)
    try:
        mod = cst.parse_module(src)
    except cst.ParserSyntaxError as e:
        return f"new_source parse error: {e}"
    body = [s for s in mod.body if not isinstance(s, cst.EmptyLine)]
    if not body:
        return "new_source is empty"
    return body


def _parse_expression(src: str) -> cst.BaseExpression | str:
    try:
        return cst.parse_expression(src)
    except cst.ParserSyntaxError as e:
        return f"value parse error: {e}"


def _dedent_to_zero(src: str) -> str:
    lines = src.splitlines()
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return src
    indent = min(len(ln) - len(ln.lstrip(" ")) for ln in non_empty)
    if indent == 0:
        return src
    return "\n".join(ln[indent:] if len(ln) >= indent else ln for ln in lines)


# ============ libcst node helpers (Python) ============


def _is_assign_to(stmt: cst.BaseStatement, name: str) -> tuple[cst.BaseStatement, cst.BaseExpression] | None:
    """If `stmt` is an Assign/AnnAssign to `name`, return (stmt, current_value)."""
    if not isinstance(stmt, cst.SimpleStatementLine):
        return None
    for item in stmt.body:
        if isinstance(item, cst.Assign):
            for target in item.targets:
                if isinstance(target.target, cst.Name) and target.target.value == name:
                    return stmt, item.value
        elif isinstance(item, cst.AnnAssign):
            if isinstance(item.target, cst.Name) and item.target.value == name:
                if item.value is not None:
                    return stmt, item.value
    return None


def _body_of(node: cst.CSTNode) -> list[cst.BaseStatement] | None:
    if isinstance(node, cst.Module):
        return list(node.body)
    if isinstance(node, cst.ClassDef) and isinstance(node.body, cst.IndentedBlock):
        return list(node.body.body)
    return None


def _matches_name(stmt: cst.BaseStatement, name: str) -> bool:
    if isinstance(stmt, (cst.FunctionDef, cst.ClassDef)) and stmt.name.value == name:
        return True
    if _is_assign_to(stmt, name) is not None:
        return True
    # Also match imported names (so `position="after:SomeImportedClass"` works)
    if isinstance(stmt, cst.SimpleStatementLine):
        for item in stmt.body:
            if isinstance(item, cst.ImportFrom):
                for alias in item.names or []:
                    if isinstance(alias, cst.ImportStar):
                        continue
                    alias_name = alias.asname.name if alias.asname else alias.name
                    if isinstance(alias_name, cst.Name) and alias_name.value == name:
                        return True
            elif isinstance(item, cst.Import):
                for alias in item.names:
                    alias_name = alias.asname.name if alias.asname else alias.name
                    if isinstance(alias_name, cst.Name) and alias_name.value == name:
                        return True
    return False


def _find_in_path(
    module: cst.Module, dotted_name: str
) -> tuple[cst.BaseStatement, list[cst.CSTNode]] | None:
    """Resolve `Foo.bar` to (target, container_path). container_path is outermost-first."""
    parts = dotted_name.split(".")
    container: cst.CSTNode = module
    path: list[cst.CSTNode] = [module]
    for i, part in enumerate(parts):
        body = _body_of(container)
        if body is None:
            return None
        target = next(
            (s for s in body if _matches_name(s, part)),
            None,
        )
        if target is None:
            return None
        if i == len(parts) - 1:
            return target, path
        if not isinstance(target, cst.ClassDef):
            return None
        container = target
        path.append(target)
    return None


def _list_addressable(module: cst.Module) -> list[str]:
    out: list[str] = []

    def walk(c: cst.CSTNode, prefix: str) -> None:
        body = _body_of(c)
        if body is None:
            return
        for s in body:
            if isinstance(s, cst.FunctionDef):
                out.append(prefix + s.name.value)
            elif isinstance(s, cst.ClassDef):
                out.append(prefix + s.name.value)
                walk(s, prefix + s.name.value + ".")
            else:
                hit = _assign_targets(s)
                for n in hit:
                    out.append(prefix + n)

    walk(module, "")
    return out


def _assign_targets(stmt: cst.BaseStatement) -> list[str]:
    if not isinstance(stmt, cst.SimpleStatementLine):
        return []
    names: list[str] = []
    for item in stmt.body:
        if isinstance(item, cst.Assign):
            for target in item.targets:
                if isinstance(target.target, cst.Name):
                    names.append(target.target.value)
        elif isinstance(item, cst.AnnAssign):
            if isinstance(item.target, cst.Name):
                names.append(item.target.value)
    return names


def _replace_named(
    container: cst.CSTNode, leaf_name: str, replacement: cst.BaseStatement
) -> cst.CSTNode:
    if isinstance(container, cst.Module):
        new_body = [replacement if _matches_name(s, leaf_name) else s for s in container.body]
        return container.with_changes(body=new_body)
    if isinstance(container, cst.ClassDef) and isinstance(container.body, cst.IndentedBlock):
        new_inner = [
            replacement if _matches_name(s, leaf_name) else s for s in container.body.body
        ]
        return container.with_changes(body=container.body.with_changes(body=new_inner))
    raise TypeError(f"can't replace inside {type(container).__name__}")


def _remove_named(container: cst.CSTNode, leaf_name: str) -> cst.CSTNode:
    if isinstance(container, cst.Module):
        new_body = [s for s in container.body if not _matches_name(s, leaf_name)]
        return container.with_changes(body=new_body)
    if isinstance(container, cst.ClassDef) and isinstance(container.body, cst.IndentedBlock):
        new_inner = [s for s in container.body.body if not _matches_name(s, leaf_name)]
        return container.with_changes(body=container.body.with_changes(body=new_inner))
    raise TypeError(f"can't remove inside {type(container).__name__}")


def _rewrite_path(
    path: list[cst.CSTNode], new_leaf: cst.CSTNode, leaf_name: str
) -> cst.Module:
    """Bubble a new leaf back up the container chain. Returns the new Module."""
    new_node: cst.CSTNode = new_leaf
    for c in reversed(path):
        new_node = _replace_named(c, leaf_name, new_node)  # type: ignore[arg-type]
        leaf_name = (
            c.name.value if isinstance(c, (cst.ClassDef, cst.FunctionDef)) else leaf_name
        )
    assert isinstance(new_node, cst.Module)
    return new_node


# ============ tool handlers ============


def _do_rename(call: ToolCall, workdir: Path) -> ToolResult:
    paths = call.arguments.get("paths") or []
    old = call.arguments.get("old_name")
    new = call.arguments.get("new_name")
    if not paths or not old or not new:
        return ToolResult(call.call_id, "error", "missing paths/old_name/new_name")
    if not old.isidentifier():
        return ToolResult(
            call.call_id,
            "error",
            f"`old_name` must be a single identifier, got `{old}`. "
            f"`rename` is for symbol renames, not text changes. For arbitrary "
            f"text edits use `str_replace` (in search_plus) instead.",
        )
    if not new.isidentifier():
        return ToolResult(call.call_id, "error", f"invalid new identifier: {new}")

    word_re = re.compile(rf"\b{re.escape(old)}\b")
    total_ast = 0
    total_text = 0
    touched: list[str] = []
    for rel in paths:
        try:
            target = EditFormat.resolve(workdir, rel)
        except ValueError as e:
            return ToolResult(call.call_id, "error", str(e))
        if not target.exists():
            return ToolResult(call.call_id, "error", f"file not found: {rel}")
        bad = _check_python(target)
        if bad:
            return ToolResult(call.call_id, "error", bad)

        module = _parse_module(target)
        if isinstance(module, str):
            return ToolResult(call.call_id, "error", module)
        renamer = _Renamer(old, new)
        new_module = module.visit(renamer)
        code = new_module.code
        new_code, text_count = word_re.subn(new, code)
        if renamer.count > 0 or text_count > 0:
            target.write_text(new_code, encoding="utf-8")
            touched.append(f"{rel} (ast={renamer.count}, text={text_count})")
            total_ast += renamer.count
            total_text += text_count
    if total_ast == 0 and total_text == 0:
        return ToolResult(call.call_id, "error", f"no occurrences of `{old}` found")
    return ToolResult(
        call.call_id,
        "ok",
        f"renamed {total_ast} identifier(s) + {total_text} textual mention(s): "
        + ", ".join(touched),
    )


class _Renamer(cst.CSTTransformer):
    def __init__(self, old: str, new: str) -> None:
        self.old = old
        self.new = new
        self.count = 0

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        if updated_node.value == self.old:
            self.count += 1
            return updated_node.with_changes(value=self.new)
        return updated_node

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        if updated_node.name.value == self.old:
            self.count += 1
            return updated_node.with_changes(name=cst.Name(self.new))
        return updated_node

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        if updated_node.name.value == self.old:
            self.count += 1
            return updated_node.with_changes(name=cst.Name(self.new))
        return updated_node

    def leave_Param(self, original_node: cst.Param, updated_node: cst.Param) -> cst.Param:
        if isinstance(updated_node.name, cst.Name) and updated_node.name.value == self.old:
            self.count += 1
            return updated_node.with_changes(name=cst.Name(self.new))
        return updated_node


def _do_replace(call: ToolCall, workdir: Path) -> ToolResult:
    path = call.arguments.get("path")
    name = call.arguments.get("name")
    new_source = call.arguments.get("new_source")
    if not path or not name or new_source is None:
        return ToolResult(call.call_id, "error", "missing path/name/new_source")
    try:
        target = EditFormat.resolve(workdir, path)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    bad = _check_python(target)
    if bad:
        return ToolResult(call.call_id, "error", bad)
    module = _parse_module(target)
    if isinstance(module, str):
        return ToolResult(call.call_id, "error", module)

    found = _find_in_path(module, name)
    if found is None:
        addressable = _list_addressable(module)
        return ToolResult(
            call.call_id,
            "error",
            f"`{name}` not found in {path}. Addressable: {', '.join(addressable) or '(none)'}",
        )
    _, container_path = found
    new_stmts = _parse_statements(new_source)
    if isinstance(new_stmts, str):
        return ToolResult(call.call_id, "error", new_stmts)
    for s in new_stmts:
        if not isinstance(s, (cst.FunctionDef, cst.ClassDef, cst.SimpleStatementLine)):
            return ToolResult(
                call.call_id,
                "error",
                f"new_source statements must be def/class/simple-stmt (got {type(s).__name__})",
            )

    leaf_name = name.split(".")[-1]
    # Replace the matching node with the FIRST new statement; insert the rest
    # as siblings immediately after (so `replace(X, "def X():\n...\n\ndef Y()...")`
    # works the way the model usually intends).
    innermost = container_path[-1]
    new_inner = _replace_named(innermost, leaf_name, new_stmts[0])
    if len(new_stmts) > 1:
        body = _body_of(new_inner)
        assert body is not None
        idx = next(
            (i for i, s in enumerate(body) if _matches_name(s, leaf_name)),
            None,
        )
        assert idx is not None
        new_body = body[: idx + 1] + new_stmts[1:] + body[idx + 1 :]
        if isinstance(new_inner, cst.Module):
            new_inner = new_inner.with_changes(body=new_body)
        else:
            assert isinstance(new_inner, cst.ClassDef) and isinstance(new_inner.body, cst.IndentedBlock)
            new_inner = new_inner.with_changes(body=new_inner.body.with_changes(body=new_body))

    if isinstance(innermost, cst.Module):
        assert isinstance(new_inner, cst.Module)
        new_module = new_inner
    else:
        parent_leaf = innermost.name.value if isinstance(innermost, (cst.ClassDef, cst.FunctionDef)) else ""
        new_module = _rewrite_path(container_path[:-1], new_inner, parent_leaf)
    target.write_text(new_module.code, encoding="utf-8")
    return ToolResult(
        call.call_id,
        "ok",
        f"replaced {name} in {path}"
        + (f" + {len(new_stmts)-1} sibling(s) inserted" if len(new_stmts) > 1 else ""),
    )


def _do_change_value(call: ToolCall, workdir: Path) -> ToolResult:
    path = call.arguments.get("path")
    target_name = call.arguments.get("target")
    new_value = call.arguments.get("new_value")
    if not path or not target_name or new_value is None:
        return ToolResult(call.call_id, "error", "missing path/target/new_value")
    try:
        target = EditFormat.resolve(workdir, path)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    bad = _check_python(target)
    if bad:
        return ToolResult(call.call_id, "error", bad)
    module = _parse_module(target)
    if isinstance(module, str):
        return ToolResult(call.call_id, "error", module)

    new_value_expr = _parse_expression(new_value)
    if isinstance(new_value_expr, str):
        # Lenient fallback: treat unparseable input as a string literal.
        # Matches user expectation that `new_value="  "` means "set to the
        # two-space string", which a real refactor UI would also accept.
        try:
            new_value_expr = cst.parse_expression(repr(new_value))
        except cst.ParserSyntaxError as e:
            return ToolResult(
                call.call_id,
                "error",
                f"new_value could not be parsed as a Python expression: {e}",
            )

    changer = _ValueChanger(target_name, new_value_expr)
    new_module = module.visit(changer)
    if changer.count == 0:
        return ToolResult(
            call.call_id,
            "error",
            f"no top-level binding named `{target_name}` in {path}",
        )
    target.write_text(new_module.code, encoding="utf-8")
    return ToolResult(
        call.call_id, "ok", f"changed value of `{target_name}` in {path}"
    )


class _ValueChanger(cst.CSTTransformer):
    """Rewrite the value of every top-level Assign/AnnAssign matching `target`."""

    def __init__(self, target: str, new_value: cst.BaseExpression) -> None:
        self.target = target
        self.new_value = new_value
        self.count = 0
        self._depth = 0

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        self._depth += 1
        return True

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        self._depth -= 1
        return updated_node

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        self._depth += 1
        return True

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.ClassDef:
        self._depth -= 1
        return updated_node

    def leave_Assign(self, original_node: cst.Assign, updated_node: cst.Assign) -> cst.Assign:
        if self._depth != 0:
            return updated_node
        for t in updated_node.targets:
            if isinstance(t.target, cst.Name) and t.target.value == self.target:
                self.count += 1
                return updated_node.with_changes(value=self.new_value)
        return updated_node

    def leave_AnnAssign(
        self, original_node: cst.AnnAssign, updated_node: cst.AnnAssign
    ) -> cst.AnnAssign:
        if self._depth != 0:
            return updated_node
        if isinstance(updated_node.target, cst.Name) and updated_node.target.value == self.target:
            self.count += 1
            return updated_node.with_changes(value=self.new_value)
        return updated_node


def _do_add(call: ToolCall, workdir: Path) -> ToolResult:
    path = call.arguments.get("path")
    new_source = call.arguments.get("new_source")
    position = call.arguments.get("position", "end") or "end"
    if not path or new_source is None:
        return ToolResult(call.call_id, "error", "missing path/new_source")
    try:
        target = EditFormat.resolve(workdir, path)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    bad = _check_python(target)
    if bad:
        return ToolResult(call.call_id, "error", bad)
    if not target.exists():
        return ToolResult(call.call_id, "error", f"file not found: {path}")
    module = _parse_module(target)
    if isinstance(module, str):
        return ToolResult(call.call_id, "error", module)
    new_stmts = _parse_statements(new_source)
    if isinstance(new_stmts, str):
        return ToolResult(call.call_id, "error", new_stmts)

    body = list(module.body)
    if position == "end":
        body.extend(new_stmts)
    elif position.startswith("after:") or position.startswith("before:"):
        kind, _, anchor = position.partition(":")
        idx = next(
            (i for i, s in enumerate(body) if _matches_name(s, anchor)),
            None,
        )
        if idx is None:
            return ToolResult(call.call_id, "error", f"anchor `{anchor}` not found")
        insert_at = idx if kind == "before" else idx + 1
        body[insert_at:insert_at] = new_stmts
    else:
        return ToolResult(
            call.call_id,
            "error",
            f"bad position `{position}` (use `end`, `after:NAME`, or `before:NAME`)",
        )
    target.write_text(module.with_changes(body=body).code, encoding="utf-8")
    return ToolResult(
        call.call_id, "ok", f"added {len(new_stmts)} statement(s) to {path} ({position})"
    )


def _do_remove(call: ToolCall, workdir: Path) -> ToolResult:
    path = call.arguments.get("path")
    name = call.arguments.get("name")
    if not path or not name:
        return ToolResult(call.call_id, "error", "missing path/name")
    try:
        target = EditFormat.resolve(workdir, path)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    bad = _check_python(target)
    if bad:
        return ToolResult(call.call_id, "error", bad)
    module = _parse_module(target)
    if isinstance(module, str):
        return ToolResult(call.call_id, "error", module)

    found = _find_in_path(module, name)
    if found is None:
        return ToolResult(call.call_id, "error", f"`{name}` not found in {path}")
    _, container_path = found
    leaf = name.split(".")[-1]
    innermost = container_path[-1]
    new_inner = _remove_named(innermost, leaf)
    if isinstance(innermost, cst.Module):
        assert isinstance(new_inner, cst.Module)
        new_module = new_inner
    else:
        parent_leaf = innermost.name.value if isinstance(innermost, (cst.ClassDef, cst.FunctionDef)) else ""
        new_module = _rewrite_path(container_path[:-1], new_inner, parent_leaf)
    target.write_text(new_module.code, encoding="utf-8")
    return ToolResult(call.call_id, "ok", f"removed {name} from {path}")


def _do_move(call: ToolCall, workdir: Path) -> ToolResult:
    from_rel = call.arguments.get("from_path")
    to_rel = call.arguments.get("to_path")
    name = call.arguments.get("name")
    if not from_rel or not to_rel or not name:
        return ToolResult(call.call_id, "error", "missing from_path/to_path/name")
    if "." in name:
        return ToolResult(call.call_id, "error", "move requires a top-level name (no dots)")
    try:
        src_path = EditFormat.resolve(workdir, from_rel)
        dst_path = EditFormat.resolve(workdir, to_rel)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    bad = _check_python(src_path) or _check_python(dst_path)
    if bad:
        return ToolResult(call.call_id, "error", bad)
    src_mod = _parse_module(src_path)
    if isinstance(src_mod, str):
        return ToolResult(call.call_id, "error", src_mod)
    moved = next(
        (s for s in src_mod.body if _matches_name(s, name)),
        None,
    )
    if moved is None:
        return ToolResult(call.call_id, "error", f"`{name}` not in {from_rel}")
    new_src = src_mod.with_changes(body=[s for s in src_mod.body if s is not moved])
    src_path.write_text(new_src.code, encoding="utf-8")
    if dst_path.exists():
        dst_mod = _parse_module(dst_path)
        if isinstance(dst_mod, str):
            return ToolResult(call.call_id, "error", dst_mod)
        new_dst = dst_mod.with_changes(body=list(dst_mod.body) + [moved])
    else:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        new_dst = cst.Module(body=[moved])
    dst_path.write_text(new_dst.code, encoding="utf-8")
    return ToolResult(call.call_id, "ok", f"moved {name} from {from_rel} to {to_rel}")


def _do_add_param(call: ToolCall, workdir: Path) -> ToolResult:
    path = call.arguments.get("path")
    callable_name = call.arguments.get("callable")
    pname = call.arguments.get("param_name")
    default = call.arguments.get("default")
    annotation = call.arguments.get("annotation")
    position = (call.arguments.get("position") or "end").lower()
    if not path or not callable_name or not pname:
        return ToolResult(call.call_id, "error", "missing path/callable/param_name")
    try:
        target = EditFormat.resolve(workdir, path)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    bad = _check_python(target)
    if bad:
        return ToolResult(call.call_id, "error", bad)
    module = _parse_module(target)
    if isinstance(module, str):
        return ToolResult(call.call_id, "error", module)
    found = _find_in_path(module, callable_name)
    if found is None:
        return ToolResult(call.call_id, "error", f"`{callable_name}` not found in {path}")
    func, container_path = found
    if not isinstance(func, cst.FunctionDef):
        return ToolResult(call.call_id, "error", f"`{callable_name}` is not a function/method")

    ann_node = None
    if annotation:
        ann_expr = _parse_expression(annotation)
        if isinstance(ann_expr, str):
            return ToolResult(call.call_id, "error", f"annotation parse error: {ann_expr}")
        ann_node = cst.Annotation(annotation=ann_expr)
    default_node: cst.BaseExpression | None = None
    if default:
        def_expr = _parse_expression(default)
        if isinstance(def_expr, str):
            return ToolResult(call.call_id, "error", f"default parse error: {def_expr}")
        default_node = def_expr
    new_param = cst.Param(
        name=cst.Name(pname),
        annotation=ann_node,
        default=default_node,
    )

    params = list(func.params.params)
    if any(isinstance(p.name, cst.Name) and p.name.value == pname for p in params):
        return ToolResult(call.call_id, "error", f"parameter `{pname}` already exists")
    if position == "start":
        if params and isinstance(params[0].name, cst.Name) and params[0].name.value in {"self", "cls"}:
            params.insert(1, new_param)
        else:
            params.insert(0, new_param)
    else:
        params.append(new_param)
    new_func = func.with_changes(params=func.params.with_changes(params=params))

    leaf = callable_name.split(".")[-1]
    new_module = _rewrite_path(container_path, new_func, leaf)
    target.write_text(new_module.code, encoding="utf-8")
    return ToolResult(call.call_id, "ok", f"added param `{pname}` to `{callable_name}` in {path}")


def _do_add_import(call: ToolCall, workdir: Path) -> ToolResult:
    path = call.arguments.get("path")
    source = call.arguments.get("source")
    names = call.arguments.get("names") or []
    if not path or not source:
        return ToolResult(call.call_id, "error", "missing path/source")
    try:
        target = EditFormat.resolve(workdir, path)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    bad = _check_python(target)
    if bad:
        return ToolResult(call.call_id, "error", bad)
    module = _parse_module(target)
    if isinstance(module, str):
        return ToolResult(call.call_id, "error", module)

    if names:
        import_src = f"from {source} import " + ", ".join(names) + "\n"
    else:
        import_src = f"import {source}\n"
    import_stmt = _parse_statement(import_src)
    if isinstance(import_stmt, str):
        return ToolResult(call.call_id, "error", import_stmt)

    # Insert after docstring + any existing imports
    body = list(module.body)
    idx = 0
    # skip module docstring (a SimpleStatementLine with a single Expr/SimpleString)
    if body and isinstance(body[0], cst.SimpleStatementLine):
        first = body[0]
        if (
            len(first.body) == 1
            and isinstance(first.body[0], cst.Expr)
            and isinstance(first.body[0].value, (cst.SimpleString, cst.ConcatenatedString))
        ):
            idx = 1
    # skip existing top-level imports
    while idx < len(body) and isinstance(body[idx], cst.SimpleStatementLine) and all(
        isinstance(s, (cst.Import, cst.ImportFrom)) for s in body[idx].body
    ):
        idx += 1
    body.insert(idx, import_stmt)
    target.write_text(module.with_changes(body=body).code, encoding="utf-8")
    return ToolResult(call.call_id, "ok", f"added import to {path}")


def _do_create_file(call: ToolCall, workdir: Path) -> ToolResult:
    path = call.arguments.get("path")
    content = call.arguments.get("content")
    if not path or content is None:
        return ToolResult(call.call_id, "error", "missing path/content")
    try:
        target = EditFormat.resolve(workdir, path)
    except ValueError as e:
        return ToolResult(call.call_id, "error", str(e))
    if target.exists():
        return ToolResult(call.call_id, "error", f"already exists: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return ToolResult(call.call_id, "ok", f"created {path} ({len(content)} bytes)")
