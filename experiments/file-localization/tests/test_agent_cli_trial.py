"""Offline tests for the agent-CLI subprocess trials.

These tests stub `subprocess.run` so we never actually spawn `claude` or
`codex`. The point is to verify the wiring: prompt formatting, parsing,
scoring, error propagation, and the RunRecord shape.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from file_localization.agent_cli_trial import (
    _parse_files,
    is_available,
    make_claude_code_trial,
    make_codex_trial,
)
from file_localization.contract import LocalizationTask
from file_localization.turn_loop_trial import LocalRepoView


# ---------- helpers ----------


@dataclass
class _StubClient:
    """Minimal client stub — only `name` is read by the trial."""

    name: str = "claude-sonnet-4-6"

    def reset(self, system: str) -> None: ...
    def add_user_text(self, text: str) -> None: ...
    def add_tool_results(self, results) -> None: ...
    def step(self, tools): raise AssertionError("should not be called")


def _task() -> LocalizationTask:
    return LocalizationTask(
        instance_id="demo-1",
        issue_text="compute_total is missing tax computation",
        repo="demo/repo",
        base_commit="abc123def456",
        gold_edit_files=frozenset({"src/foo.py"}),
        gold_test_files=frozenset({"tests/test_foo.py"}),
    )


def _make_view(tmp_path: Path) -> LocalRepoView:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").write_text("assert True\n")
    return LocalRepoView(tmp_path)


class _FakeCompleted:
    """Stand-in for `subprocess.CompletedProcess`."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# ---------- is_available ----------


def test_is_available_false_for_bogus_binary() -> None:
    assert is_available("definitely-not-a-real-cli-xyz123") is False


def test_is_available_false_for_empty() -> None:
    assert is_available("") is False


def test_is_available_true_for_existing_path(tmp_path: Path) -> None:
    f = tmp_path / "fake-cli"
    f.write_text("#!/bin/sh\necho hi\n")
    assert is_available(str(f)) is True


# ---------- parsing ----------


def test_parse_files_basic_block() -> None:
    out = "Here are the files:\nFILE: src/foo.py\nFILE: tests/test_foo.py\n"
    assert _parse_files(out) == ["src/foo.py", "tests/test_foo.py"]


def test_parse_files_dedupes_preserve_order() -> None:
    out = "FILE: a.py\nFILE: b.py\nFILE: a.py\n"
    assert _parse_files(out) == ["a.py", "b.py"]


def test_parse_files_empty_returns_empty() -> None:
    assert _parse_files("") == []
    assert _parse_files("no file lines here") == []


# ---------- claude code trial (mocked subprocess) ----------


