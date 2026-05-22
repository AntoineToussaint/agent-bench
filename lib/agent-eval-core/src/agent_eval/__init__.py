"""agent-eval-core: domain-agnostic plumbing for LLM evaluation experiments.

What this gives you:
  - Model clients (Anthropic, OpenAI) with consistent interface + provider quirks fixed
  - Sweep runner: iterate (model x condition x task), aggregate, persist
  - Budget tracking: cap total spend in USD, halt on overrun
  - Pricing: per-model $/Mtok with Jan 2026 prices
  - Transcripts: JSON dump format + inspector
  - Reports: CSV + markdown pivot tables, pass matrices

What it does NOT give you:
  - Anything domain-specific (formats, tools, oracles, retrievers, metrics)
  - You bring your own Trial function — (model, condition, task) -> RunRecord
"""

from agent_eval.types import (
    AssistantMessage,
    ModelClient,
    RunRecord,
    ToolCall,
    ToolResult,
    Transcript,
    TurnUsage,
)
from agent_eval.models import make_client, MODELS
from agent_eval.pricing import cost_usd, price_table
from agent_eval.sweep import Sweep, Budget
from agent_eval.transcripts import dump_transcript, load_transcript, summarize_transcript

__all__ = [
    "AssistantMessage",
    "Budget",
    "MODELS",
    "ModelClient",
    "RunRecord",
    "Sweep",
    "ToolCall",
    "ToolResult",
    "Transcript",
    "TurnUsage",
    "cost_usd",
    "dump_transcript",
    "load_transcript",
    "make_client",
    "price_table",
    "summarize_transcript",
]

__version__ = "0.1.0"
