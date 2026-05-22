| model | format | n | pass@1 | invalid_tool/turn | mean_tokens | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|
| claude-haiku-4-5 | ast_python | 3 | 100.0% | 0.0% | 8,023 | 7.1 |
| claude-haiku-4-5 | search_replace | 5 | 100.0% | 0.0% | 9,019 | 6.8 |
| claude-haiku-4-5 | semantic_ops | 4 | 100.0% | 0.0% | 10,932 | 7.1 |
| claude-haiku-4-5 | unified_diff | 4 | 100.0% | 17.9% | 11,082 | 7.8 |
| gpt-5-mini | ast_python | 3 | 100.0% | 0.0% | 5,871 | 10.1 |
| gpt-5-mini | search_replace | 5 | 100.0% | 2.5% | 10,102 | 23.4 |
| gpt-5-mini | semantic_ops | 5 | 100.0% | 4.9% | 15,957 | 53.1 |
| gpt-5-mini | unified_diff | 2 | 0.0% | 0.0% | 17,312 | 20.2 |

## Pass matrix

Each cell: pass-rate across formats for that (task, model).

| task | claude-haiku-4-5 | gpt-5-mini |
|---|---:|---:|
| add-parameter-001 | 100% | 100% |
| bug-fix-comparison-001 | 100% | 75% |
| move-function-001 | 100% | 100% |
| rename-helper-001 | 100% | 100% |
| repetitive-structure-001 | 100% | 75% |