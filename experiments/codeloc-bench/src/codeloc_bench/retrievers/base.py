from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Retriever(Protocol):
    """Plug-in interface. Implement these three members for a new retriever.

    `index` is called once per repo+commit; `query` is called once per task.
    The returned list of file paths is what the benchmark scores against the
    gold-patch file set.
    """

    name: str

    def index(self, repo_path: Path) -> object: ...

    def query(self, index: object, query: str, k: int) -> list[str]: ...
