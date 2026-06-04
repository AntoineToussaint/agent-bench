"""How good is a CHEAP, deploy-honest verifier? — mined from gate decisions.

STRATEGY.md's central problem: most per-phase rewards (localization Hit@k, test
quality) don't exist at deploy time — you only learn "tests pass" at the very end.
The plan needs a cheap signal that says "is this phase output correct?" WITHOUT an
oracle. The Patch Cascade gate is exactly that: a small conservative model judging
a repair patch, with its verdict logged against a hidden oracle probe (gate_correct).

This aggregates every gate decision across the result CSVs into a confusion matrix
for the verifier, with the ASYMMETRIC framing that matters: a false CONFIDENT ships
broken code (catastrophic); a false NOT_CONFIDENT just wastes a tier (safe).

  decision token  tNN:<C|N><ok|X>   C=CONFIDENT(stop)  N=NOT_CONFIDENT(escalate)
  C ok -> stop & state passes  (TP, correct stop)
  C X  -> stop & state fails   (FP, CATASTROPHIC: ships broken)
  N X  -> escalate & state passes (FN, safe: wasted tier)
  N ok -> escalate & state fails  (TN, correct escalate)

Usage:
  uv run --package code-editing python \
    experiments/code-editing/scripts/analyze_verifier.py results/patch_cascade_*/per_trial.csv
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

DEC = re.compile(r"t(\d+):([CN])(ok|X)")


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print("usage: analyze_verifier.py <per_trial.csv> ...", file=sys.stderr)
        return 1

    # confusion counts, overall and per judged-tier
    overall = defaultdict(int)
    by_tier = defaultdict(lambda: defaultdict(int))
    n_files = 0
    for path in paths:
        if not path.exists():
            continue
        n_files += 1
        for row in csv.DictReader(path.open()):
            for tier, conf, corr in DEC.findall(row.get("gate_decisions", "") or ""):
                # classify
                if conf == "C" and corr == "ok":
                    cell = "TP"
                elif conf == "C" and corr == "X":
                    cell = "FP"  # catastrophic
                elif conf == "N" and corr == "X":
                    cell = "FN"  # safe
                else:
                    cell = "TN"
                overall[cell] += 1
                by_tier[int(tier)][cell] += 1

    def report(label, c):
        TP, FP, FN, TN = c["TP"], c["FP"], c["FN"], c["TN"]
        n = TP + FP + FN + TN
        if not n:
            return
        acc = (TP + TN) / n
        prec = TP / (TP + FP) if (TP + FP) else float("nan")  # safety of a "stop"
        rec = TP / (TP + FN) if (TP + FN) else float("nan")   # of passing states, % stopped
        fp_rate = FP / n  # catastrophic-error rate
        print(f"\n{label}  (n={n})")
        print(f"  accuracy            {acc:.2f}")
        print(f"  stop-precision      {prec:.2f}   (when it says STOP, how often the code is actually correct)")
        print(f"  stop-recall         {rec:.2f}   (of correct states, how often it stops)")
        print(f"  CATASTROPHIC (FP)   {FP}/{n} = {fp_rate:.2f}   (said CONFIDENT on broken code)")
        print(f"  safe waste   (FN)   {FN}/{n}            (escalated already-correct code)")
        print(f"  confusion  TP={TP} FP={FP} FN={FN} TN={TN}")

    print(f"# Cheap verifier accuracy — mined from {n_files} result file(s).")
    print("# Verifier = claude-haiku-4-5 (the gate model), judging repair patches.")
    report("OVERALL", overall)
    for tier in sorted(by_tier):
        report(f"judged after tier {tier}", by_tier[tier])

    fp = overall["FP"]
    tot = sum(overall.values())
    print(f"\nHEADLINE: a cheap conservative verifier shipped broken code in "
          f"{fp}/{tot} decisions ({(fp/tot if tot else 0):.0%}); "
          f"its errors are otherwise on the safe (over-escalate) side.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
