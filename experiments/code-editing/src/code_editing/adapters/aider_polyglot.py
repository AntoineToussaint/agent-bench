"""Import a subset of Aider's Polyglot benchmark as code-editing tasks.

Source: https://github.com/Aider-AI/polyglot-benchmark

For each exercise it converts:
  - .docs/instructions.md  → task.yaml `instructions`
  - <exercise>.py / .ts    → fixture/
  - <exercise>_test.py     → oracle/tests/
into our task layout under tasks/polyglot/<lang>/<exercise>/.

Usage:
    uv run python scripts/fetch_polyglot.py --langs python,typescript --limit 25
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import yaml  # type: ignore[import-not-found]
from git import Repo

POLYGLOT_REPO = "https://github.com/Aider-AI/polyglot-benchmark"
SUPPORTED_LANGS = {"python", "typescript", "javascript", "go", "rust", "cpp", "java"}


def fetch(langs: list[str], limit: int | None, dest_root: Path) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        print(f"cloning {POLYGLOT_REPO} ...")
        repo_path = Path(tmp) / "polyglot"
        Repo.clone_from(POLYGLOT_REPO, repo_path, depth=1)

        count = 0
        for lang in langs:
            if lang not in SUPPORTED_LANGS:
                print(f"skipping unknown lang: {lang}")
                continue
            lang_root = repo_path / lang / "exercises" / "practice"
            if not lang_root.exists():
                print(f"  no exercises dir for {lang}")
                continue
            for ex_dir in sorted(lang_root.iterdir()):
                if not ex_dir.is_dir():
                    continue
                if limit is not None and count >= limit:
                    return count
                if _import_exercise(lang, ex_dir, dest_root):
                    count += 1
        return count


def _import_exercise(lang: str, ex_dir: Path, dest_root: Path) -> bool:
    name = ex_dir.name
    instructions_path = ex_dir / ".docs" / "instructions.md"
    if not instructions_path.exists():
        return False
    instructions = instructions_path.read_text(encoding="utf-8")

    out_dir = dest_root / "tasks" / "polyglot" / lang / name
    fixture = out_dir / "fixture"
    oracle = out_dir / "oracle"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    fixture.mkdir(parents=True)
    oracle.mkdir(parents=True)

    if lang == "python":
        oracle_cmd = ["python", "-m", "pytest", "-q", str("tests/")]
        # Find source file(s) — exercise dir contains foo.py and foo_test.py
        files_in_context: list[str] = []
        tests_dir = oracle / "tests"
        tests_dir.mkdir()
        for f in ex_dir.iterdir():
            if not f.is_file() or f.suffix != ".py":
                continue
            if f.name.endswith("_test.py"):
                shutil.copy2(f, tests_dir / f.name)
            else:
                shutil.copy2(f, fixture / f.name)
                files_in_context.append(f.name)
    elif lang == "typescript":
        oracle_cmd = ["npm", "test", "--silent"]
        files_in_context = []
        for f in ex_dir.iterdir():
            if f.is_file() and f.suffix in {".ts", ".js", ".json"}:
                shutil.copy2(f, fixture / f.name)
                if not f.name.endswith(".test.ts"):
                    files_in_context.append(f.name)
        # ts tests live in fixture too in Polyglot layout
    else:
        # generic: copy everything, leave oracle_cmd blank
        oracle_cmd = []
        files_in_context = []
        for f in ex_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, fixture / f.name)
                files_in_context.append(f.name)

    meta = {
        "task_id": f"polyglot-{lang}-{name}",
        "language": lang,
        "category": "polyglot",
        "instructions": instructions,
        "files_in_context": files_in_context,
        "oracle_cmd": oracle_cmd,
    }
    (out_dir / "task.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return True


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--langs", default="python", help="Comma-separated language list.")
    p.add_argument("--limit", type=int, default=None, help="Max exercises per language.")
    p.add_argument(
        "--dest",
        default=str(Path(__file__).resolve().parents[1]),
        help="Project root (default: this repo).",
    )
    args = p.parse_args()
    langs = [s.strip() for s in args.langs.split(",") if s.strip()]
    count = fetch(langs, args.limit, Path(args.dest))
    print(f"imported {count} exercise(s).")


if __name__ == "__main__":
    main()
