# Capability scorecard — claude-haiku-4-5

N=2 tasks per experiment. Smoke run, not a benchmark.
Each experiment uses its default backend from `data/model_backends.yaml`.

Step-level columns (only for turn-loop trials):
- **wasted%**: fraction of turns that didn't make progress (re-tried same call, or all calls errored)
- **batch**: mean actions per active turn — higher = better batching, lower = chatty

| capability             |  n | pass | cost     | latency | wasted% | batch |
|---|---:|---:|---:|---:|---:|---:|
| find  (localize)       | 2 |  100% | $0.0360 |  15.7s |    8% |  1.3 |
| plan  (tool-use)       | 2 |  100% | $0.0011 |   1.4s | — | — |
| edit  (code)           | 2 |  100% | $0.0144 |   5.5s |    0% |  1.0 |

Reproduce per-experiment with the experiment's own sweep script.
