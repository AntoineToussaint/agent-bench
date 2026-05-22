"""LLM-driven derived-tool synthesis.

Given a cluster of recurring lessons + the source tool, ask Sonnet to design
a derived tool that wraps the source with the fix encoded. The LLM emits a
structured spec (JSON), not Python code — we never eval LLM output.

The spec format intentionally constrains what's expressible to safe
transformations: Python str.format on a template, optional conditional
appends based on boolean args. This covers the vast majority of
'wrap a primitive with a project-specific convention' cases without
opening an arbitrary-code surface.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from agent_eval import make_client

from tool_selection.pricing import cost_for
from tool_selection.types import Tool

from .lessons import Lesson
from .promotion import DerivedTool

load_dotenv()


SYNTHESIZER_SYSTEM = """\
You design a DERIVED TOOL that wraps a primitive (the SOURCE TOOL) with a
fix that makes a recurring failure structurally impossible.

You will receive:
  - the source tool spec (name, description, JSON schema),
  - a cluster of LESSONS (text rules) distilled from repeated failures,
  - sample error text from those failures.

Design a derived tool with:
  - A short, action-oriented NAME (snake_case, ~2-4 words). It should read
    like a domain verb: pytest_run, project_build, deploy_release.
  - A DESCRIPTION (3-5 sentences) explaining what it does and what's been
    handled for the caller. Mention what the model no longer needs to think
    about (the rule that's been baked in).
  - A JSON SCHEMA for the derived tool's args. These should be a CLEANER,
    HIGHER-LEVEL surface than the source tool's args — e.g. the source has
    'command: str' but the derived might have 'test_path: str, verbose: bool'.
    The point is to encode the recurring fix into the schema's structure.
  - A WRAP TEMPLATE: how to construct the source tool's args from the
    derived tool's args. Format: a Python f-string-like template
    (uses {var} placeholders for derived args) for each source arg.
  - Optional CONDITIONAL RENDERS: for boolean derived args, define a
    snippet to inject when the flag is true vs false.

Output JSON ONLY (no markdown fence, no commentary):

{
  "name": "derived_tool_name",
  "description": "Short rich description ending with the baked-in fix.",
  "json_schema": {
    "type": "object",
    "properties": {
      "<arg>": {"type": "string", "description": "..."},
      ...
    },
    "required": ["<arg>"]
  },
  "source_tool": "bash",
  "wrap": {
    "<source_arg_name>": "<template with {derived_arg} placeholders, can reference conditional names>"
  },
  "conditionals": {
    "<placeholder_name>": {
      "if_arg": "<boolean_derived_arg>",
      "if_true": "<text inserted when true>",
      "if_false": "<text inserted when false (default '')>"
    }
  }
}

Example for 'pytest tests live in verify/' lessons:
{
  "name": "pytest_run",
  "description": "Run pytest in this project. The project's test directory (verify/) is handled for you — just pass the test file path relative to verify/.",
  "json_schema": {
    "type": "object",
    "properties": {
      "test_path": {"type": "string", "description": "Test file relative to verify/, e.g. 'test_auth.py'."},
      "verbose": {"type": "boolean"}
    },
    "required": ["test_path"]
  },
  "source_tool": "bash",
  "wrap": {
    "command": "pytest verify/{test_path}{verbose_flag}"
  },
  "conditionals": {
    "verbose_flag": {"if_arg": "verbose", "if_true": " -v", "if_false": ""}
  }
}

Be precise — the wrap template is the security boundary. Do not invoke
shell metacharacters that the source tool wouldn't naturally produce.
"""


@dataclass
class SynthesisResult:
    derived: DerivedTool | None
    error: str | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    raw: str = ""


def _build_wrap_fn(spec_wrap: dict, spec_conditionals: dict):
    """Build a safe wrap_fn from the structured spec — no eval."""

    def wrap_fn(derived_args: dict[str, Any]) -> dict[str, Any]:
        # Materialize conditional placeholders
        ctx = dict(derived_args)
        for name, cond in spec_conditionals.items():
            arg_val = derived_args.get(cond.get("if_arg"))
            ctx[name] = cond.get("if_true", "") if arg_val else cond.get("if_false", "")
        # Strip any leaked path prefixes the model accidentally included
        for k, v in list(ctx.items()):
            if isinstance(v, str):
                pass  # No path stripping in v1 — let LLM decide
        # Build source-args dict by formatting each template
        out: dict[str, Any] = {}
        for src_arg, template in spec_wrap.items():
            try:
                out[src_arg] = template.format(**ctx)
            except KeyError as e:
                # Missing placeholder — fall back to leaving template alone
                out[src_arg] = template
        return out

    return wrap_fn


def _strip_json(text: str) -> str:
    """Best-effort to pull a JSON object out of the model's response."""
    text = text.strip()
    if text.startswith("```"):
        # Strip markdown code fence
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return m.group(0)
    return text


def synthesize_from_cluster(
    cluster_lessons: list[Lesson],
    source_tool: Tool,
    model: str = "claude-sonnet-4-6",
) -> SynthesisResult:
    """Ask the LLM to design a derived tool from a cluster of recurring lessons."""
    if not cluster_lessons:
        return SynthesisResult(derived=None, error="empty cluster")

    # Build the prompt
    lesson_block = "\n".join(
        f"  - [{l.category}] {l.text}\n      (from error: {l.source_error[:150]})"
        for l in cluster_lessons
    )
    source_schema = json.dumps(source_tool.json_schema, indent=2)
    prompt = (
        f"# Source tool\n"
        f"name: {source_tool.name}\n"
        f"description: {source_tool.description}\n"
        f"json_schema:\n{source_schema}\n\n"
        f"# Recurring lessons ({len(cluster_lessons)} fires)\n"
        f"{lesson_block}\n\n"
        f"Design the derived tool. Output JSON only."
    )

    try:
        client = make_client(model)
        if hasattr(client, "max_tokens"):
            client.max_tokens = 1500
        client.reset(SYNTHESIZER_SYSTEM)
        client.add_user_text(prompt)
        msg = client.step([])
        text = msg.text
        in_tok = msg.usage.input_tokens
        out_tok = msg.usage.output_tokens
    except Exception as exc:  # noqa: BLE001
        return SynthesisResult(derived=None, error=f"api error: {exc!r}")

    cost = cost_for(model, in_tok, out_tok)

    # Parse the JSON
    raw_json = _strip_json(text)
    try:
        spec = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return SynthesisResult(
            derived=None,
            error=f"json parse error: {exc!r}",
            cost_usd=cost,
            input_tokens=in_tok,
            output_tokens=out_tok,
            raw=raw_json,
        )

    # Validate the spec
    try:
        derived_name = spec["name"]
        derived_description = spec["description"]
        derived_schema = spec["json_schema"]
        source_name = spec.get("source_tool", source_tool.name)
        wrap_map = spec["wrap"]
        conds = spec.get("conditionals", {})
    except KeyError as exc:
        return SynthesisResult(
            derived=None,
            error=f"missing key in spec: {exc!r}",
            cost_usd=cost,
            input_tokens=in_tok,
            output_tokens=out_tok,
            raw=raw_json,
        )

    # Build the Tool + wrap_fn
    tool = Tool(
        name=derived_name,
        toolbox=source_tool.toolbox,
        description=derived_description,
        json_schema=derived_schema,
    )
    wrap_fn = _build_wrap_fn(wrap_map, conds)
    derived = DerivedTool(
        tool=tool,
        source_tool_name=source_name,
        wrap_fn=wrap_fn,
    )
    return SynthesisResult(
        derived=derived,
        cost_usd=cost,
        input_tokens=in_tok,
        output_tokens=out_tok,
        raw=raw_json,
    )
