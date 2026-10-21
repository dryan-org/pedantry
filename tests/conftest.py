import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from pedantry import __version__
from pedantry.cli import app

if TYPE_CHECKING:
    from collections.abc import Callable

V1 = Path(__file__).parent / "fixtures" / "v1"


@dataclass
class Result:
    exit_code: int
    output: str


@pytest.fixture
def pedantry() -> Callable[..., Result]:
    """Run the CLI in-process: ``pedantry("sync", "--path", str(repo))``."""
    runner = CliRunner()

    def run(*args: str) -> Result:
        result = runner.invoke(app, list(args))
        return Result(result.exit_code, result.output)

    return run


@pytest.fixture
def version() -> str:
    return __version__


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[..., Path]:
    """Create a fixture repo from {path: text}; ``git=True`` also runs git init."""

    def build(files: dict[str, str] | None = None, *, git_init: bool = False) -> Path:
        root = tmp_path / "repo"
        root.mkdir(exist_ok=True)
        write(root, files or {})
        if git_init:
            git(root, "init", "-q")
        return root

    return build


@pytest.fixture
def fake_npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put an ``npm`` on PATH that records its arguments and adds the devDependency."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "npm.log"
    script = bin_dir / "npm"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        "python3 - <<'PY'\n"
        "import json\n"
        'data = json.load(open("package.json"))\n'
        'data.setdefault("devDependencies", {})["@dryan/pedantry"] = "github:fake"\n'
        'json.dump(data, open("package.json", "w"), indent=2)\n'
        "PY\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log
