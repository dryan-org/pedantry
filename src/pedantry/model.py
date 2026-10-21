"""Shared types and constants."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class ProjectType(StrEnum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    CSS = "css"
    DJANGO = "django"


# Types that pull in other types' tooling.
IMPLIED: dict[ProjectType, frozenset[ProjectType]] = {
    ProjectType.DJANGO: frozenset(
        {ProjectType.PYTHON, ProjectType.JAVASCRIPT, ProjectType.CSS}
    ),
}

PIN_FILE = "pedantry.toml"
BLOCK_BEGIN = "# >>> pedantry"
BLOCK_END = "# <<< pedantry"
MANAGED_PHRASE = "managed by pedantry sync, do not edit"


def effective(
    types: frozenset[ProjectType] | set[ProjectType],
) -> frozenset[ProjectType]:
    """Expand a repo's declared types with the types they imply."""
    result = set(types)
    for declared in types:
        result |= IMPLIED.get(declared, frozenset())
    return frozenset(result)


@dataclass
class Pin:
    """What a repo pins: the pedantry version and its project types."""

    version: str
    types: list[ProjectType]
    vendor: bool = False
    # Managed pyproject tables the repo keeps for itself, e.g. "tool.ruff.lint".
    keep: list[str] = field(default_factory=list)


@dataclass
class Change:
    """One file that sync would write (or that check found out of date)."""

    path: str
    old: str | None
    new: str

    @property
    def status(self) -> str:
        return "missing" if self.old is None else "differs"


class PedantryError(Exception):
    """A user-facing failure: printed without a traceback."""


def read_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None
