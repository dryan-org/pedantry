"""Fingerprints of the files earlier pedantry versions copied into repos.

``pedantry migrate`` uses them to tell a stale copy of an old pedantry file
(safe to replace) from a deliberate per-repo edit (kept). The table is built
from pedantry's git history by ``scripts/build_legacy.py``.
"""

import json
import tomllib
from functools import cache

from pedantry.content import data_file
from pedantry.formats import (
    digest,
    loads_jsonc,
    parse_lefthook,
    split_editorconfig,
    split_toml,
)


@cache
def table() -> dict[str, object]:
    loaded: dict[str, object] = json.loads(data_file("legacy.json"))
    return loaded


def known(kind: str, unit: str, value_digest: str) -> bool:
    """Whether an older pedantry shipped this unit with exactly this content."""
    units = table().get(kind, {})
    return isinstance(units, dict) and value_digest in units.get(unit, [])


def known_line(line: str) -> bool:
    lines = table().get("prettierignore", [])
    return isinstance(lines, list) and line in lines


def known_agents(text: str) -> bool:
    agents = table().get("agents", [])
    return isinstance(agents, list) and agents_digest(text) in agents


# Unit extractors: shared by the migrate code and the table builder.


def lefthook_units(text: str) -> dict[str, str]:
    return {command.name: command.key() for command in parse_lefthook(text).commands}


def pyproject_units(text: str) -> dict[str, str]:
    units: dict[str, str] = {}
    for section in split_toml(text):
        if section.header is None or section.header.startswith("[["):
            continue
        try:
            units[section.header] = digest(section.value())
        except (tomllib.TOMLDecodeError, KeyError):
            continue
    return units


def editorconfig_units(text: str) -> dict[str, str]:
    return {
        section.header: digest(section.properties())
        for section in split_editorconfig(text)
        if section.header is not None
    }


def tsconfig_units(text: str) -> dict[str, str]:
    data = loads_jsonc(text)
    options = data.get("compilerOptions", {}) if isinstance(data, dict) else {}
    return {key: digest(value) for key, value in options.items()}


def agents_digest(text: str) -> str:
    return digest(text.strip())
