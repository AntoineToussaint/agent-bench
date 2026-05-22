"""Multi-turn execution: simulated tool execution with deterministic failures,
episode-style runner with retry budget, and (later) lesson-store augmentation.

The execution layer extends the one-shot framework to test recovery from
realistic runtime errors (wrong cwd, branch not pushed, etc.) without
actually running git/gh/fs commands.
"""

from .executor import CallResult, execute_call
from .runner import Episode, EpisodeAttempt, run_episode
from .state import Call, FailureTrigger

__all__ = [
    "Call",
    "CallResult",
    "Episode",
    "EpisodeAttempt",
    "FailureTrigger",
    "execute_call",
    "run_episode",
]
