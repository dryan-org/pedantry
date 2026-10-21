"""Compute, apply and verify the files pedantry manages."""

import difflib
import json
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pedantry import __version__
from pedantry.blocks import find_block, put_block, without_block
from pedantry.config import (
    load_pin,
    pin_source,
    put_pin_in_pyproject,
    render_pin_file,
)
from pedantry.content import (
    detect_layout,
    detect_tools,
    editorconfig_block,
    prettierignore_block,
    render_agents,
    render_lefthook,
    render_pyproject_block,
    typescript_major,
    vendored_files,
)
from pedantry.model import (
    MANAGED_PHRASE,
    PIN_FILE,
    Change,
    PedantryError,
    Pin,
    ProjectType,
    effective,
    read_text,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

GIT_URL = "git+https://github.com/dryan-org/pedantry"


def run_command(version: str, args: str) -> str:
    return f"uvx --from {GIT_URL}@v{version} pedantry {args}"


@dataclass
class ResolvedPin:
    pin: Pin
    source: str  # "pyproject.toml" or "pedantry.toml"


def resolve_pin(
    root: Path,
    *,
    types: list[ProjectType] | None = None,
    vendor: bool = False,
    upgrade: bool = False,
) -> ResolvedPin:
    """The pin to sync against: the repo's, adjusted by the command-line options.

    The running pedantry must be the pinned version; ``upgrade`` re-pins to it.
    """
    pin = load_pin(root)
    source = pin_source(root)
    if pin is None or source is None:
        if not types:
            raise PedantryError(
                "no pedantry pin found: pass --type (e.g. --type python) to set one "
                "up, "
                "or add [tool.pedantry] to pyproject.toml / create pedantry.toml"
            )
        wants_pyproject = (root / "pyproject.toml").is_file() or bool(
            effective(frozenset(types)) & {ProjectType.PYTHON}
        )
        return ResolvedPin(
            Pin(version=__version__, types=types, vendor=vendor),
            "pyproject.toml" if wants_pyproject else PIN_FILE,
        )
    if pin.version != __version__:
        if not upgrade:
            raise PedantryError(
                f"this repo pins pedantry {pin.version} but {__version__} is running.\n"
                f"Run: {run_command(pin.version, 'sync')}\n"
                f"To move to {__version__}: pedantry sync --upgrade"
            )
        pin.version = __version__
    if types:
        pin.types = types
    if vendor:
        pin.vendor = True
    return ResolvedPin(pin, source)


NPM_PACKAGE = "@dryan/pedantry"


def npm_pin_command(root: Path, version: str) -> list[str] | None:
    """The npm command that moves ``@dryan/pedantry`` to ``version``, if it needs one.

    None when package.json does not list the package or already points at the tag.
    """
    text = read_text(root / "package.json")
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("devDependencies", "dependencies"):
        group = data.get(key)
        spec = group.get(NPM_PACKAGE) if isinstance(group, dict) else None
        if isinstance(spec, str):
            if spec.endswith(f"#v{version}"):
                return None
            flag = "--save-dev" if key == "devDependencies" else "--save"
            return [
                "npm",
                "install",
                flag,
                f"github:dryan-org/pedantry#v{version}",
            ]
    return None


def run_npm_pin(root: Path, command: list[str]) -> str | None:
    """Run the npm bump; the note to show when npm is not installed, else None."""
    if shutil.which("npm") is None:
        return (
            f"npm is not installed, so {NPM_PACKAGE} was not bumped. Run: "
            + " ".join(command)
        )
    subprocess.run(command, cwd=root, check=True)
    return None


def _validate_pyproject(text: str) -> None:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        raise PedantryError(
            f"pyproject.toml would be invalid ({err}). A table that pedantry manages "
            "is "
            "probably also defined outside the managed block: run `pedantry "
            "migrate`, or "
            "list the table under `keep` in [tool.pedantry]."
        ) from err


def render_pyproject(text: str | None, pin: Pin, *, pin_here: bool, root: Path) -> str:
    out = text or ""
    if pin_here:
        out = put_pin_in_pyproject(out, pin)
    layout = detect_layout(root, text)
    block = render_pyproject_block(pin.version, frozenset(pin.types), pin.keep, layout)
    if block is not None:
        out = put_block(out, block)
    elif find_block(out) is not None:
        out = without_block(out)
    _validate_pyproject(out)
    return out


CLAUDE_IMPORT = "@AGENTS.md\n"


def _exists(root: Path, path: str, read: Callable[[str], str | None]) -> bool:
    """Whether a file is there: in-memory edits and symlinks (even dangling) count."""
    target = root / path
    return read(path) is not None or target.exists() or target.is_symlink()


def _managed(text: str | None) -> bool:
    return text is not None and MANAGED_PHRASE in text


def compute(
    root: Path,
    resolved: ResolvedPin,
    *,
    force: bool = False,
    reader: Callable[[str], str | None] | None = None,
) -> list[Change]:
    """Every managed file whose content differs from what sync would write.

    ``reader`` supplies current file text by repo-relative path (migrate uses it
    to start from its in-memory edits); by default files are read from disk.
    """
    read = reader or (lambda path: read_text(root / path))
    pin = resolved.pin
    types = frozenset(pin.types)
    kinds = effective(types)
    targets: dict[str, str] = {}
    whole: set[str] = set()

    targets[".editorconfig"] = put_block(
        read(".editorconfig"), editorconfig_block(pin.version), at_top=True
    )
    targets[".prettierignore"] = put_block(
        read(".prettierignore"), prettierignore_block(pin.version), at_top=True
    )
    for path, text in {
        "lefthook.yml": render_lefthook(
            pin.version,
            types,
            typescript_major(read("package.json")),
            detect_tools(read),
        ),
        ".pedantry/AGENTS.md": render_agents(pin.version),
    }.items():
        targets[path] = text
        whole.add(path)

    pin_in_pyproject = resolved.source == "pyproject.toml"
    if pin_in_pyproject or ProjectType.PYTHON in kinds:
        targets["pyproject.toml"] = render_pyproject(
            read("pyproject.toml"), pin, pin_here=pin_in_pyproject, root=root
        )
    if not pin_in_pyproject:
        targets[PIN_FILE] = render_pin_file(pin)

    if read("AGENTS.md") is not None and not _exists(root, "CLAUDE.md", read):
        targets["CLAUDE.md"] = CLAUDE_IMPORT

    if pin.vendor:
        for path, text in vendored_files(pin.version, types).items():
            targets[path] = text
            whole.add(path)

    changes: list[Change] = []
    for path, new in targets.items():
        old = read(path)
        if old == new:
            continue
        if path == PIN_FILE and old is not None and load_pin(root) is not None:
            existing = load_pin(root)
            if existing == pin:
                continue
        if path in whole and old is not None and not _managed(old) and not force:
            raise PedantryError(
                f"{path} exists and is not managed by pedantry. Run `pedantry "
                "migrate` to "
                "keep its repo-specific parts, or pass --force to overwrite it."
            )
        changes.append(Change(path, old, new))
    return changes


def apply(root: Path, changes: list[Change]) -> None:
    for change in changes:
        target = root / change.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.new, encoding="utf-8")


def diff(change: Change) -> str:
    return "".join(
        difflib.unified_diff(
            (change.old or "").splitlines(keepends=True),
            change.new.splitlines(keepends=True),
            fromfile=f"a/{change.path}",
            tofile=f"b/{change.path}",
        )
    )
