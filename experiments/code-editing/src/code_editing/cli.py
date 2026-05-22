"""Typer CLI for the experiment harness."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from agent_eval import MODELS, ModelClient, RunRecord, make_client
from agent_eval.models.anthropic_client import ANTHROPIC_MODELS
from agent_eval.models.openai_client import OPENAI_MODELS
from agent_eval.reports import write_csv, write_markdown

from code_editing.bench import discover_tasks, load_task, run_trial
from code_editing.bench.runner import run_single_shot, run_structured
from code_editing.formats import FORMAT_REGISTRY


app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASKS = PROJECT_ROOT / "tasks"
DEFAULT_OUT = PROJECT_ROOT / "results"


@app.callback()
def _main_callback() -> None:
    # Project-local .env wins, then walk up looking for a shared .env (e.g. ~/Development/.env)
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    for parent in PROJECT_ROOT.parents:
        candidate = parent / ".env"
        if candidate.exists():
            load_dotenv(candidate, override=False)
            break


def _make_client(model: str) -> ModelClient:
    if model not in MODELS:
        raise typer.BadParameter(f"unknown model: {model}")
    return make_client(model)


@app.command("list-formats")
def list_formats() -> None:
    t = Table(title="Edit formats")
    t.add_column("name")
    t.add_column("description")
    for name, cls in sorted(FORMAT_REGISTRY.items()):
        t.add_row(name, cls.description)
    console.print(t)


@app.command("list-models")
def list_models() -> None:
    t = Table(title="Models")
    t.add_column("name")
    t.add_column("provider")
    t.add_column("provider_id")
    for name, pid in sorted(ANTHROPIC_MODELS.items()):
        t.add_row(name, "anthropic", pid)
    for name, pid in sorted(OPENAI_MODELS.items()):
        t.add_row(name, "openai", pid)
    console.print(t)


@app.command("list-tasks")
def list_tasks(tasks_dir: Path = DEFAULT_TASKS) -> None:
    tasks = discover_tasks(tasks_dir)
    t = Table(title=f"Tasks in {tasks_dir}")
    t.add_column("task_id")
    t.add_column("lang")
    t.add_column("category")
    t.add_column("oracle_cmd")
    for task in tasks:
        t.add_row(task.task_id, task.language, task.category, " ".join(task.oracle_cmd))
    console.print(t)


@app.command("run")
def run(
    task: str = typer.Option(..., help="Task id (or path to task directory)"),
    model: str = typer.Option(..., help="Model name (see list-models)"),
    fmt: str = typer.Option(..., "--format", help="Edit format (see list-formats)"),
    tasks_dir: Path = DEFAULT_TASKS,
    mode: str = typer.Option("single", help="single | structured | agent"),
    max_turns: int = 12,
    out_dir: Path = DEFAULT_OUT,
) -> None:
    """Run a single (task, model, format) trial."""

    task_spec = _resolve_task(task, tasks_dir)
    if fmt not in FORMAT_REGISTRY:
        raise typer.BadParameter(f"unknown format: {fmt}")
    fmt_obj = FORMAT_REGISTRY[fmt]()
    client = _make_client(model)

    with tempfile.TemporaryDirectory(prefix=f"ct-{task_spec.task_id}-") as tmp:
        workdir = Path(tmp) / "work"
        if mode == "single":
            rec = run_single_shot(task_spec, client, fmt_obj, workdir, transcripts_dir=out_dir / "transcripts")
        elif mode == "structured":
            rec = run_structured(task_spec, client, fmt_obj, workdir, transcripts_dir=out_dir / "transcripts")
        elif mode == "agent":
            rec = run_trial(task_spec, client, fmt_obj, workdir, max_turns=max_turns, transcripts_dir=out_dir / "transcripts")
        else:
            raise typer.BadParameter(f"unknown mode: {mode} (use 'single', 'structured', or 'agent')")

    _print_record(rec)
    write_csv([rec], out_dir / "single_run.csv")


@app.command("sweep")
def sweep(
    models: str = typer.Option(
        "claude-sonnet-4-6",
        help="Comma-separated model names",
    ),
    formats: str = typer.Option(
        "search_replace,unified_diff,ast_python,semantic_ops",
        help="Comma-separated edit format names",
    ),
    tasks_dir: Path = DEFAULT_TASKS,
    only_category: str | None = typer.Option(None, help="Restrict to one category"),
    only_language: str | None = typer.Option(None, help="Restrict to one language"),
    only_size: str | None = typer.Option(None, help="Restrict to one size: small|medium|large"),
    mode: str = typer.Option("single", help="single | agent"),
    max_turns: int = 12,
    out_dir: Path = DEFAULT_OUT,
    limit: int | None = typer.Option(None, help="Cap tasks for a smoke run"),
) -> None:
    """Sweep across (task, model, format)."""

    model_list = [m.strip() for m in models.split(",") if m.strip()]
    fmt_list = [f.strip() for f in formats.split(",") if f.strip()]
    for m in model_list:
        if m not in MODELS:
            raise typer.BadParameter(f"unknown model: {m}")
    for f in fmt_list:
        if f not in FORMAT_REGISTRY:
            raise typer.BadParameter(f"unknown format: {f}")

    tasks = discover_tasks(tasks_dir)
    if only_category:
        tasks = [t for t in tasks if t.category == only_category]
    if only_language:
        tasks = [t for t in tasks if t.language == only_language]
    if only_size:
        tasks = [t for t in tasks if t.task_id.endswith(f"__{only_size}")]
    if limit is not None:
        tasks = tasks[:limit]

    if not tasks:
        console.print("[red]no tasks matched[/red]")
        raise typer.Exit(1)

    records: list[RunRecord] = []
    total = len(tasks) * len(model_list) * len(fmt_list)
    idx = 0
    for task in tasks:
        for model_name in model_list:
            for fmt_name in fmt_list:
                idx += 1
                # Skip language/format combos that don't make sense
                if task.language != "python" and fmt_name in {"ast_python", "semantic_ops"}:
                    console.print(
                        f"[yellow]({idx}/{total}) skip {task.task_id} / {model_name} / {fmt_name}: "
                        f"format only supports python[/yellow]"
                    )
                    continue
                console.print(
                    f"[cyan]({idx}/{total})[/cyan] {task.task_id} / {model_name} / {fmt_name}"
                )
                client = _make_client(model_name)
                fmt_obj = FORMAT_REGISTRY[fmt_name]()
                with tempfile.TemporaryDirectory(prefix=f"ct-{task.task_id}-") as tmp:
                    workdir = Path(tmp) / "work"
                    try:
                        if mode == "single":
                            rec = run_single_shot(task, client, fmt_obj, workdir, transcripts_dir=out_dir / "transcripts")
                        elif mode == "structured":
                            rec = run_structured(task, client, fmt_obj, workdir, transcripts_dir=out_dir / "transcripts")
                        else:
                            rec = run_trial(task, client, fmt_obj, workdir, max_turns=max_turns, transcripts_dir=out_dir / "transcripts")
                    except Exception as e:  # noqa: BLE001
                        console.print(f"[red]trial errored: {e}[/red]")
                        continue
                records.append(rec)
                status = "[green]PASS[/green]" if rec.passed else "[red]FAIL[/red]"
                console.print(
                    f"    {status} turns={rec.turns} tools={rec.tool_calls} "
                    f"invalid={rec.invalid_tool_calls} "
                    f"tokens={rec.usage.input_tokens + rec.usage.output_tokens}"
                )

    write_csv(records, out_dir / "sweep.csv")
    write_markdown(records, out_dir / "sweep.md")
    console.print(f"\n[green]Wrote {len(records)} records to {out_dir}[/green]")


def _resolve_task(task: str, tasks_dir: Path) -> "TaskSpec":  # type: ignore[name-defined]
    from code_editing.types import TaskSpec

    p = Path(task)
    if p.exists() and (p / "task.yaml").exists():
        return load_task(p)
    for t in discover_tasks(tasks_dir):
        if t.task_id == task:
            return t
    raise typer.BadParameter(f"task not found: {task}")


def _print_record(rec: RunRecord) -> None:
    t = Table(title=f"{rec.task_id} | {rec.model} | {rec.condition}")
    t.add_column("metric")
    t.add_column("value")
    t.add_row("passed", "[green]yes[/green]" if rec.passed else "[red]no[/red]")
    t.add_row("turns", str(rec.turns))
    t.add_row("tool_calls", str(rec.tool_calls))
    t.add_row("invalid_tool_calls", str(rec.invalid_tool_calls))
    t.add_row("input_tokens", str(rec.usage.input_tokens))
    t.add_row("output_tokens", str(rec.usage.output_tokens))
    t.add_row("latency_s", f"{rec.latency_seconds:.2f}")
    if rec.error:
        t.add_row("error", rec.error)
    if rec.transcript_path:
        t.add_row("transcript", rec.transcript_path)
    console.print(t)
    if not rec.passed and rec.stdout:
        console.print("[dim]--- oracle stdout (tail) ---[/dim]")
        console.print(rec.stdout[-1500:])
    if not rec.passed and rec.stderr:
        console.print("[dim]--- oracle stderr (tail) ---[/dim]")
        console.print(rec.stderr[-1500:])


if __name__ == "__main__":
    app()
