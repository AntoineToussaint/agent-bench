| model | condition | n | pass@1 | invalid/turn | mean_tokens | mean_cost_usd | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| gemini-2.5-flash | edit | 2 | 100.0% | 0.0% | 8,598 | $0.0042 | 3.2 |
| gemini-2.5-flash | localize | 2 | 100.0% | 0.0% | 19,904 | $0.0080 | 10.0 |
| gemini-2.5-flash | select | 2 | 50.0% | 0.0% | 3,926 | $0.0013 | 1.3 |

## Pass matrix

Each cell: pass-rate across conditions for that (task, model).

| task | gemini-2.5-flash |
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
| gemini-2.5-flash | select | `missing_required_call` | 1 |
