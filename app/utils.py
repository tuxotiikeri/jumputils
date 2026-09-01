"""Small filesystem utilities shared by command-line and reporting code."""

from pathlib import Path


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
