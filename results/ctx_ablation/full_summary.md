| model | condition | n | pass@1 | invalid/turn | mean_tokens | mean_cost_usd | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| claude-haiku-4-5 | keep_everything | 3 | 100.0% | 4.0% | 30,601 | $0.0533 | 13.4 |
| claude-haiku-4-5 | sliding_window_5 | 3 | 100.0% | 3.0% | 38,399 | $0.0469 | 16.0 |
| claude-haiku-4-5 | tool_result_elision_2 | 3 | 100.0% | 4.3% | 25,184 | $0.0291 | 10.5 |

## Pass matrix

Each cell: pass-rate across conditions for that (task, model).

| task | claude-haiku-4-5 |
|---|---:|
| astropy__astropy-12907 | 100% |
| astropy__astropy-14182 | 100% |
| astropy__astropy-14365 | 100% |

