# What is the most efficient way to get to one-shot correctness in tool calls?

*An empirical study of selection strategies, schema granularity, and final-shot phase design across Claude Haiku 4.5 and Sonnet 4.6.*

---

## 1 · The question

LLM agentic systems lose reliability as the tool catalog grows and as the action sequence required by a task lengthens. We isolate **one-shot tool calling** — given a user task and a final-shot model, can the model emit the full correct succession of tool calls (with correct arguments) in a single assistant response?

We compare different ways to spend tokens en route to that one shot:
- **Tool surfacing** — full catalog vs filtered (BM25 / embeddings / small-LLM router / hybrid pipelines)
- **Granularity** — narrow (40 small tools) vs fat (12 wide tools with action enums)
- **Phase design** — vanilla 1-phase vs plan-first prompt vs 2-phase (selection then args)
- **Final-shot model** — Haiku 4.5 vs Sonnet 4.6

All metrics are reported on the Pareto plane of **(one-shot correctness × pipeline cost × latency)**.

## 2 · Benchmark

- **3 toolboxes**: filesystem, git, github. Two granularity variants of each (narrow / fat).
- **16 hand-authored tasks** spanning research-grounded failure modes:
  - 5 easy (1-3 calls), 8 medium (4-7 calls), 3 large (8+ calls)
  - Failure-mode coverage: confusable siblings (TRAJECT-Bench), phantom tools (Phantom-Tool blog), long sequences (KAMI / Microsoft Lost-in-Multi-Turn), argument coupling (Composio 2026), wrong-order temptation, state confusion (BFCL v3), parallel-similar batching.
- **Scoring**: structural — required tool calls present with right key arguments, no hallucinated/forbidden tools, schemas validate. Selection and args accuracy reported separately.

## 3 · Strategies and phases tested

**Surfacing strategies** (subset of the full registry — the rest were dominated in a prior sweep):
- `full` — all tools in catalog surfaced (39 narrow / 12 fat)
- `tool:llm-haiku` — Haiku LLM-as-retriever picks top-10 tools per task
- `hybrid:embed-openai-small+llm-haiku` — embedding shortlist (k=20) then LLM rerank (k=10)

**Phases**:
- `1phase` — original behavior: surfaced tools in system prompt, model emits all tool_use in one response
- `1phase-plan` — same call, but prompt requires a `<plan>` block listing every tool call before emitting them. Hypothesis: targets the "stopped mid-plan" failure documented in KAMI and Lost-in-Multi-Turn (~25-point drop)
- `2phase` (smoke-tested, not in main sweep) — phase 1 picks (name, intent) sequence; phase 2 fills args one tool at a time. Found dominated by `1phase-plan` on Haiku.

## 4 · Headline findings

*[Populated after sweep completes]*

## 5 · Pareto frontiers

*[Populated after sweep completes]*

### 5.1 · Haiku × narrow
### 5.2 · Haiku × fat
### 5.3 · Sonnet × narrow
### 5.4 · Sonnet × fat

## 6 · Per-failure-mode breakdown

*[Populated after sweep completes]*

| Failure mode | Tasks | Vanilla 1phase | Plan-first | What recovers it |
|---|---|---|---|---|
| Confusable siblings | E4, M3, H2 | | | |
| Phantom tool | E5 | | | |
| Long sequence (>5 calls) | M1, M2, H1 | | | |
| Argument coupling | M5, H3 | | | |
| Wrong-order temptation | M6 | | | |
| State confusion | M7 | | | |
| Parallel-similar | M8 | | | |

## 7 · Verdict

*[Populated after sweep completes]*

The bottom line we'll present in plain English: **For each (model × granularity), which (strategy, phase) combination should production agentic systems use?**

## 8 · Threats to validity

- **Single replicate per condition.** Temp=0 reduces variance but model providers have residual non-determinism (the prior caching study measured CV up to 40% on OpenAI). Numbers should be considered ±2-3 pp.
- **Synthetic catalog.** 3 toolboxes / 40 tools is smaller than many production setups. Hallucination rates (~33% past 50 tools per Phantom-Tool blog) are not stressed here.
- **Task author bias.** All 16 tasks hand-authored by the study designer; failure-mode coverage tags are post-hoc.
- **Two final-shot models.** Generalization to GPT-5.4 family, Gemini, open-weights not measured.
- **Hot path not measured.** Real production systems benefit from prompt caching (the prior caching study found 86% cost reduction) — we deliberately measure cold-cache costs here for clean isolation.

## 9 · Reproducing

```bash
git clone <repo>
cp .env.example .env  # ANTHROPIC_API_KEY, OPENAI_API_KEY
uv sync
uv run python scripts/run_sweep.py \
  --strategy full --strategy tool:llm-haiku \
  --strategy hybrid:embed-openai-small+llm-haiku \
  --phase 1phase --phase 1phase-plan \
  --model claude-haiku-4-5 \
  --out data/runs/sweep_v2_haiku.jsonl
uv run python scripts/run_sweep.py \
  --strategy full --strategy tool:llm-haiku \
  --strategy hybrid:embed-openai-small+llm-haiku \
  --phase 1phase --phase 1phase-plan \
  --model claude-sonnet-4-6 \
  --out data/runs/sweep_v2_sonnet.jsonl
uv run python scripts/thesis.py
```
