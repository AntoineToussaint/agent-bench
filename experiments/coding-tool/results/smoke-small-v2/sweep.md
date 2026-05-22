| model | format | n | pass@1 | invalid_tool/turn | mean_tokens | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|
| claude-haiku-4-5 | search_replace | 14 | 50.0% | 0.0% | 1,864 | 2.4 |
| claude-haiku-4-5 | semantic | 14 | 50.0% | 14.6% | 2,893 | 2.8 |
| claude-haiku-4-5 | unified_diff | 14 | 21.4% | 50.0% | 1,794 | 2.8 |

## Pass matrix

Each cell: pass-rate across formats for that (task, model).

| task | claude-haiku-4-5 |
|---|---:|
| c01_localized_bug__small | 100% |
| c02_multi_site__small | 67% |
| c03_xfile_rename__small | 33% |
| c04_signature_change__small | 0% |
| c05_api_migration__small | 0% |
| c06_extract_function__small | 0% |
| c07_inline_function__small | 33% |
| c08_add_feature__small | 33% |
| c09_remove_sweep__small | 0% |
| c10_repetitive_structure__small | 100% |
| c11_type_changes__small | 33% |
| c12_hygiene__small | 33% |
| c13_test_work__small | 100% |
| c14_config_code__small | 33% |