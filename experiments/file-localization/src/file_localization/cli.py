from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from .data import DATASETS, load_tasks
from .local import load_local_tasks, make_single_task
from .runner import run, save_results, summarize

BUILTIN_RETRIEVERS = {
    "ripgrep": "file_localization.retrievers.ripgrep:RipgrepRetriever",
    "bm25": "file_localization.retrievers.bm25:BM25Retriever",
    "semble": "file_localization.retrievers.semble:SembleRetriever",
}


def _resolve(spec: str):
    module, attr = spec.rsplit(":", 1)
    return getattr(importlib.import_module(module), attr)()


def _read_text(path: Path | None) -> str:
    return path.read_text(encoding="utf-8") if path is not None else ""


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="file-localization",
        description="File-localization benchmark against SWE-bench gold patches.",
    )
    p.add_argument(
        "--retriever", required=True,
        help=f"Builtin ({'|'.join(BUILTIN_RETRIEVERS)}) or module:ClassName for a custom retriever.",
    )

    src = p.add_argument_group("task source (pick one)")
    src.add_argument(
        "--dataset",
        help=(
            f"HF alias ({'|'.join(DATASETS)}), raw HF dataset id, or a local "
            "path: .jsonl file, .json file, or directory of task subfolders."
        ),
    )
    src.add_argument("--patch", type=Path, help="Patch file for an ad-hoc single task.")

    ah = p.add_argument_group("ad-hoc task options (used with --patch)")
    ah.add_argument("--query", help="Problem statement / issue text for the ad-hoc task.")
    ah.add_argument("--repo", help="GitHub owner/name for the ad-hoc task (cloned + checked out at --base-commit).")
    ah.add_argument("--base-commit", default="", help="Commit hash to check out (with --repo).")
    ah.add_argument("--repo-path", type=Path, help="Local repo path; skips clone/checkout.")
    ah.add_argument("--test-patch", type=Path, help="Optional test patch file.")
    ah.add_argument("--instance-id", default="adhoc", help="Identifier recorded in the result.")

    flt = p.add_argument_group("dataset filters")
    flt.add_argument("--split", default="test", help="HuggingFace split (default: test).")
    flt.add_argument("--limit", type=int, default=None, help="Cap number of tasks for smoke runs.")
    flt.add_argument(
        "--filter-instance", action="append", default=[],
        help="Restrict to specific instance_ids (repeatable).",
    )
    flt.add_argument(
        "--filter-repo", action="append", default=[],
        help="Restrict to specific repos (owner/name, repeatable).",
    )

    out = p.add_argument_group("output")
    out.add_argument("--output", type=Path, default=Path("results.json"))
    out.add_argument("--k-max", type=int, default=20, help="Retrieve top-N files per query.")
    return p


def _resolve_tasks(args: argparse.Namespace):
    if args.patch and args.dataset:
        raise SystemExit("pick one of --dataset or --patch, not both")
    if args.patch:
        if not args.query:
            raise SystemExit("--query is required with --patch")
        if not (args.repo or args.repo_path):
            raise SystemExit("ad-hoc task needs --repo (+ --base-commit) or --repo-path")
        return [make_single_task(
            patch=_read_text(args.patch),
            problem_statement=args.query,
            repo=args.repo or "",
            base_commit=args.base_commit,
            repo_path=str(args.repo_path) if args.repo_path else "",
            test_patch=_read_text(args.test_patch),
            instance_id=args.instance_id,
        )]
    if not args.dataset:
        raise SystemExit("must provide --dataset or --patch")

    local_path = Path(args.dataset).expanduser()
    if local_path.exists():
        return load_local_tasks(local_path)
    return load_tasks(args.dataset, args.split)


def main() -> None:
    args = _build_parser().parse_args()
    tasks = _resolve_tasks(args)

    if args.filter_instance:
        wanted = set(args.filter_instance)
        tasks = [t for t in tasks if t.instance_id in wanted]
    if args.filter_repo:
        wanted = set(args.filter_repo)
        tasks = [t for t in tasks if t.repo in wanted]
    if args.limit:
        tasks = tasks[: args.limit]
    if not tasks:
        raise SystemExit("No tasks matched the requested filters.")

    spec = BUILTIN_RETRIEVERS.get(args.retriever, args.retriever)
    retriever = _resolve(spec)

    results = run(retriever, tasks, k_max=args.k_max)
    summary = summarize(results)
    save_results(results, summary, args.output)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
