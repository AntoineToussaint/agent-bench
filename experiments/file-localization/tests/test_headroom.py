"""Unit tests for the Step-2 headroom math (run_config_arms.headroom_analysis).

The headline number drives a build/don't-build decision, so the math is tested
directly — no API, no sweep.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# The script lives under scripts/ (not an importable package), so load it by path.
# Register in sys.modules before exec so @dataclass introspection can resolve
# the module (it looks up cls.__module__ in sys.modules).
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_config_arms.py"
_spec = importlib.util.spec_from_file_location("run_config_arms", _SCRIPT)
rca = importlib.util.module_from_spec(_spec)
sys.modules["run_config_arms"] = rca
_spec.loader.exec_module(rca)


def test_headroom_when_no_single_arm_dominates():
    # arm A wins task t1, arm B wins task t2 → per-task oracle beats either fixed arm.
    composite = {
        "A": {"t1": 1.0, "t2": 0.0},
        "B": {"t1": 0.0, "t2": 1.0},
    }
    cost = {"A": {"t1": 0.01, "t2": 0.01}, "B": {"t1": 0.02, "t2": 0.02}}
    h = rca.headroom_analysis(["A", "B"], composite, cost)
    assert h is not None
    assert h.best_single == 0.5            # each arm averages 0.5
    assert h.oracle_select == 1.0          # pick the winner each task
    assert abs(h.headroom - 0.5) < 1e-9    # real headroom → build the bandit


def test_no_headroom_when_one_arm_dominates_every_task():
    composite = {
        "A": {"t1": 0.9, "t2": 0.8},       # A best on both
        "B": {"t1": 0.3, "t2": 0.2},
    }
    cost = {"A": {"t1": 0.01, "t2": 0.01}, "B": {"t1": 0.01, "t2": 0.01}}
    h = rca.headroom_analysis(["A", "B"], composite, cost)
    assert h.best_single_arm == "A"
    assert abs(h.headroom) < 1e-9          # oracle == best single → don't build


def test_only_compares_tasks_completed_by_every_arm():
    # B never finished t2 (budget cutoff). t2 must be excluded from the fair set.
    composite = {
        "A": {"t1": 1.0, "t2": 1.0},
        "B": {"t1": 0.0},
    }
    cost = {"A": {"t1": 0.01, "t2": 0.01}, "B": {"t1": 0.02}}
    h = rca.headroom_analysis(["A", "B"], composite, cost)
    assert h.completed == ["t1"]           # t2 dropped
    assert h.best_single == 1.0            # A on the one shared task
    assert h.headroom == 0.0


def test_returns_none_when_no_shared_task():
    composite = {"A": {"t1": 1.0}, "B": {"t2": 1.0}}
    cost = {"A": {"t1": 0.01}, "B": {"t2": 0.01}}
    assert rca.headroom_analysis(["A", "B"], composite, cost) is None


def test_returns_none_when_an_arm_has_no_results():
    composite = {"A": {"t1": 1.0}, "B": {}}
    cost = {"A": {"t1": 0.01}, "B": {}}
    assert rca.headroom_analysis(["A", "B"], composite, cost) is None
