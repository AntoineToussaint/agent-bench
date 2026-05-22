# Agent location: the structural variable behind tool-surface choices

## The point

When you benchmark an LLM-driven agent against a sandboxed task (Docker container, ephemeral VM, etc.), one structural choice dominates everything downstream: **does the agent code run inside or outside the sandbox?**

This isn't a tool-design question — it's an architecture question — and it determines what your measurement actually measures.

## Two cases

```
┌────────────────────────────────────────────────────────────────────┐
│ A. Agent INSIDE the sandbox                                        │
│                                                                    │
│   ┌─────────────────────────┐         ┌────────────────────────┐   │
│   │  Sandbox (Docker, VM)   │         │  Provider API          │   │
│   │  ┌──────────────────┐   │         │  (Anthropic, OpenAI)   │   │
│   │  │ agent loop       │←──┼─────────│                        │   │
│   │  │ + real bash      │   │   API   │                        │   │
│   │  │ + real fs        │──→│         │                        │   │
│   │  │ + real pytest    │   │         │                        │   │
│   │  └──────────────────┘   │         │                        │   │
│   └─────────────────────────┘         └────────────────────────┘   │
│                                                                    │
│   Translation layer:  none — agent has native access               │
│   Measurement isolates:  (LLM capability × agent design)           │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ B. Agent OUTSIDE the sandbox                                       │
│                                                                    │
│   ┌─────────────────┐    ┌──────────┐    ┌────────────────────┐    │
│   │ agent (your    │    │ harness  │    │ Sandbox            │    │
│   │ code, your     │←──→│ translates│←──→│ (Docker, VM)       │    │
│   │ tool schema)   │    │ tool→exec │    │                    │    │
│   └─────────────────┘    └──────────┘    └────────────────────┘    │
│         ↑                                                          │
│       API ↕                                                        │
│   ┌─────────────────┐                                              │
│   │ Provider API    │                                              │
│   └─────────────────┘                                              │
│                                                                    │
│   Translation layer:  every action: tool_call → docker exec        │
│                       → tool_result → next tool_call               │
│   Measurement entangles:  (LLM × agent tool surface × translation) │
└────────────────────────────────────────────────────────────────────┘
```

## What you actually measure in each

**Inside.** The LLM is just the brain. The agent code uses real shell, real file ops, real test runners. Loop overhead is one API round-trip per decision. Tool semantics are whatever bash already gives you. There's no "tool surface" the model has to learn — it can use real Unix.

**Outside.** Every action gets serialized into a tool call your code understands, then translated into a Docker exec, then back. The model's tool-use behavior (the [single-call ceiling we measured](tool-use-vs-structured-output.md), the catalog-bloat effect we and `tool-selection` saw) is in scope. The shape of the translation layer becomes a confound for any number you report.

## What we've measured so far

`coding-tool` and `tool-selection` both held **agent location = outside**, varied the tool surface shape:
- single tool_use → +43pp gap to structured JSON output (`coding-tool`)
- one-phase tool catalog → 4× cost vs two-phase at 150 tools (`tool-selection`)

Those are real findings about the *translation layer* — about what you pay for keeping the agent outside.

## What we haven't measured

The agent-inside-vs-outside cross-tab, on the same task and same model. As far as we can find, **no benchmark has published this**. Everyone reports a single number under their specific apparatus.

## Why this matters now

The field is converging on **agents that run inside containers natively**. As of mid-2026:

- **Claude Code** has first-class devcontainer.json support; the CLI runs in a container with full bash + fs access.
- **OpenHands** runs in containers by default; the agent loop lives in the sandbox.
- **Cline**, **Aider**, **Goose**, **Cursor's remote agents**, **SWE-Agent**: all support running the agent loop inside a container.
- **Modal**, **e2b**, **Daytona**: provide infrastructure specifically for shipping agents into sandboxes.

The capability is converging. The benchmarks haven't caught up — most are still architected as "outside the box, with translation."

## What a clean experiment would look like

A future `experiments/agent-location/` could measure:

1. Pick a task suite (Terminal-Bench, SWE-Bench, or a custom set).
2. Fix the model (Sonnet 4.6 or Opus 4.7).
3. Run each task in two configurations:
   - **Outside**: hosted LLM ↔ `agent-eval-core`-style harness ↔ Docker exec
   - **Inside**: hosted LLM ↔ tiny agent loop running *inside* the same Docker image, with native bash
4. Report pass rate, token cost, turns, latency per configuration.

Hypothesis: the inside-agent configuration wins by a large margin (probably similar order to the 43pp structured-output uplift we already measured), AND it converges across models because the translation-layer noise is removed.

If true, the actionable conclusion for the field is concrete: **stop building benchmarks where the agent lives outside the sandbox.** It's the wrong shape now that providers/frameworks all support running inside.

## Connection to existing findings

This is the *third* axis of the same diagnosis we keep finding:

| axis | failure of canonical pattern | workaround |
|---|---|---|
| **Many tools** | catalog bloat, cache invalidation, accuracy degrades past ~40 tools | two-phase selection (`tool-selection`) |
| **Multi-step plans** | single-call ceiling, model emits ~1 op per response | structured-text output (`coding-tool`) |
| **Sandboxed execution** | translation layer between agent + environment confounds measurement | agent inside the sandbox |

Each one says: **the convenience defaults of the canonical agent stack are wrong in a specific predictable way at production scale, and the fix is to bypass the canonical pattern in that specific way.** None of them require new model capabilities — they all change the apparatus around the model.
