"""Rebuild src/pedantry/data/legacy.json from pedantry's git history.

Fingerprints every unit (lefthook command, pyproject table, editorconfig
section, tsconfig option, .prettierignore line, whole AGENTS.md) of the files
that pedantry v1 copied into repos, at every commit up to --rev. It also runs
each historical setup-pedantry.py to capture the lefthook.yml it generated.

Run from the repo root:  uv run python scripts/build_legacy.py --rev fcc9a63
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Annotated

import typer

from pedantry import legacy

OUTPUT = Path("src/pedantry/data/legacy.json")
# Where each v1 file lived in history (AGENTS.md moved in v2).
FILES = {
    "lefthook": ("lefthook.yml", legacy.lefthook_units),
    "pyproject": ("pyproject.toml", legacy.pyproject_units),
    "editorconfig": (".editorconfig", legacy.editorconfig_units),
    "tsconfig": ("tsconfig.json", legacy.tsconfig_units),
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def revisions(rev: str, path: str) -> list[str]:
    return git("log", "--format=%h", rev, "--", path).split()


def show(rev: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{rev}:{path}"], capture_output=True, text=True
    )
    return result.stdout if result.returncode == 0 else None


def add(units: dict[str, set[str]], found: dict[str, str]) -> None:
    for name, value in found.items():
        if name.startswith("project") or name.startswith("dependency-groups"):
            continue
        units[name].add(value)


def generated_lefthooks(rev: str) -> list[str]:
    """lefthook.yml as written by each historical setup-pedantry.py."""
    outputs: list[str] = []
    for script_rev in revisions(rev, "setup-pedantry.py"):
        source = show(script_rev, "setup-pedantry.py")
        if source is None:
            continue
        for types in (
            ["python"],
            ["typescript"],
            ["django"],
            ["css", "javascript"],
            ["python", "typescript", "css", "django"],
        ):
            with tempfile.TemporaryDirectory() as work:
                script = Path(work) / "setup_old.py"
                script.write_text(source)
                spec = importlib.util.spec_from_file_location("setup_old", script)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(module)
                    old_cwd = Path.cwd()
                    os.chdir(work)
                    try:
                        module.generate_lefthook(types)
                        outputs.append((Path(work) / "lefthook.yml").read_text())
                    finally:
                        os.chdir(old_cwd)
                except Exception as err:  # old script versions differ; best effort
                    print(f"skip setup {script_rev} {types}: {err}", file=sys.stderr)
    return outputs


def main(rev: Annotated[str, typer.Option(help="Last v1 commit to include.")]) -> None:
    table: dict[str, object] = {"rev": rev}
    for kind, (path, extract) in FILES.items():
        units: dict[str, set[str]] = defaultdict(set)
        for old in revisions(rev, path):
            text = show(old, path)
            if text is not None:
                add(units, extract(text))
        if kind == "lefthook":
            for text in generated_lefthooks(rev):
                add(units, extract(text))
        table[kind] = {name: sorted(values) for name, values in sorted(units.items())}

    lines: set[str] = set()
    for old in revisions(rev, ".prettierignore"):
        text = show(old, ".prettierignore")
        if text is not None:
            lines |= {line.strip() for line in text.splitlines() if line.strip()}
    table["prettierignore"] = sorted(lines)

    agents: set[str] = set()
    for path in ("AGENTS.md",):
        for old in revisions(rev, path):
            text = show(old, path)
            if text is not None:
                agents.add(legacy.agents_digest(text))
    table["agents"] = sorted(agents)

    OUTPUT.write_text(
        json.dumps(table, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    typer.run(main)
