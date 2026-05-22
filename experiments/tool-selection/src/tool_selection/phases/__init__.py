"""Final-shot phase abstractions.

A Phase takes (task, surfaced_tools, model) and produces (final_calls,
final_text, pipeline_steps). The default is OnePhase (current behavior:
one API call surfaces tools and the model emits all tool_use blocks).
Alternatives target specific failure modes:

  - PlanFirstPhase   — same single call, but the prompt forces the model
                       to emit a <plan> block listing every tool call
                       before emitting them. Mitigates the "stopped
                       mid-plan" failure documented in KAMI and Microsoft's
                       Lost-in-Multi-Turn study.
  - TwoPhase         — Phase 1: model sees only (name, description) for
                       surfaced tools, returns ordered list of tool names.
                       Phase 2: one focused call per chosen tool with only
                       that tool's full schema in context, fills args.
                       Parallel by default. Mitigates schema violations
                       and confusable-sibling errors documented in
                       TRAJECT-Bench.
"""

from .base import Phase, PhaseResult
from .one_phase import OnePhase, OnePhaseConfusabilityAware, PlanFirstPhase
from .two_phase import TwoPhase

PHASES: dict[str, object] = {
    "1phase": OnePhase,
    "1phase-plan": PlanFirstPhase,
    "1phase-confuse": OnePhaseConfusabilityAware,
    "2phase": TwoPhase,
    "2phase-args-sonnet": lambda: TwoPhase(args_model="claude-sonnet-4-6"),
    "2phase-sel-haiku-args-sonnet": lambda: TwoPhase(
        selection_model="claude-haiku-4-5", args_model="claude-sonnet-4-6"
    ),
}

__all__ = [
    "Phase",
    "PhaseResult",
    "OnePhase",
    "PlanFirstPhase",
    "OnePhaseConfusabilityAware",
    "TwoPhase",
    "PHASES",
]
