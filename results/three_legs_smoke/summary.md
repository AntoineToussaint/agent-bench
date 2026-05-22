| model | condition | n | pass@1 | invalid/turn | mean_tokens | mean_cost_usd | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| claude-haiku-4-5 | claude-code | 1 | 100.0% | 0.0% | 0 | $0.0000 | 20.6 |
| claude-haiku-4-5 | one-shot | 1 | 100.0% | 0.0% | 604 | $0.0008 | 1.8 |
| claude-haiku-4-5 | turn-loop | 1 | 100.0% | 0.0% | 35,236 | $0.0768 | 21.5 |

## Pass matrix

Each cell: pass-rate across conditions for that (task, model).

| task | claude-haiku-4-5 |
|---|---:|
| astropy__astropy-12907 | 100% |
