"""Selectors: pluggable ranking strategies used by approaches.

A Selector picks top-k items from a list (Toolboxes or Tools) given a query
string. Each selector tracks its own cost + latency in a PipelineStep, so an
approach using it can attribute the inner cost.

Naming convention for selector ids — these surface in approach ids like
`toolbox_preselect:bm25` or `tool_retrieval:embed-openai-small`:
  - bm25
  - embed-local                 (sentence-transformers MiniLM)
  - embed-openai-small
  - embed-openai-large
  - llm-haiku                   (claude-haiku-4-5)
  - llm-gpt-mini                (gpt-5.4-mini)
"""

from .base import Selectable, Selection, Selector
from .bm25 import BM25Selector
from .llm import LLMSelector
from .local_embed import LocalEmbedSelector
from .openai_embed import OpenAIEmbedSelector

SELECTORS: dict[str, object] = {
    "bm25": BM25Selector,
    "embed-local": lambda: LocalEmbedSelector(),
    "embed-openai-small": lambda: OpenAIEmbedSelector("text-embedding-3-small"),
    "embed-openai-large": lambda: OpenAIEmbedSelector("text-embedding-3-large"),
    "llm-haiku": lambda: LLMSelector("claude-haiku-4-5"),
    "llm-gpt-mini": lambda: LLMSelector("gpt-5.4-mini"),
}


def get_selector(selector_id: str) -> Selector:
    if selector_id not in SELECTORS:
        raise KeyError(f"Unknown selector: {selector_id!r}. Known: {sorted(SELECTORS)}")
    factory = SELECTORS[selector_id]
    return factory() if callable(factory) else factory()


__all__ = ["Selector", "Selection", "Selectable", "get_selector", "SELECTORS"]
