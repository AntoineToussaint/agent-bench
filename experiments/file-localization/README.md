# file-localization

File-localization benchmark for code retrievers, using **SWE-bench gold patches as ground truth**.

For each task: feed the issue text to a retriever, get a ranked list of files, score against the set of files the gold patch actually modifies. Reports `recall@k` and `NDCG@k` separately for *edit* files and *test* files, since gold patches usually include both.

Motivation: most code-retrieval benchmarks are LLM-generated and LLM-judged (e.g. semble's own benchmark) or function-level snippet pools (e.g. CoIR). Neither matches the workflow that actually matters for coding agents: *given a real issue, find the files you need to edit in a real repository.* File-level localization on SWE-bench Verified / Lite / Pro is exactly that workflow, and several papers (Agentless, Moatless, RepoGraph) show it's a hard ceiling on agent performance — if you don't find the file, you can't fix the bug.

## Install

```bash
uv sync                       # ripgrep + BM25 retrievers
uv sync --extra semble        # also installs semble from GitHub
uv sync --extra embeddings    # adds sentence-transformers (for custom dense retrievers)
```

`ripgrep` retriever needs `rg` on `$PATH`.

## Usage

Four input modes, all dispatched from the same CLI:

```bash
# 1. HuggingFace SWE-bench (aliases: verified | lite | full | multimodal | pro)
uv run file-localization --retriever bm25 --dataset lite --filter-repo psf/requests

# 2. Local JSONL file (one Task object per line)
uv run file-localization --retriever bm25 --dataset ./my_tasks.jsonl

# 3. Local directory of task subfolders (meta.json + gold.patch [+ test.patch])
uv run file-localization --retriever bm25 --dataset ./tasks_dir/

# 4. Ad-hoc single task from a patch file
uv run file-localization --retriever bm25 \
  --patch ./fix.patch \
  --query "fix off-by-one in pagination" \
  --repo-path ~/code/myrepo
```

### Task schema

JSONL line / JSON object / `meta.json` fields:

| field | required | note |
|---|---|---|
| `problem_statement` | yes | the query (issue text, NL question, etc.) |
| `patch` | yes | unified diff used to extract gold files |
| `repo` *or* `repo_path` | yes | GitHub `owner/name` (will be cloned) OR a local path (used as-is) |
| `base_commit` | when using `repo` | commit to check out into a worktree |
| `instance_id` | optional | defaults to filename / subdir name |
| `test_patch` | optional | concatenated with `patch` when computing gold files |

Directory form:

```
tasks_dir/
├── my-task-1/
│   ├── meta.json       # {repo, base_commit, problem_statement, ...}
│   ├── gold.patch
│   └── test.patch      # optional
├── my-task-2/
│   └── ...
```

## Built-in retrievers

| Name | What it does |
|---|---|
| `ripgrep` | Extract keywords from the query → `rg -l --fixed-strings` → rank files by distinct-keyword hit count. |
| `bm25` | BM25 over file contents using `rank-bm25`; one document per file. |
| `semble` | Wraps `semble.SembleIndex.from_path`; over-fetches chunks, dedupes to file paths. Requires the `semble` extra. |

Plug in your own:

```python
# my_retriever.py
class MyRetriever:
    name = "mine"
    def index(self, repo_path): ...     # called once per (repo, commit)
    def query(self, index, query, k):   # returns a ranked list of file paths
        ...
```

```bash
uv run file-localization --retriever my_retriever:MyRetriever --dataset lite
```

## Smoke results (illustrative, N=3)

Three `psf/requests` tasks from SWE-bench Lite. **Three queries is not a measurement — these numbers are here to show the framework runs end-to-end.**

| Method  | R@1  | R@5  | R@10 | NDCG@5 | NDCG@10 | idx ms | query ms |
|---------|-----:|-----:|-----:|-------:|--------:|-------:|---------:|
| ripgrep | 0.00 | 0.33 | 1.00 |  0.167 |   0.404 |    ~0  |    189.7 |
| bm25    | 0.00 | 0.67 | 1.00 |  0.287 |   0.388 |   19.5 |      1.0 |
| semble  | 0.33 | 1.00 | 1.00 |  0.687 |   0.687 |  445.2 |     14.4 |

Per-task rank of the gold edit file in each retriever's top-10:

| Task | Gold file | ripgrep | bm25 | semble |
|---|---|---:|---:|---:|
| psf__requests-1963 | `requests/sessions.py` | 3 | 4 | **1** |
| psf__requests-2148 | `requests/models.py`   | 6 | 4 | **2** |
| psf__requests-2317 | `requests/sessions.py` | 6 | 9 | **4** |

## Caveats worth stating upfront

- **Test files in gold patches.** SWE-bench patches typically include the *test* that catches the bug as well as the fix. `recall_edit` / `ndcg_edit` exclude test files using a path-based heuristic in `patches.py:TEST_PATH_RE` — tune if your dataset has unusual conventions.
- **Query construction.** The full `problem_statement` is fed to the retriever without truncation. Long issues with stack traces may favor or disadvantage different retrievers; report at multiple lengths if you want to be careful.
- **Contamination.** Embedding models trained on GitHub may have seen Verified / Lite instances. Use SWE-bench Pro (`--dataset pro`) for less contaminated evaluation.
- **One-shot retrieval, not iterative.** This measures the ceiling for an agent that gets one retrieval call. Real agents iterate.

## Layout

```
src/file_localization/
├── data.py            # HF dataset loader, Task dataclass
├── local.py           # JSONL / JSON / directory loaders; make_single_task
├── patches.py         # gold-patch parsing, edit/test split
├── repos.py           # bare clone + worktree cache; local repo_path passthrough
├── metrics.py         # recall@k, NDCG@k
├── runner.py          # run / summarize / save_results
├── cli.py             # entry point
└── retrievers/
    ├── base.py        # Retriever Protocol
    ├── ripgrep.py
    ├── bm25.py
    └── semble.py
```

## License

MIT (assumed — add a LICENSE file).
