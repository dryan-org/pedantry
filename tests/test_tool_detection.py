"""Hooks only for tools the repo has; the npm pin follows sync --upgrade."""

import json
import os
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Result

from pedantry.content import render_lefthook
from pedantry.model import ProjectType

MAKE = Callable[..., Path]
CLI = Callable[..., Result]

PYPROJECT = '[project]\nname = "demo"\nversion = "0.1.0"\n'
PACKAGE = '{\n  "name": "demo",\n  "private": true\n}\n'


def hooks(root: Path) -> set[str]:
    text = (root / "lefthook.yml").read_text()
    names = ("eslint", "stylelint", "vulture", "ruff-check")
    return {name for name in names if f"\n    {name}:\n" in text}


def test_sync_leaves_out_hooks_for_tools_the_repo_lacks(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"package.json": PACKAGE, "pyproject.toml": PYPROJECT})

    result = pedantry(
        "sync",
        "--path",
        str(root),
        "--type",
        "python",
        "--type",
        "typescript",
        "--type",
        "css",
    )

    assert result.exit_code == 0, result.output
    assert hooks(root) == {"ruff-check"}
    assert pedantry("check", "--path", str(root)).exit_code == 0


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"eslint.config.mjs": "export default [];\n"}, {"eslint"}),
        ({"package.json": '{"eslintConfig": {}}'}, {"eslint"}),
        ({"stylelint.config.mjs": "export default {};\n"}, {"stylelint"}),
        ({".stylelintrc.json": "{}\n"}, {"stylelint"}),
        ({"package.json": '{"stylelint": {}}'}, {"stylelint"}),
    ],
)
def test_a_config_file_turns_the_hook_on(
    files: dict[str, str], expected: set[str], make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"package.json": PACKAGE, **files})

    pedantry("sync", "--path", str(root), "--type", "typescript", "--type", "css")

    assert hooks(root) == expected
    assert pedantry("check", "--path", str(root)).exit_code == 0


@pytest.mark.parametrize(
    ("pyproject", "wanted"),
    [
        (PYPROJECT, False),
        (PYPROJECT + '\n[dependency-groups]\ndev = ["vulture>=2.13"]\n', True),
        (PYPROJECT + '\n[project.optional-dependencies]\ndev = ["Vulture"]\n', True),
        (PYPROJECT + '\n[dependency-groups]\ndev = ["vulture-extras"]\n', False),
    ],
)
def test_vulture_needs_a_dependency_or_its_own_table(
    pyproject: str, wanted: bool, make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": pyproject})

    pedantry("sync", "--path", str(root), "--type", "python")

    assert ("vulture" in hooks(root)) is wanted
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_a_kept_vulture_table_turns_the_hook_on(
    make_repo: MAKE, pedantry: CLI, version: str
) -> None:
    root = make_repo(
        {
            "pyproject.toml": PYPROJECT + "\n[tool.vulture]\nmin_confidence = 60\n",
            "pedantry.toml": f'version = "{version}"\ntypes = ["python"]\n'
            'keep = ["tool.vulture"]\n',
        }
    )

    result = pedantry("sync", "--path", str(root))

    assert result.exit_code == 0, result.output
    assert "vulture" in hooks(root)
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_the_managed_vulture_table_does_not_count(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})
    pedantry("sync", "--path", str(root), "--type", "python")

    assert "[tool.vulture]" in (root / "pyproject.toml").read_text()
    assert "vulture" not in hooks(root)
    again = pedantry("sync", "--path", str(root), "--json")
    assert json.loads(again.output)["changes"] == []


