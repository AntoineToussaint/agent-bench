| model | condition | n | pass@1 | invalid/turn | mean_tokens | mean_cost_usd | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| claude-haiku-4-5 | claude-code | 5 | 100.0% | 0.0% | 0 | $0.0000 | 16.9 |
| claude-haiku-4-5 | one-shot | 5 | 60.0% | 0.0% | 740 | $0.0010 | 1.2 |
| claude-haiku-4-5 | turn-loop | 5 | 40.0% | 0.0% | 32,439 | $0.0662 | 21.8 |

## Pass matrix

Each cell: pass-rate across conditions for that (task, model).

| task | claude-haiku-4-5 |
|---|---:|
| astropy__astropy-12907 | 67% |
| astropy__astropy-14182 | 100% |
| astropy__astropy-14365 | 100% |
| astropy__astropy-14995 | 33% |
| astropy__astropy-6938 | 33% |
