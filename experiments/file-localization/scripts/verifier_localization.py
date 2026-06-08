"""Can a CHEAP model verify a localization — "are these the right files to edit?"
— without the gold patch?

Why this matters (STRATEGY.md): the localization reward (Hit@k vs gold files) is
ORACLE-ONLY — it doesn't exist in production. The whole plan needs a deploy-time
signal instead. The repair-patch verifier (analyze_verifier.py) looked strong
(stop-precision 1.00, 0% catastrophic); this asks the same of the phase whose
reward is hardest to get in prod.

v0 design — controlled candidates, no repo cloning:
  - Load SWE-bench-verified tasks (issue_text + gold_edit_files) via HF.
  - For each task build candidate localizations of known quality:
      positive  = the gold files                       (label: correct)
      negative  = real files from OTHER same-repo issues (label: wrong — right
                  repo, wrong place; a plausible distractor, not a random path)
  - Run a cheap CONSERVATIVE verifier on each (issue + proposed files -> CONFIDENT
    / NOT_CONFIDENT). It sees paths + issue only (no file contents) — a fair first
    test of whether that alone suffices.
  - Score the verdict against gold (candidate ⊇ gold). Confusion matrix, same
    asymmetric framing as the repair verifier: a false CONFIDENT green-lights a
    WRONG localization (catastrophic); a false NOT_CONFIDENT just over-escalates.

Limitations (honest): synthetic negatives may be easier than a real localizer's
mistakes; no file contents shown; small n. A v1 would score REAL localizer
outputs and feed file snippets.

Usage:
  cd /Users/antoine/Development/research/agent-bench
  uv run --package file-localization python \
    experiments/file-localization/scripts/verifier_localization.py \
    --n 12 --verifier-model claude-haiku-4-5 --out results/verifier_localization
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

from agent_eval import make_client
from agent_eval.pricing import cost_usd
from file_localization.adapters.hf_swebench import load_swebench, to_localization_tasks

SYSTEM = (
    "You are a STRICT, SKEPTICAL code reviewer. A localizer proposes the set of "
    "files where a GitHub issue should be fixed. You decide whether you are "
    "confident the fix belongs in EXACTLY those files.\n\n"
    "This is asymmetric: a false CONFIDENT sends the fix to the wrong place "
    "(catastrophic); saying NOT_CONFIDENT just asks for another look (cheap). So:\n"
    "  - CONFIDENT only if the proposed files clearly contain where this issue's "
    "root cause lives, and you don't think a key file is missing.\n"
    "  - If you have ANY doubt — a likely-missing file, files that look unrelated "
    "to the issue, too broad/narrow a set — answer NOT_CONFIDENT.\n"
    "First line: exactly CONFIDENT or NOT_CONFIDENT. Then one line why."
)


def _judge(client, issue_text: str, files: list[str]):
    user = (
        "## Issue\n" + issue_text.strip()[:4000] + "\n\n"
        "## Files the localizer proposes editing\n"
        + "\n".join(f"- {f}" for f in files) + "\n\n"
        "Do these files contain where the fix belongs? "
        "First line: CONFIDENT or NOT_CONFIDENT."
    )
    client.reset(SYSTEM)
    client.add_user_text(user)
    t0 = time.monotonic()
    msg = client.step([])
    latency = time.monotonic() - t0
    first = (msg.text or "").strip().splitlines()[0].upper() if (msg.text or "").strip() else ""
    confident = "CONFIDENT" in first and "NOT" not in first
    return confident, msg.usage, latency


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12, help="number of tasks")
    ap.add_argument("--verifier-model", default="claude-haiku-4-5")
    ap.add_argument("--distractors", type=int, default=3, help="wrong files per negative candidate")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="results/verifier_localization")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_dotenv()
    rng = random.Random(args.seed)

    print(f"loading {args.n} SWE-bench-verified tasks (HF; first run downloads the dataset)...")
    raws = load_swebench("verified", "test")
    tasks = [t for t in to_localization_tasks(raws) if t.gold_edit_files]
    tasks = tasks[: args.n]

    # distractor pool: real gold files grouped by repo (right repo, wrong issue)
    pool: dict[str, set[str]] = defaultdict(set)
    for t in to_localization_tasks(raws):
        pool[t.repo] |= set(t.gold_edit_files)

    # build (task, candidate, label) cases
    cases = []
    for t in tasks:
        gold = set(t.gold_edit_files)
        cases.append((t, sorted(gold), True))  # positive
        wrong_pool = sorted(pool[t.repo] - gold)
        if wrong_pool:
            neg = rng.sample(wrong_pool, min(args.distractors, len(wrong_pool)))
            cases.append((t, neg, False))  # negative: right repo, wrong files

    print(f"{len(tasks)} tasks -> {len(cases)} candidates "
          f"({sum(1 for _,_,l in cases if l)} positive / {sum(1 for _,_,l in cases if not l)} negative); "
          f"verifier = {args.verifier_model}")
    if args.dry_run:
        for t, files, label in cases[:6]:
            print(f"  [{'POS' if label else 'NEG'}] {t.task_id}: {files}")
        print("[dry-run] no API calls.")
        return 0

    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2

    client = make_client(args.verifier_model)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    conf = defaultdict(int)
    rows = []
    for t, files, label in cases:
        confident, usage, latency = _judge(client, t.issue_text, files)
        cost = cost_usd(args.verifier_model, usage)
        correct = (confident == label)
        cell = ("TP" if confident and label else "FP" if confident and not label
                else "FN" if (not confident) and label else "TN")
        conf[cell] += 1
        rows.append((t.task_id, "pos" if label else "neg", int(confident), int(label),
                     cell, f"{cost:.6f}", f"{latency:.2f}"))
        print(f"  {t.task_id:28s} {'POS' if label else 'NEG'} "
              f"verdict={'CONF' if confident else 'NOT '} -> {cell}")

    with (out / "per_case.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "candidate", "confident", "is_correct", "cell", "cost_usd", "latency_s"])
        w.writerows(rows)

    TP, FP, FN, TN = conf["TP"], conf["FP"], conf["FN"], conf["TN"]
    n = TP + FP + FN + TN
    acc = (TP + TN) / n if n else 0
    prec = TP / (TP + FP) if (TP + FP) else float("nan")
    rec = TP / (TP + FN) if (TP + FN) else float("nan")
    print(f"\n=== LOCALIZATION VERIFIER ({args.verifier_model}, n={n}) ===")
    print(f"  accuracy           {acc:.2f}")
    print(f"  confident-precision {prec:.2f}  (when it says CONFIDENT, how often the localization is actually right)")
    print(f"  confident-recall    {rec:.2f}  (of correct localizations, how often it's confident)")
    print(f"  CATASTROPHIC (FP)  {FP}/{n} = {FP/n if n else 0:.2f}  (green-lit a WRONG localization)")
    print(f"  safe reject  (FN)  {FN}/{n}           (rejected a correct localization)")
    print(f"  confusion  TP={TP} FP={FP} FN={FN} TN={TN}")
    print(f"\nwrote {out/'per_case.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
