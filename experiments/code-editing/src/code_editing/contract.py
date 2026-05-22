"""Task / Result / scoring contract for code-editing trials.

This is the source of truth for the experiment's typed I/O. The legacy
`code_editing.types` module re-exports `EditTask` as `TaskSpec` for
backward compatibility.

Input (EditTask):
  - A starter directory (`fixture/`) — files copied verbatim into the workdir
  - Instructions in natural language
  - A list of files to put in front of the model up front (the rest can be
    discovered via tools)
  - An oracle command (typically `pytest`) — run inside the workdir after
    the model's edits; exit 0 = passed

Output (EditResult):
  - Path to the final workdir (the model's edits applied to a copy of fixture)
  - Pass/fail from the oracle command
  - Captured stdout/stderr from the oracle

Scoring:
  - passed: oracle exit_code == 0
  - extra:  oracle returncode, tool-call counts, tokens (carried on RunRecord)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


Language = Literal["python", "typescript"]


@dataclass
class EditTask:
    """Input contract for a code-editing trial."""

    task_id: str
    language: Language
    category: str                 # e.g. "rename", "move", "extract_method"
    fixture_dir: Path             # source files to copy into the workdir
    instructions: str             # task description shown to the model
    oracle_cmd: list[str]         # command run inside workdir; exit 0 == pass
    files_in_context: list[str] = field(default_factory=list)  # primary files to surface


@dataclass
class EditResult:
    """Output contract for a code-editing trial."""

    workdir: Path
    passed: bool
    oracle_returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class EditScore:
    """Computed metrics for one edit trial."""

    passed: bool
    returncode: int

    def as_extra(self) -> dict[str, int | bool]:
        return {"oracle_returncode": self.returncode, "passed": self.passed}


def score(result: EditResult) -> EditScore:
    """Score an EditResult. Scoring is binary on oracle exit code."""
    return EditScore(passed=result.passed, returncode=result.oracle_returncode)
