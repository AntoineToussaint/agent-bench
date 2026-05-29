# Data sources

Provenance for the data files committed here. All are **derived, slim CSVs** —
we do not commit raw upstream archives (fetch them with the scripts instead).

## `swebench_verified_enrichment.csv`

Per-instance enrichment for the SWE-bench Verified 500, keyed on `instance_id`.
Built by `experiments/file-localization/scripts/build_verified_enrichment.py`
(re-run to refresh). 500 rows, ~70 KB.

Columns:
- `difficulty` — human time-to-fix bucket (`<15 min fix`, `15 min - 1 hour`,
  `1-4 hours`, `>4 hours`).
- `underspecified`, `false_negative`, `other_major_issues` — OpenAI ensembled
  annotation severities (0–3; ≥2 = severe). Use to drop contaminated/contested
  tasks (`file_localization.difficulty.is_clean`).
- `ref_solve_rate` — fraction of the 4 reference models that resolved it.
- `ref_cost_avg` — mean $/instance across the 4 reference models.
- `cost_*`, `calls_*`, `resolved_*` — per reference model (gpt5, gpt5_mini,
  sonnet4, sonnet45), from the mini-SWE-agent scaffold runs.

Upstream (no license declared by either; we commit only derived factual
columns — no annotator notes / ids / timestamps):
- Difficulty + quality flags: OpenAI SWE-bench Verified annotation release —
  `https://cdn.openai.com/introducing-swe-bench-verified/swe-bench-annotation-results.zip`
  (`ensembled_annotations_public.csv`).
- Per-instance cost/calls: swebench.com leaderboard data —
  `https://raw.githubusercontent.com/swe-bench/swe-bench.github.io/master/data/info_for_leaderboard.json`.

What is NOT available upstream and therefore absent here: per-instance
**latency / wall-clock** and **token counts** (no public SWE-bench source
exposes them).

## `swebench_*_difficulty.csv` (if present)

Per-instance leaderboard pass-rate (solver difficulty), built by
`experiments/file-localization/scripts/swebench_difficulty.py` from
`github.com/swe-bench/experiments`. Columns: `instance_id, repo, n_solved,
n_total, pass_rate`. Distinct from the `ref_solve_rate` above (that's only the
4 reference models; this is the whole leaderboard).
