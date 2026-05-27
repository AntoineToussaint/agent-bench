| model | condition | n | pass@1 | invalid/turn | mean_tokens | mean_cost_usd | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| gpt-5-mini | edit | 2 | 100.0% | 0.0% | 6,036 | $0.0021 | 14.7 |
| gpt-5-mini | localize | 2 | 100.0% | 0.0% | 37,178 | $0.0112 | 27.4 |
| gpt-5-mini | select | 2 | 50.0% | 0.0% | 2,975 | $0.0012 | 4.7 |

## Pass matrix

Each cell: pass-rate across conditions for that (task, model).

| task | gpt-5-mini |
|---|---:|
| E1-stage-and-commit-typo | 0% |
| E2-draft-pr | 100% |
| astropy__astropy-12907 | 100% |
| astropy__astropy-14182 | 100% |
| c01_localized_bug__large | 100% |
| c01_localized_bug__medium | 100% |

## Failure modes

Each row is a (model, condition, mode) bucket with N=number of
failed trials in that bucket. See `lib/agent-eval-core/FAILURE_MODES.md`
for the taxonomy.

| model | condition | failure_mode | n |
|---|---|---|---:|
| gpt-5-mini | select | `missing_required_call` | 1 |
