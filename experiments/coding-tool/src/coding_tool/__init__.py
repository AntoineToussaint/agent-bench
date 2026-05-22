"""coding-tool: experimental harness for comparing LLM code-edit formats."""

__version__ = "0.1.0"


def main() -> None:
    from coding_tool.cli import app

    app()
