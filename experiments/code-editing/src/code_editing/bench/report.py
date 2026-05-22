"""Thin re-export of agent_eval.reports for backwards compatibility.

The report helpers live in agent-eval-core. This shim exists so existing
imports (`from code_editing.bench.report import write_csv, write_markdown`)
keep working without churn.
"""

from agent_eval.reports import (  # noqa: F401
    CSV_COLUMNS,
    summarize_markdown,
    write_csv,
    write_markdown,
)
