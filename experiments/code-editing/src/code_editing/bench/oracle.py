"""Run a task's oracle command in the workdir and return pass/fail + output."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OracleResult:
    passed: bool
    returncode: int
    stdout: str
    stderr: str


def run_oracle(cmd: list[str], workdir: Path, timeout: int = 60) -> OracleResult:
    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return OracleResult(
            passed=False,
            returncode=-1,
            stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
            stderr=(e.stderr or "TIMEOUT") if isinstance(e.stderr, str) else "TIMEOUT",
        )
    except FileNotFoundError as e:
        return OracleResult(passed=False, returncode=-2, stdout="", stderr=str(e))
    return OracleResult(
        passed=proc.returncode == 0,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