def test_check_agrees_with_sync_when_a_tool_appears(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"package.json": PACKAGE})
    pedantry("sync", "--path", str(root), "--type", "javascript")
    assert hooks(root) == set()

    (root / "eslint.config.js").write_text("export default [];\n")

    assert pedantry("check", "--path", str(root)).exit_code == 1
    pedantry("sync", "--path", str(root))
    assert hooks(root) == {"eslint"}
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_migrate_reports_the_hooks_it_left_out(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo({"package.json": PACKAGE, "pyproject.toml": PYPROJECT})

    result = pedantry(
        "migrate",
        "--path",
        str(root),
        "--skip-npm",
        "--type",
        "python",
        "--type",
        "typescript",
        "--type",
        "css",
    )

    assert result.exit_code == 0, result.output
    assert "no `eslint` hook (no ESLint config file found)" in result.output
    assert "no `stylelint` hook" in result.output
    assert "no `vulture` hook" in result.output
    assert hooks(root) == {"ruff-check"}
    assert pedantry("check", "--path", str(root)).exit_code == 0


# ------------------------------------------------------- npm pin on --upgrade


def old_pin_repo(make_repo: MAKE, spec: str) -> Path:
    package = {"name": "d", "devDependencies": {"@dryan/pedantry": spec}}
    return make_repo(
        {
            "package.json": json.dumps(package),
            "pedantry.toml": 'version = "1.0.0"\ntypes = ["typescript"]\n',
        }
    )


def test_sync_upgrade_bumps_the_npm_pin(
    make_repo: MAKE, pedantry: CLI, fake_npm: Path, version: str
) -> None:
    root = old_pin_repo(make_repo, "github:dryan-org/pedantry#v1.0.0")

    result = pedantry("sync", "--path", str(root), "--upgrade")

    assert result.exit_code == 0, result.output
    assert (
        f"install --save-dev github:dryan-org/pedantry#v{version}"
        in fake_npm.read_text()
    )
    assert f"ran npm install --save-dev github:dryan-org/pedantry#v{version}" in (
        result.output
    )


def test_sync_upgrade_dry_run_does_not_run_npm(
    make_repo: MAKE, pedantry: CLI, fake_npm: Path
) -> None:
    root = old_pin_repo(make_repo, "github:dryan-org/pedantry#v1.0.0")

    result = pedantry("sync", "--path", str(root), "--upgrade", "--dry-run")

    assert "would run npm install --save-dev" in result.output
    assert not fake_npm.exists()


def test_sync_without_upgrade_leaves_the_npm_pin_alone(
    make_repo: MAKE, pedantry: CLI, fake_npm: Path, version: str
) -> None:
    root = old_pin_repo(make_repo, f"github:dryan-org/pedantry#v{version}")
    (root / "pedantry.toml").write_text(
        f'version = "{version}"\ntypes = ["typescript"]\n'
    )

    pedantry("sync", "--path", str(root))
    pedantry("sync", "--path", str(root), "--upgrade")

    assert not fake_npm.exists()


def test_sync_upgrade_skips_npm_when_package_json_does_not_list_it(
    make_repo: MAKE, pedantry: CLI, fake_npm: Path
) -> None:
    root = make_repo(
        {
            "package.json": PACKAGE,
            "pedantry.toml": 'version = "1.0.0"\ntypes = ["typescript"]\n',
        }
    )

    pedantry("sync", "--path", str(root), "--upgrade")

    assert not fake_npm.exists()


def test_sync_upgrade_notes_a_missing_npm(
    make_repo: MAKE, pedantry: CLI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = old_pin_repo(make_repo, "github:dryan-org/pedantry#v1.0.0")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", f"{empty}{os.pathsep}")

    result = pedantry("sync", "--path", str(root), "--upgrade")

    assert result.exit_code == 0, result.output
    assert "npm is not installed" in result.output


def test_migrate_bumps_a_listed_npm_pin(
    make_repo: MAKE, pedantry: CLI, fake_npm: Path, version: str
) -> None:
    root = old_pin_repo(make_repo, "github:dryan-org/pedantry#v1.0.0")

    result = pedantry("migrate", "--path", str(root), "--type", "python")

    assert result.exit_code == 0, result.output
    assert f"github:dryan-org/pedantry#v{version}" in fake_npm.read_text()


# ------------------------------------------------ tools recorded in the pin


def test_migrate_keeps_the_vulture_hook_when_its_table_is_absorbed(
    make_repo: MAKE, pedantry: CLI
) -> None:
    vulture = (
        "[tool.vulture]\nmin_confidence = 80\n\n"
        'ignore_names = [\n    "*_test.py",\n    "test_*.py",\n]\n\n'
        'exclude = [\n    ".venv/",\n    "venv/",\n    "node_modules/",\n'
        '    "migrations/",  # Django migrations\n]\n'
    )
    root = make_repo({"pyproject.toml": PYPROJECT + "\n" + vulture})

    result = pedantry("migrate", "--path", str(root), "--type", "python")

    assert result.exit_code == 0, result.output
    assert "vulture" in hooks(root)
    pin = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["pedantry"]
    assert "vulture" in pin["tools"]
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_migrate_records_tools_from_the_old_lefthook_and_configs(
    make_repo: MAKE, pedantry: CLI
) -> None:
    old = (
        "pre-commit:\n  commands:\n    eslint:\n      run: npx eslint\n"
        "    stylelint:\n      run: npx stylelint\n"
    )
    root = make_repo({"package.json": PACKAGE, "lefthook.yml": old})

    result = pedantry(
        "migrate", "--path", str(root), "--skip-npm", "--type", "typescript"
    )

    assert result.exit_code == 0, result.output
    pin = tomllib.loads((root / "pedantry.toml").read_text())
    assert pin["tools"] == ["eslint", "stylelint"]
    assert {"eslint"} <= hooks(root)


def v201_repo(make_repo: MAKE) -> Path:
    managed = render_lefthook("2.0.1", frozenset({ProjectType.TYPESCRIPT}))
    return make_repo(
        {
            "package.json": PACKAGE,
            "lefthook.yml": managed,
            "pedantry.toml": 'version = "2.0.1"\ntypes = ["typescript"]\n',
        }
    )


def test_upgrade_from_a_pin_without_tools_keeps_existing_hooks(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = v201_repo(make_repo)
    assert "eslint" in hooks(root)

    result = pedantry("sync", "--path", str(root), "--upgrade")

    assert result.exit_code == 0, result.output
    assert "eslint" in hooks(root)
    pin = tomllib.loads((root / "pedantry.toml").read_text())
    assert pin["tools"] == ["eslint", "prettier"]
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_removing_a_tool_from_the_pin_drops_its_hook(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = v201_repo(make_repo)
    pedantry("sync", "--path", str(root), "--upgrade")
    pin_file = root / "pedantry.toml"
    pin_file.write_text(
        pin_file.read_text().replace('"eslint", ', "").replace('"eslint"', "")
    )

    assert pedantry("check", "--path", str(root)).exit_code == 1
    pedantry("sync", "--path", str(root))

    assert "eslint" not in hooks(root)
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_adding_a_tool_to_the_pin_adds_its_hook(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo({"package.json": PACKAGE})
    pedantry("sync", "--path", str(root), "--type", "css")
    assert "stylelint" not in hooks(root)
    pin_file = root / "pedantry.toml"
    pin_file.write_text(pin_file.read_text() + 'tools = ["stylelint"]\n')

    pedantry("sync", "--path", str(root))

    assert "stylelint" in hooks(root)
    assert pedantry("check", "--path", str(root)).exit_code == 0
