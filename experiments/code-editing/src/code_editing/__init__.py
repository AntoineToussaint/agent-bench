"""code-editing: experimental harness for comparing LLM code-edit formats."""

__version__ = "0.1.0"


def main() -> None:
    from code_editing.cli import app

    app()
