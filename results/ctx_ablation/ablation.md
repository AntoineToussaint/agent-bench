# Context-policy ablation — claude-haiku-4-5

N=3 tasks × 3 policies = 9 trials.
Same tasks, same model, same backend — only the context policy varies.

| policy | pass | mean cost | peak in p50 | cache% | wasted% | failure modes |
|---|---:|---:|---:|---:|---:|---|
| `keep_everything` | 100% | $0.0533 | 8,256 | 30% | 6% | — |
| `tool_result_elision_2` | 100% | $0.0291 | 6,158 | 15% | 5% | — |
| `sliding_window_5` | 100% | $0.0469 | 8,195 | 54% | 6% | — |
