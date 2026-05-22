| model | format | n | pass@1 | invalid_tool/turn | mean_tokens | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|
| claude-sonnet-4-6 | search_replace | 14 | 92.9% | 0.0% | 1,341 | 4.8 |
| claude-sonnet-4-6 | semantic | 14 | 42.9% | 6.9% | 867 | 4.3 |
| claude-sonnet-4-6 | unified_diff | 14 | 14.3% | 50.0% | 1,166 | 5.0 |

## Pass matrix

Each cell: pass-rate across formats for that (task, model).

| task | claude-sonnet-4-6 |
|---|---:|
| c01_localized_bug__small | 100% |
| c02_multi_site__small | 67% |
| c03_xfile_rename__small | 67% |
| c04_signature_change__small | 67% |
| c05_api_migration__small | 0% |
| c06_extract_function__small | 67% |
| c07_inline_function__small | 33% |
| c08_add_feature__small | 33% |
| c09_remove_sweep__small | 33% |
| c10_repetitive_structure__small | 67% |
| c11_type_changes__small | 33% |
| c12_hygiene__small | 33% |
| c13_test_work__small | 67% |
| c14_config_code__small | 33% |