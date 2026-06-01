"""Generate example trace bundles for Mind's agent-debugger.

Builds a handful of illustrative localization SessionTraces (no API, no repo —
synthetic but realistic conversations), writes each as a debugger bundle
(`<dir>/<task>/execution.json` + `openinference.json`), and seeds one annotation
so the annotation system shows content on first open.

Default output is ~/.mind/traces (what the debugger reads with no env set), so:

    uv run --package file-localization python \\
        experiments/file-localization/scripts/make_debugger_examples.py
    cd ~/Development/mind/docs/harness/research/agent-research/agent-debugger
    pnpm install && pnpm dev          # http://localhost:3000

Override the dir with --out (then start the app with
MIND_AGENT_DEBUGGER_TRACE_DIR=<dir>).
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent_eval import (
    AssistantMessage,
    PhaseConfig,
    PhaseReward,
    SessionTrace,
    Snapshot,
    ToolCall,
    Transcript,
    TurnUsage,
    write_to_debugger,
)


def _conv(system: str, turns: list[tuple[str, list[ToolCall]]]) -> Transcript:
    t = Transcript(system=system)
    t.add_user_text("Issue: AltAz frame transform raises ValueError on empty input arrays.")
    for text, calls in turns:
        t.add_assistant(
            AssistantMessage(text=text, tool_calls=calls, usage=TurnUsage(input_tokens=900, output_tokens=40))
        )
    return t


def _grep(pattern: str) -> ToolCall:
    return ToolCall(name="grep", arguments={"pattern": pattern}, call_id=uuid.uuid4().hex[:8])


def _view(path: str) -> ToolCall:
    return ToolCall(name="view_file", arguments={"path": path}, call_id=uuid.uuid4().hex[:8])


def _done(files: list[str]) -> ToolCall:
    return ToolCall(name="done", arguments={"files": files}, call_id=uuid.uuid4().hex[:8])


_SYS = "You localize the source files a GitHub issue needs edited. Explore, then call done(files=[...])."
GOLD = ["astropy/coordinates/builtin_frames/altaz.py"]


def _reward(submitted: list[str], composite: float, passed: bool) -> PhaseReward:
    return PhaseReward(
        value=composite, kind="oracle",
        detail={"passed": passed, "recall": 1.0 if passed else 0.0, "submitted": submitted},
    )


def example_pass() -> SessionTrace:
    t = SessionTrace(task_id="astropy-12907-pass")
    root = t.start(Snapshot())
    sub = GOLD
    conv = _conv(_SYS, [
        ("Searching for the AltAz frame.", [_grep("class AltAz")]),
        ("Confirming the transform lives here.", [_view(GOLD[0])]),
        ("Found the file.", [_done(sub)]),
    ])
    t.add(phase="localize", config=PhaseConfig("claude-sonnet-4-6", "cot", "keep_everything"),
          parent=root, snapshot=Snapshot.from_transcript(conv), reward=_reward(sub, 1.0, True),
          metadata={"context_frames": 6, "context_omissions": 0})
    return t


def example_missing() -> SessionTrace:
    t = SessionTrace(task_id="astropy-13398-missing")
    root = t.start(Snapshot())
    sub = ["astropy/coordinates/sky_coordinate.py"]  # plausible but not the gold file
    conv = _conv(_SYS, [
        ("This looks like a SkyCoord issue.", [_grep("def transform_to")]),
        ("Submitting SkyCoord.", [_done(sub)]),
    ])
    t.add(phase="localize", config=PhaseConfig("claude-haiku-4-5", "terse", "keep_everything"),
          parent=root, snapshot=Snapshot.from_transcript(conv), reward=_reward(sub, 0.0, False),
          metadata={"context_frames": 4, "context_omissions": 0})
    return t


def example_irrelevant() -> SessionTrace:
    t = SessionTrace(task_id="astropy-irrelevant")
    root = t.start(Snapshot())
    sub = ["docs/changelog.rst", "setup.py"]  # entirely wrong region
    conv = _conv(_SYS, [("Maybe it's a packaging issue.", [_done(sub)])])
    t.add(phase="localize", config=PhaseConfig("claude-haiku-4-5", "terse", "keep_everything"),
          parent=root, snapshot=Snapshot.from_transcript(conv), reward=_reward(sub, 0.0, False),
          metadata={"context_frames": 2, "context_omissions": 0})
    return t


def example_sliding_window() -> SessionTrace:
    t = SessionTrace(task_id="astropy-window-omits")
    root = t.start(Snapshot())
    sub = GOLD
    conv = _conv(_SYS, [
        ("Listing the coordinates package.", [_grep("AltAz")]),
        ("Reading candidates.", [_view("astropy/coordinates/builtin_frames/__init__.py")]),
        ("Narrowing down.", [_view(GOLD[0])]),
        ("Done.", [_done(sub)]),
    ])
    # A pruning policy dropped 3 older messages from the window.
    t.add(phase="localize", config=PhaseConfig("claude-sonnet-4-6", "cot", "sliding_window_5"),
          parent=root, snapshot=Snapshot.from_transcript(conv), reward=_reward(sub, 0.95, True),
          metadata={"context_frames": 5, "context_omissions": 3})
    return t


def example_forked() -> tuple[SessionTrace, str]:
    """Two config arms on one task. Returns (trace, losing_arm_node_id) so the
    caller can seed an annotation on the arm that failed."""
    t = SessionTrace(task_id="astropy-forked-arms")
    root = t.start(Snapshot())
    # Arm A: haiku, wrong region.
    a = t.add(phase="localize", config=PhaseConfig("claude-haiku-4-5", "terse", "keep_everything"),
              parent=root,
              snapshot=Snapshot.from_transcript(_conv(_SYS, [("Guessing SkyCoord.", [_done(["astropy/coordinates/sky_coordinate.py"])])])),
              reward=_reward(["astropy/coordinates/sky_coordinate.py"], 0.0, False))
    # Arm B: sonnet, correct.
    t.add(phase="localize", config=PhaseConfig("claude-sonnet-4-6", "cot", "tool_result_elision_2"),
          parent=root,
          snapshot=Snapshot.from_transcript(_conv(_SYS, [("Searching AltAz.", [_grep("class AltAz")]), ("Found it.", [_done(GOLD)])])),
          reward=_reward(GOLD, 1.0, True))
    return t, a.id


def _seed_annotation(out_dir: Path, file_id: str, object_id: str) -> Path:
    """Write an annotation sidecar attaching a note to a failed objective."""
    now = datetime.now(timezone.utc).isoformat()
    ann = {
        "version": 2,
        "annotations": [
            {
                "id": str(uuid.uuid4()),
                "spanId": None,
                "objectId": object_id,
                "objectKind": "objective",
                "createdAt": now,
                "updatedAt": now,
                "comment": "Haiku arm localized to SkyCoord — wrong region (localization_irrelevant). "
                           "The issue mentions AltAz explicitly; the model anchored on 'transform' instead. "
                           "Candidate fix: prompt nudge to extract the failing class name first.",
                "tags": ["localization_irrelevant", "haiku", "prompt-fix"],
                "rating": 2,
                "source": "user",
                "author": "me",
            }
        ],
    }
    p = out_dir / f"{file_id}.annotations.json"
    p.write_text(json.dumps(ann, indent=2))
    return p


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=Path.home() / ".mind" / "traces")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    written = []
    for fn in (example_pass, example_missing, example_irrelevant, example_sliding_window):
        tr = fn()
        bundle = write_to_debugger(tr, traces_dir=args.out)
        written.append(bundle.name)

    forked, losing_id = example_forked()
    bundle = write_to_debugger(forked, traces_dir=args.out)
    written.append(bundle.name)
    ann_path = _seed_annotation(args.out, bundle.name, losing_id)

    print(f"wrote {len(written)} example bundles to {args.out}:")
    for w in written:
        print(f"  - {w}")
    print(f"seeded annotation: {ann_path.name} (on the failed haiku arm)")
    print()
    print("View them:")
    print("  cd ~/Development/mind/docs/harness/research/agent-research/agent-debugger")
    if args.out != Path.home() / ".mind" / "traces":
        print(f"  MIND_AGENT_DEBUGGER_TRACE_DIR={args.out} pnpm dev")
    else:
        print("  pnpm dev    # http://localhost:3000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
