| model | condition | n | pass@1 | invalid/turn | mean_tokens | mean_cost_usd | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| claude-haiku-4-5 | edit | 2 | 100.0% | 0.0% | 8,775 | $0.0144 | 5.5 |
| claude-haiku-4-5 | localize | 2 | 100.0% | 5.6% | 18,394 | $0.0360 | 15.7 |
| claude-haiku-4-5 | select | 2 | 100.0% | 0.0% | 571 | $0.0011 | 1.4 |

## Pass matrix

Each cell: pass-rate across conditions for that (task, model).

| task | claude-haiku-4-5 |
|---|---:|
| E1-stage-and-commit-typo | 100% |
| E2-draft-pr | 100% |
| astropy__astropy-12907 | 100% |
| astropy__astropy-14182 | 100% |
| c01_localized_bug__large | 100% |
| c01_localized_bug__medium | 100% |

