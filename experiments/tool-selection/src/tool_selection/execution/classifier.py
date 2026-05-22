"""Failure classifier: turns (call, error, task) into a Lesson via a small LLM call.

Cheap by design (Haiku, max 200 output tokens). Output is constrained to a
single short rule + a scope indicator (tool / task).
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any

from dotenv import load_dotenv

from .lessons import Lesson, task_signature

load_dotenv()


CLASSIFIER_SYSTEM = """\
You are a failure-pattern extractor. Given:
  - the user's task,
  - the agent's failed tool call,
  - the resulting error message,

produce a SHORT, ACTIONABLE rule the agent should follow next time to avoid
the same failure. The rule should be 1-2 sentences and start with a verb.

Decide the scope. STRONGLY DEFAULT to "tool":
  - "tool"  WHENEVER the fix is about HOW to use a specific tool — its args,
            allowed values, required preconditions, common composition
            mistakes. This is by far the most common case. Examples:
              * 'When calling git_push for the first time on a new branch,
                 set set_upstream=True.'
              * 'When using bash to run pytest, prefix the test path with
                 verify/ (this project's test directory).'
  - "task"  ONLY when the rule is genuinely about TASK COMPOSITION across
            multiple different tools, with no actionable per-tool component.
            Such rules are rare — most "task" candidates are actually "tool"
            rules in disguise (the model just isn't using the right args).

Reply with ONLY a JSON object:
{
  "rule": "<one-or-two-sentence actionable rule>",
  "scope": "tool" | "task"
}
"""


def _call_classifier(prompt: str, model: str = "claude-haiku-4-5") -> tuple[dict, dict]:
    """Returns (parsed_json, telemetry)."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    t0 = time.perf_counter()
    resp = client.messages.create(
        model=model,
        max_tokens=200,
        temperature=0,
        system=CLASSIFIER_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    latency_ms = (time.perf_counter() - t0) * 1000

    # Parse the JSON, with fallback
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        m = re.search(r"\{.*?\}", text, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = {"rule": text.strip()[:200], "scope": "tool"}
        else:
            parsed = {"rule": text.strip()[:200], "scope": "tool"}

    return parsed, {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "latency_ms": latency_ms,
    }


def classify_failure(
    task,
    call_tool: str,
    call_args: dict,
    error_message: str,
    category: str,
    model: str = "claude-haiku-4-5",
) -> tuple[Lesson, dict]:
    """Generate a Lesson from a single failure.

    Returns (lesson, telemetry). Telemetry includes input_tokens, output_tokens,
    latency_ms so the caller can roll up classifier cost into the experiment
    accounting.
    """
    prompt = (
        f"# Task\n{task.prompt[:500]}\n\n"
        f"# Failed call\n"
        f"  tool: {call_tool}\n"
        f"  args: {json.dumps({k: v for k, v in call_args.items() if v is not None})[:500]}\n\n"
        f"# Error\n{error_message[:500]}\n\n"
        f"# Category\n{category}\n\n"
        f"What's the rule? Reply with the JSON object."
    )

    parsed, telem = _call_classifier(prompt, model=model)
    scope = parsed.get("scope", "tool")
    if scope not in ("tool", "task"):
        scope = "tool"

    key = call_tool if scope == "tool" else task_signature(task)
    rule = parsed.get("rule", "").strip()
    if not rule:
        rule = f"Avoid this error pattern when calling {call_tool}."

    lesson = Lesson(
        id=f"lesson-{uuid.uuid4().hex[:8]}",
        text=rule,
        category=category,
        scope=scope,
        key=key,
        source_error=error_message[:200],
    )
    return lesson, telem