def test_claude_trial_parses_stdout_and_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = _make_view(tmp_path)
    task = _task()
    fake_stdout = "FILE: src/foo.py\nFILE: tests/test_foo.py\n"
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["cwd"] = kwargs.get("cwd")
        captured["timeout"] = kwargs.get("timeout")
        return _FakeCompleted(stdout=fake_stdout, stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    trial = make_claude_code_trial(repo_view_for=lambda t: view, cli_path="claude")
    rec = trial(_StubClient(name="claude-sonnet-4-6"), "agent-cli-claude-code", task)

    # wiring
    assert captured["argv"][0] == "claude"
    assert "-p" in captured["argv"]
    # the prompt is the last positional that contains "## Issue"
    assert any("## Issue" in a for a in captured["argv"])
    assert captured["cwd"] == str(view.root)
    assert captured["timeout"] == 120

    # outcome
    assert rec.passed is True
    assert rec.error is None
    assert rec.turns == 1
    assert rec.tool_calls == 0
    assert rec.invalid_tool_calls == 0
    assert rec.cost_usd == 0.0
    assert rec.usage.input_tokens == 0
    assert rec.usage.output_tokens == 0
    assert rec.condition == "agent-cli-claude-code"
    assert rec.model == "claude-sonnet-4-6"
    assert rec.task_id == "demo-1"
    assert rec.extra["recall"] == 1.0
    assert rec.extra["precision"] == 1.0
    assert rec.extra["n_predicted"] == 2
    assert rec.extra["n_false_positives"] == 0
    assert rec.extra["submitted"] == ["src/foo.py", "tests/test_foo.py"]
    assert rec.stdout == fake_stdout


def test_codex_trial_parses_stdout_and_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = _make_view(tmp_path)
    task = _task()
    fake_stdout = (
        "Looked through the code, here's my answer:\n"
        "FILE: src/foo.py\n"
        "FILE: tests/test_foo.py\n"
    )
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["cwd"] = kwargs.get("cwd")
        return _FakeCompleted(stdout=fake_stdout, stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    trial = make_codex_trial(repo_view_for=lambda t: view, cli_path="codex")
    rec = trial(_StubClient(name="gpt-5"), "agent-cli-codex", task)

    assert captured["argv"][0] == "codex"
    assert captured["argv"][1] == "exec"
    assert captured["cwd"] == str(view.root)
    assert rec.passed is True
    assert rec.extra["recall"] == 1.0
    assert rec.extra["submitted"] == ["src/foo.py", "tests/test_foo.py"]
    assert rec.condition == "agent-cli-codex"
    assert rec.model == "gpt-5"


def test_trial_handles_zero_file_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = _make_view(tmp_path)
    task = _task()

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: _FakeCompleted(stdout="I am thinking out loud.\n", stderr=""),
    )

    trial = make_claude_code_trial(repo_view_for=lambda t: view)
    rec = trial(_StubClient(), "agent-cli-claude-code", task)
    assert rec.passed is False
    assert rec.extra["submitted"] == []
    assert rec.extra["n_predicted"] == 0
    assert rec.extra["recall"] == 0.0
    assert rec.error is None  # CLI succeeded; just gave no useful answer


def test_trial_timeout_sets_error_and_does_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = _make_view(tmp_path)
    task = _task()

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(subprocess, "run", fake_run)

    trial = make_claude_code_trial(repo_view_for=lambda t: view, timeout=5)
    rec = trial(_StubClient(), "agent-cli-claude-code", task)

    assert rec.error == "cli_timeout"
    assert rec.passed is False
    assert rec.extra["submitted"] == []
    # latency should still be recorded
    assert rec.latency_seconds >= 0.0


def test_trial_nonzero_exit_records_error_but_still_parses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = _make_view(tmp_path)
    task = _task()
    # Even on failure, the CLI may have printed partial output; we should
    # still parse it but mark the record as errored (passed=False).
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: _FakeCompleted(
            stdout="FILE: src/foo.py\nFILE: tests/test_foo.py\n",
            stderr="boom",
            returncode=2,
        ),
    )
    trial = make_codex_trial(repo_view_for=lambda t: view)
    rec = trial(_StubClient(), "agent-cli-codex", task)

    assert rec.error is not None and rec.error.startswith("cli_failed")
    assert rec.passed is False  # forced False due to error
    assert rec.extra["recall"] == 1.0  # parsing still worked
    assert rec.stderr == "boom"


def test_trial_filenotfound_sets_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = _make_view(tmp_path)
    task = _task()

    def fake_run(argv, **kwargs):
        raise FileNotFoundError(2, "No such file", argv[0])

    monkeypatch.setattr(subprocess, "run", fake_run)

    trial = make_claude_code_trial(
        repo_view_for=lambda t: view, cli_path="not-a-real-binary"
    )
    rec = trial(_StubClient(), "agent-cli-claude-code", task)
    assert rec.error == "cli_not_found"
    assert rec.passed is False


def test_trial_rejects_repo_view_without_root(tmp_path: Path) -> None:
    class _Bogus:
        pass

    task = _task()
    trial = make_claude_code_trial(repo_view_for=lambda t: _Bogus())
    with pytest.raises(TypeError, match="\\.root"):
        trial(_StubClient(), "agent-cli-claude-code", task)
