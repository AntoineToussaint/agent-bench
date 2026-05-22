| model | format | n | pass@1 | invalid_tool/turn | mean_tokens | mean_latency (s) |
|---|---|---:|---:|---:|---:|---:|
| claude-sonnet-4-6 | search_replace | 14 | 64.3% | 0.0% | 5,229 | 6.2 |
| claude-sonnet-4-6 | semantic | 14 | 42.9% | 5.3% | 4,389 | 4.8 |
| claude-sonnet-4-6 | unified_diff | 14 | 0.0% | 78.6% | 5,064 | 6.2 |

## Pass matrix

Each cell: pass-rate across formats for that (task, model).

| task | claude-sonnet-4-6 |
|---|---:|
| c01_localized_bug__medium | 67% |
| c02_multi_site__medium | 33% |
| c03_xfile_rename__medium | 33% |
| c04_signature_change__medium | 33% |
| c05_api_migration__medium | 0% |
| c06_extract_function__medium | 33% |
| c07_inline_function__medium | 67% |
| c08_add_feature__medium | 0% |
| c09_remove_sweep__medium | 0% |
| c10_repetitive_structure__medium | 67% |
| c11_type_changes__medium | 33% |
| c12_hygiene__medium | 33% |
| c13_test_work__medium | 67% |
| c14_config_code__medium | 33% |