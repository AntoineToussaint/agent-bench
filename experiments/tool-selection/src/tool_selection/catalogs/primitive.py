"""Primitive-only catalog: minimal toolset for phase 3 lesson-promotion experiments.

We deliberately strip the catalog down to:
  - `bash` — the unstructured shell primitive (with a deliberately SPARSE
    description: no examples, no convention hints, just 'runs a shell command')
  - `read_file`, `write_file`, `list_directory` — minimal filesystem
    primitives so tasks can complete after they figure out the test invocation

This setup defeats two of the three redundancy layers from phase 2:
  - Layer 1 (catalog design): no structured `run_tests` to route around bash
  - Layer 2 (description quality): bash description gives no path rule

Layer 3 (model pretraining) may or may not defeat it on its own — that's
what the phase 3 experiment measures.
"""

from __future__ import annotations

from tool_selection.types import Catalog, Tool, Toolbox

from ._descriptions import TOOLBOX_DESCRIPTIONS


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


# Sparse bash description — DELIBERATELY uninformative. No examples, no path
# conventions, no mention of cwd. This is what a poorly-documented MCP tool
# looks like in production.
PRIMITIVE_TOOLS = (
    Tool(
        name="bash",
        toolbox="filesystem",
        description="Execute a shell command. Returns stdout, stderr, and exit code.",
        json_schema=_schema(
            {"command": {"type": "string"}},
            required=["command"],
        ),
    ),
    Tool(
        name="read_file",
        toolbox="filesystem",
        description="Read the contents of a file.",
        json_schema=_schema(
            {"path": {"type": "string"}},
            required=["path"],
        ),
    ),
    Tool(
        name="write_file",
        toolbox="filesystem",
        description="Write content to a file, overwriting if it exists.",
        json_schema=_schema(
            {"path": {"type": "string"}, "content": {"type": "string"}},
            required=["path", "content"],
        ),
    ),
    Tool(
        name="list_directory",
        toolbox="filesystem",
        description="List the contents of a directory.",
        json_schema=_schema(
            {"path": {"type": "string"}},
            required=["path"],
        ),
    ),
)


primitive_catalog = Catalog(
    granularity="primitive",  # type: ignore[arg-type]  # not in the Granularity Literal; that's OK
    toolboxes=(
        Toolbox(
            name="filesystem",
            description=TOOLBOX_DESCRIPTIONS["filesystem"],
            tools=PRIMITIVE_TOOLS,
        ),
    ),
)
