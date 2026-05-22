| model | format | n | pass@1 | invalid_tool/turn | mean_tokens | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|
| claude-sonnet-4-6 | search_replace | 14 | 57.1% | 0.0% | 5,425 | 6.7 |
| claude-sonnet-4-6 | semantic | 14 | 42.9% | 4.8% | 4,434 | 5.5 |

## Pass matrix

Each cell: pass-rate across formats for that (task, model).

| task | claude-sonnet-4-6 |
|---|---:|
| c01_localized_bug__medium | 100% |
| c02_multi_site__medium | 0% |
| c03_xfile_rename__medium | 50% |
| c04_signature_change__medium | 50% |
| c05_api_migration__medium | 0% |
| c06_extract_function__medium | 50% |
| c07_inline_function__medium | 50% |
| c08_add_feature__medium | 0% |
| c09_remove_sweep__medium | 0% |
| c10_repetitive_structure__medium | 100% |
| c11_type_changes__medium | 100% |
| c12_hygiene__medium | 50% |
| c13_test_work__medium | 100% |
| c14_config_code__medium | 50% |