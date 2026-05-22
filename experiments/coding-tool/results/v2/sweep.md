| model | format | n | pass@1 | invalid_tool/turn | mean_tokens | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|
| claude-haiku-4-5 | ast_python | 5 | 60.0% | 5.8% | 28,206 | 28.2 |
| claude-haiku-4-5 | search_replace | 5 | 100.0% | 0.0% | 8,672 | 6.8 |
| claude-haiku-4-5 | semantic_ops | 5 | 100.0% | 7.3% | 18,974 | 19.2 |
| claude-haiku-4-5 | unified_diff | 5 | 100.0% | 16.7% | 15,870 | 12.7 |
| gpt-5-mini | ast_python | 5 | 60.0% | 8.9% | 25,989 | 81.1 |
| gpt-5-mini | search_replace | 5 | 100.0% | 0.0% | 9,917 | 19.1 |
| gpt-5-mini | semantic_ops | 5 | 100.0% | 7.5% | 13,460 | 24.8 |
| gpt-5-mini | unified_diff | 5 | 20.0% | 2.4% | 29,904 | 50.9 |

## Pass matrix

Each cell: pass-rate across formats for that (task, model).

| task | claude-haiku-4-5 | gpt-5-mini |
|---|---:|---:|
| add-parameter-001 | 100% | 75% |
| bug-fix-comparison-001 | 100% | 75% |
| move-function-001 | 75% | 50% |
| rename-helper-001 | 75% | 50% |
| repetitive-structure-001 | 100% | 100% |