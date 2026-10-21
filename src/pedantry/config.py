"""The version pin: ``[tool.pedantry]`` in pyproject.toml or ``pedantry.toml``."""

import tomllib
from typing import TYPE_CHECKING

from pedantry.formats import join_toml, split_toml
from pedantry.model import PIN_FILE, PedantryError, Pin, ProjectType

if TYPE_CHECKING:
    from pathlib import Path


def parse_pin(table: dict[str, object], source: str) -> Pin:
    version = table.get("version")
    types = table.get("types")
    if not isinstance(version, str) or not isinstance(types, list):
        raise PedantryError(f'{source}: needs `version = "x.y.z"` and `types = [...]`')
    try:
        parsed = [ProjectType(str(item)) for item in types]
    except ValueError as err:
        valid = ", ".join(t.value for t in ProjectType)
        raise PedantryError(f"{source}: {err} (valid types: {valid})") from err
    keep = table.get("keep", [])
    if not isinstance(keep, list):
        raise PedantryError(f"{source}: `keep` must be a list of table names")
    tools = table.get("tools")
    if tools is not None and not isinstance(tools, list):
        raise PedantryError(f"{source}: `tools` must be a list of tool names")
    return Pin(
        version=version,
        types=parsed,
        vendor=bool(table.get("vendor", False)),
        keep=[str(item) for item in keep],
        tools=None if tools is None else [str(item) for item in tools],
    )


def pin_source(root: Path) -> str | None:
    """Where the pin lives: ``pedantry.toml`` wins, then pyproject.toml."""
    if (root / PIN_FILE).is_file():
        return PIN_FILE
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        if "pedantry" in data.get("tool", {}):
            return "pyproject.toml"
    return None


def load_pin(root: Path) -> Pin | None:
    source = pin_source(root)
    if source is None:
        return None
    data = tomllib.loads((root / source).read_text(encoding="utf-8"))
    table = data if source == PIN_FILE else data["tool"]["pedantry"]
    return parse_pin(table, source)


def render_pin_table(pin: Pin, *, header: bool) -> str:
    types = ", ".join(f'"{t.value}"' for t in pin.types)
    lines = ["[tool.pedantry]"] if header else []
    lines += [f'version = "{pin.version}"', f"types = [{types}]"]
    if pin.vendor:
        lines.append("vendor = true")
    if pin.keep:
        lines.append("keep = [" + ", ".join(f'"{k}"' for k in pin.keep) + "]")
    if pin.tools is not None:
        lines.append("tools = [" + ", ".join(f'"{t}"' for t in pin.tools) + "]")
    return "\n".join(lines)


def render_pin_file(pin: Pin) -> str:
    return (
        "# Pins the pedantry version for this repo. Edit `version`, then run\n"
        "# `pedantry sync --upgrade` with that version.\n"
        + render_pin_table(pin, header=False)
        + "\n"
    )


def put_pin_in_pyproject(text: str, pin: Pin) -> str:
    """Write the pin into ``[tool.pedantry]``, leaving the rest of the text alone."""
    sections = split_toml(text)
    existing = next((s for s in sections if s.header == "tool.pedantry"), None)
    rendered = render_pin_table(pin, header=True)
    if existing is not None:
        if existing.value() == _as_table(pin):
            return text
        # Keep the blank and comment lines after the last key: they may be the
        # start of the managed block, which belongs to this section's text.
        last = max(
            n
            for n, line in enumerate(existing.lines)
            if line.strip() and not line.strip().startswith("#")
        )
        existing.lines = rendered.split("\n") + existing.lines[last + 1 :]
        return join_toml(sections)
    base = text if text.endswith("\n") or not text else text + "\n"
    spacer = "\n" if base and not base.endswith("\n\n") else ""
    return base + spacer + rendered + "\n"


def _as_table(pin: Pin) -> dict[str, object]:
    table: dict[str, object] = {
        "version": pin.version,
        "types": [t.value for t in pin.types],
    }
    if pin.vendor:
        table["vendor"] = True
    if pin.keep:
        table["keep"] = list(pin.keep)
    if pin.tools is not None:
        table["tools"] = list(pin.tools)
    return table
