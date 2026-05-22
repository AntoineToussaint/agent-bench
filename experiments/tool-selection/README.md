# tool-selection

**What is the most efficient way to get to one-shot correctness in tool calls?**

We measure the Pareto frontier of (one-shot correctness × pipeline cost × latency) across tool-surfacing strategies, using a benchmark of ~30 hand-authored tasks over 3 toolboxes (`filesystem`, `git`, `github`) in two tool granularities (narrow vs fat).

## What "one shot" means

The model gets **one assistant turn** to emit the full succession of tool calls needed to complete the task. We do not run an agent loop and do not actually execute the tools — we inspect the response structurally:
- did the required calls appear?
- with the right key arguments?
- with schemas that parse?
- without hallucinating tools that weren't surfaced?

The surfacing pipeline that leads up to that final shot **can** be multiple inner steps (an LLM router that picks toolboxes, an embedding lookup that picks tools), and those steps count toward the pipeline's cost and latency budget. We want to know where the tokens are best spent.

## Approaches

| ID | Inner pipeline | Final shot sees |
|---|---|---|
| `full` | (none) | All tools across all toolboxes |
| `toolbox_llm` | Small LLM picks toolboxes from descriptions | Tools in selected toolboxes |
| `toolbox_embed` | Embedding similarity vs toolbox descriptions | Tools in top-k toolboxes |
| `tool_embed` | Embedding similarity vs tool descriptions | Top-k tools directly |

Each runs in both `narrow` and `fat` granularities × multiple final-shot models (Haiku 4.5, Sonnet 4.6, gpt-5.4-mini).

## Quickstart

```bash
cp .env.example .env   # ANTHROPIC_API_KEY, OPENAI_API_KEY
uv sync
uv run python scripts/shakedown.py   # smoke test
uv run python scripts/run.py         # full sweep
uv run marimo edit notebooks/01_report.py
```

Budget-capped via `EXPERIMENT_BUDGET_USD` in `.env`.
