| model | format | n | pass@1 | invalid_tool/turn | mean_tokens | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|
| claude-opus-4-7 | search_plus | 14 | 92.9% | 0.0% | 7,286 | 9.0 |

## Pass matrix

Each cell: pass-rate across formats for that (task, model).

| task | claude-opus-4-7 |
|---|---:|
| c01_localized_bug__medium | 100% |
| c02_multi_site__medium | 100% |
| c03_xfile_rename__medium | 100% |
| c04_signature_change__medium | 100% |
| c05_api_migration__medium | 100% |
| c06_extract_function__medium | 100% |
| c07_inline_function__medium | 100% |
| c08_add_feature__medium | 100% |
| c09_remove_sweep__medium | 0% |
| c10_repetitive_structure__medium | 100% |
| c11_type_changes__medium | 100% |
| c12_hygiene__medium | 100% |
| c13_test_work__medium | 100% |
| c14_config_code__medium | 100% |