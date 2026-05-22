"""Quick CLI to dump a saved transcript as: turn-by-turn calls + results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--max-content", type=int, default=200)
    args = p.parse_args()

    d = json.loads(Path(args.path).read_text())
    print(f"task: {d['task_id']} | model: {d['model']} | format: {d['format']}")
    print(f"oracle.passed: {d['oracle']['passed']}")
    print(f"entries: {len(d['entries'])}")
    print()
    for i, e in enumerate(d["entries"]):
        if e["role"] == "user":
            text = (e.get("content") or "(payload)")[: args.max_content].replace("\n", " / ")
            print(f"[{i:2}] USER   {text!r}")
        elif e["role"] == "assistant":
            if e.get("text"):
                snip = e["text"][: args.max_content].replace("\n", " / ")
                print(f"[{i:2}] ASST_TXT {snip!r}")
            for tc in e["tool_calls"]:
                args_str = json.dumps(tc["arguments"])[: args.max_content].replace("\n", " / ")
                print(f"[{i:2}] CALL   {tc['name']}({args_str})")
        elif e["role"] == "tool":
            for r in e["results"]:
                content = r["content"][: args.max_content].replace("\n", " / ")
                print(f"[{i:2}] {r['status'].upper():5}  {content}")
        else:
            print(f"[{i:2}] {e['role']:6} {str(e)[:200]}")


if __name__ == "__main__":
    main()
