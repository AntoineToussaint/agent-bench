| model | condition | n | pass@1 | invalid/turn | mean_tokens | mean_cost_usd | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| claude-haiku-4-5 | one-shot | 5 | 80.0% | 0.0% | 1,988 | $0.0067 | 8.1 |
| claude-haiku-4-5 | turn-loop | 5 | 100.0% | 2.4% | 19,515 | $0.0441 | 12.5 |
| claude-haiku-4-5 | turn-loop-schema | 5 | 100.0% | 1.4% | 32,561 | $0.0683 | 18.9 |
| claude-haiku-4-5 | turn-loop-structured | 5 | 80.0% | 578.6% | 8,507 | $0.0179 | 11.3 |
| claude-sonnet-4-6 | one-shot | 5 | 100.0% | 0.0% | 815 | $0.0026 | 2.2 |
| claude-sonnet-4-6 | turn-loop | 5 | 100.0% | 0.0% | 6,532 | $0.0441 | 11.6 |
| claude-sonnet-4-6 | turn-loop-schema | 5 | 80.0% | 0.0% | 5,341 | $0.0405 | 12.1 |
| claude-sonnet-4-6 | turn-loop-structured | 5 | 100.0% | 0.0% | 3,707 | $0.0265 | 11.4 |

## Pass matrix

Each cell: pass-rate across conditions for that (task, model).

| task | claude-haiku-4-5 | claude-sonnet-4-6 |
|---|---:|---:|
| astropy__astropy-12907 | 100% | 75% |
| astropy__astropy-14182 | 100% | 100% |
| astropy__astropy-14365 | 100% | 100% |
| astropy__astropy-14995 | 50% | 100% |
| astropy__astropy-6938 | 100% | 100% |
