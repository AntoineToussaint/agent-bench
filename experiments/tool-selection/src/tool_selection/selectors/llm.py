"""LLM-as-selector: ask a small model to rank candidates by relevance.

The model is shown the user's task + a numbered list of candidate
(name, description) entries and asked to return a JSON list of the top-k
names. We do NOT use tool calling for this — we use structured text output
with retry-on-parse-error. Cheaper, easier to debug, and the candidate set
is small enough to fit easily in input.
"""

from __future__ import annotations

import json
import os
import re
import time

from dotenv import load_dotenv

from tool_selection.pricing import cost_for
from tool_selection.types import PipelineStep

from .base import Selectable, Selection, Selector

load_dotenv()


def _build_prompt(query: str, candidates: list[Selectable], k: int) -> str:
    lines = [
        "You are routing a user request to a small set of tools or tool groups.",
        f"Pick the {k} most relevant candidates for the user's task.",
        "Return ONLY a JSON array of candidate names, ordered from most to least",
        "relevant. No commentary, no markdown. Example: [\"name_a\", \"name_b\"]",
        "",
        "# User task",
        query,
        "",
        "# Candidates",
    ]
    for i, c in enumerate(candidates):
        lines.append(f"{i + 1}. {c.name} — {c.description}")
    lines.append("")
    lines.append(f"Top-{k} JSON array:")
    return "\n".join(lines)


def _parse_response(text: str, valid_names: set[str], k: int) -> list[str]:
    """Pull a JSON array of names out of the model's text and filter to valid ones."""
    text = text.strip()
    # Try direct parse first
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*?\]", text, re.DOTALL)
        if not m:
            return []
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(parsed, list):
        return []
    seen: list[str] = []
    for x in parsed:
        if isinstance(x, str) and x in valid_names and x not in seen:
            seen.append(x)
        if len(seen) >= k:
            break
    return seen


class LLMSelector(Selector):
    def __init__(self, model: str):
        self.model = model
        if model.startswith("claude"):
            self.id = f"llm-{'haiku' if 'haiku' in model else 'sonnet' if 'sonnet' in model else 'opus'}"
        elif model.startswith("gpt"):
            self.id = f"llm-{'gpt-mini' if 'mini' in model else 'gpt'}"
        else:
            self.id = f"llm-{model}"

    def select(self, query: str, candidates: list[Selectable], k: int) -> Selection:
        prompt = _build_prompt(query, candidates, k)
        valid = {c.name for c in candidates}
        t0 = time.perf_counter()

        if self.model.startswith("claude"):
            import anthropic

            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            resp = client.messages.create(
                model=self.model,
                max_tokens=512,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            inp_tok = resp.usage.input_tokens
            out_tok = resp.usage.output_tokens
        else:
            from openai import OpenAI

            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            resp = client.chat.completions.create(
                model=self.model,
                max_completion_tokens=512,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.choices[0].message.content or ""
            inp_tok = resp.usage.prompt_tokens
            out_tok = resp.usage.completion_tokens

        latency_ms = (time.perf_counter() - t0) * 1000
        ids = _parse_response(text, valid, k)

        return Selection(
            selected_ids=ids,
            scores=[],
            steps=[
                PipelineStep(
                    kind="llm_router",
                    model=self.model,
                    input_tokens=inp_tok,
                    output_tokens=out_tok,
                    cost_usd=cost_for(self.model, inp_tok, out_tok),
                    latency_ms=latency_ms,
                    note=f"selected {len(ids)}/{len(candidates)} (asked for {k})",
                )
            ],
        )
