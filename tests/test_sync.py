import json
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Result, write

MAKE = Callable[..., Path]
CLI = Callable[..., Result]

PYPROJECT = '[project]\nname = "demo"\nversion = "0.1.0"\n'
PACKAGE = '{\n  "name": "demo",\n  "private": true\n}\n'

# type -> (files the fixture repo starts with, hooks expected, pyproject block?)
CASES: dict[str, tuple[dict[str, str], set[str], bool]] = {
    "python": ({"pyproject.toml": PYPROJECT}, {"ruff-check", "vulture"}, True),
    "typescript": (
        {"package.json": PACKAGE, "tsconfig.json": "{}\n", "src/a.ts": "export {};\n"},
        {"eslint"},
        False,
    ),
    "javascript": ({"package.json": PACKAGE, "a.js": "\n"}, {"eslint"}, False),
    "css": ({"package.json": PACKAGE, "a.css": "a {}\n"}, {"stylelint"}, False),
    "django": (
        {"pyproject.toml": PYPROJECT, "manage.py": "\n"},
        {"ruff-check", "vulture", "django-upgrade", "eslint", "stylelint"},
        True,
    ),
}
ALL_HOOKS = {
    "eslint",
    "stylelint",
    "ruff-format",
    "ruff-check",
    "vulture",
    "django-upgrade",
}


def hooks_in(text: str) -> set[str]:
    return {hook for hook in ALL_HOOKS if f"\n    {hook}:\n" in text}


@pytest.mark.parametrize("kind", CASES)
def test_sync_writes_managed_files_for_type(
    kind: str, make_repo: MAKE, pedantry: CLI, version: str
) -> None:
    files, hooks, has_block = CASES[kind]
    root = make_repo(files)

    result = pedantry("sync", "--path", str(root), "--type", kind)
    assert result.exit_code == 0, result.output

    stamp = f"pedantry {version}: managed by pedantry sync, do not edit"
    lefthook = (root / "lefthook.yml").read_text()
    assert stamp in lefthook
    assert "prettier:" in lefthook
    assert hooks_in(lefthook) >= hooks
    assert hooks_in(lefthook) <= hooks | {"ruff-format"}
    assert "uv run ruff" in lefthook or kind in {"typescript", "javascript", "css"}

    assert stamp in (root / ".editorconfig").read_text()
    assert ".pedantry" in (root / ".prettierignore").read_text().splitlines()
    agents = (root / ".pedantry" / "AGENTS.md").read_text()
    assert stamp in agents
    assert "Do Not Edit Pedantry-Managed Files" in agents

    pyproject = (root / "pyproject.toml").read_text() if has_block else ""
    assert ("# >>> pedantry" in pyproject) is has_block
    if has_block:
        data = tomllib.loads(pyproject)
        assert data["tool"]["ruff"]["line-length"] == 88
        assert "E" in data["tool"]["ruff"]["lint"]["select"]
        assert data["tool"]["vulture"]["min_confidence"] == 80
        assert ("django-upgrade" in data["tool"]) is (kind == "django")
        assert data["tool"]["pedantry"]["version"] == version
        assert (root / "pedantry.toml").exists() is False
    else:
        pin = tomllib.loads((root / "pedantry.toml").read_text())
        assert pin == {"version": version, "types": [kind]}


@pytest.mark.parametrize("kind", CASES)
def test_sync_twice_changes_nothing(kind: str, make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo(CASES[kind][0])
    pedantry("sync", "--path", str(root), "--type", kind)
    first = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}

    again = pedantry("sync", "--path", str(root), "--json")

    assert json.loads(again.output)["changes"] == []
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == first


@pytest.mark.parametrize("kind", CASES)
def test_check_passes_after_sync(kind: str, make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo(CASES[kind][0])
    pedantry("sync", "--path", str(root), "--type", kind)

    result = pedantry("check", "--path", str(root))

    assert result.exit_code == 0, result.output


def test_sync_uses_the_pinned_types_when_type_is_omitted(
    make_repo: MAKE, pedantry: CLI, version: str
) -> None:
    root = make_repo(
        {
            "pyproject.toml": PYPROJECT
            + f'\n[tool.pedantry]\nversion = "{version}"\ntypes = ["python"]\n'
        }
    )

    result = pedantry("sync", "--path", str(root))

    assert result.exit_code == 0, result.output
    assert "uv run ruff check" in (root / "lefthook.yml").read_text()


def test_sync_without_pin_or_type_fails(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})

    result = pedantry("sync", "--path", str(root))

    assert result.exit_code == 2
    assert "--type" in result.output


def test_dry_run_writes_nothing(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})

    result = pedantry("sync", "--path", str(root), "--type", "python", "--dry-run")

    assert result.exit_code == 0
    assert "would write lefthook.yml" in result.output
    assert sorted(p.name for p in root.iterdir()) == ["pyproject.toml"]
    assert (root / "pyproject.toml").read_text() == PYPROJECT


# ------------------------------------------------------------------ check


@pytest.mark.parametrize(
    ("path", "edit"),
    [
        ("lefthook.yml", lambda text: text.replace("prettier:", "prettier-x:")),
        (".pedantry/AGENTS.md", lambda text: text + "\nmy rule\n"),
        (
            ".editorconfig",
            lambda text: text.replace("indent_size = 4", "indent_size = 8"),
        ),
        (".prettierignore", lambda text: text.replace("node_modules", "modules")),
        (
            "pyproject.toml",
            lambda text: text.replace("line-length = 88", "line-length = 100"),
        ),
    ],
)
def test_check_detects_drift_in_each_managed_file(
    path: str, edit: Callable[[str], str], make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})
    pedantry("sync", "--path", str(root), "--type", "python")
    (root / path).write_text(edit((root / path).read_text()))

    result = pedantry("check", "--path", str(root), "--json")

    assert result.exit_code == 1
    report = json.loads(result.output)
    assert report["ok"] is False
    assert [change["path"] for change in report["changes"]] == [path]


def test_check_reports_a_missing_file(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})
    pedantry("sync", "--path", str(root), "--type", "python")
    (root / "lefthook.yml").unlink()

    result = pedantry("check", "--path", str(root))

    assert result.exit_code == 1
    assert "lefthook.yml (missing)" in result.output


def test_check_ignores_edits_outside_the_managed_parts(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})
    pedantry("sync", "--path", str(root), "--type", "python")
    for name, extra in {
        "pyproject.toml": "\n[tool.ruff.lint.isort]\nforce-single-line = true\n",
        ".editorconfig": "\n[*.yml]\nindent_size = 2\n",
        ".prettierignore": "\nmy-generated/\n",
    }.items():
        with (root / name).open("a") as handle:
            handle.write(extra)

    result = pedantry("check", "--path", str(root))

    assert result.exit_code == 0, result.output


def test_sync_keeps_everything_outside_the_markers(
    make_repo: MAKE, pedantry: CLI
) -> None:
    original = (
        PYPROJECT
        + "\n[tool.coverage.run]\nbranch = true\n"
        + '\n[tool.ruff.lint.isort]\nknown-first-party = ["demo"]\n'
    )
    root = make_repo(
        {
            "pyproject.toml": original,
            ".editorconfig": "root = true\n\n[*.yml]\nindent_size = 2\n",
            ".prettierignore": "my-generated/\n",
        }
    )

    result = pedantry("sync", "--path", str(root), "--type", "python")

    assert result.exit_code == 0, result.output
    pyproject = (root / "pyproject.toml").read_text()
    assert pyproject.startswith(PYPROJECT)
    assert "[tool.coverage.run]\nbranch = true" in pyproject
    assert 'known-first-party = ["demo"]' in pyproject
    assert "[*.yml]\nindent_size = 2" in (root / ".editorconfig").read_text()
    assert "my-generated/" in (root / ".prettierignore").read_text()


# ---------------------------------------------------------------- the pin


def test_sync_refuses_a_pin_for_another_version(
    make_repo: MAKE, pedantry: CLI, version: str
) -> None:
    root = make_repo({"pedantry.toml": 'version = "1.2.3"\ntypes = ["css"]\n'})

    result = pedantry("sync", "--path", str(root))

    assert result.exit_code == 2
    assert "pins pedantry 1.2.3" in result.output
    assert f"{version} is running" in result.output
    assert "@v1.2.3" in result.output
    assert pedantry("check", "--path", str(root)).exit_code == 2


def test_sync_upgrade_moves_the_pin(
    make_repo: MAKE, pedantry: CLI, version: str
) -> None:
    root = make_repo({"pedantry.toml": 'version = "1.2.3"\ntypes = ["css"]\n'})

    result = pedantry("sync", "--path", str(root), "--upgrade")

    assert result.exit_code == 0, result.output
    assert tomllib.loads((root / "pedantry.toml").read_text())["version"] == version
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_pin_in_pyproject_keeps_other_tool_pedantry_formatting(
    make_repo: MAKE, pedantry: CLI, version: str
) -> None:
    pin = f'[tool.pedantry]\n# my note\nversion = "{version}"\ntypes = ["python"]\n'
    root = make_repo({"pyproject.toml": PYPROJECT + "\n" + pin})

    pedantry("sync", "--path", str(root))

    assert pin in (root / "pyproject.toml").read_text()


def test_unknown_type_in_the_pin_is_an_error(
    make_repo: MAKE, pedantry: CLI, version: str
) -> None:
    root = make_repo({"pedantry.toml": f'version = "{version}"\ntypes = ["cobol"]\n'})

    result = pedantry("sync", "--path", str(root))

    assert result.exit_code == 2
    assert "cobol" in result.output


def test_type_option_updates_the_pin(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})
    pedantry("sync", "--path", str(root), "--type", "python")

    pedantry("sync", "--path", str(root), "--type", "python", "--type", "css")

    pin = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["pedantry"]
    assert pin["types"] == ["python", "css"]
    assert "stylelint:" in (root / "lefthook.yml").read_text()


# -------------------------------------------------------------- safeguards


def test_sync_refuses_to_overwrite_an_unmanaged_lefthook(
    make_repo: MAKE, pedantry: CLI
) -> None:
    custom = "pre-commit:\n  commands:\n    mine:\n      run: echo hi\n"
    root = make_repo({"pyproject.toml": PYPROJECT, "lefthook.yml": custom})

    result = pedantry("sync", "--path", str(root), "--type", "python")

    assert result.exit_code == 2
    assert "pedantry migrate" in result.output
    assert (root / "lefthook.yml").read_text() == custom
    assert (
        pedantry("sync", "--path", str(root), "--type", "python", "--force").exit_code
        == 0
    )
    assert "managed by pedantry sync" in (root / "lefthook.yml").read_text()


def test_a_managed_table_defined_outside_the_block_is_reported(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {"pyproject.toml": PYPROJECT + "\n[tool.ruff]\nline-length = 120\n"}
    )

    result = pedantry("sync", "--path", str(root), "--type", "python")

    assert result.exit_code == 2
    assert "pedantry migrate" in result.output
    assert "keep" in result.output
    assert "line-length = 120" in (root / "pyproject.toml").read_text()


def test_keep_leaves_a_table_to_the_repo(
    make_repo: MAKE, pedantry: CLI, version: str
) -> None:
    root = make_repo(
        {
            "pyproject.toml": PYPROJECT
            + "\n[tool.ruff]\nline-length = 120\n"
            + f'\n[tool.pedantry]\nversion = "{version}"\ntypes = ["python"]\n'
            + 'keep = ["tool.ruff"]\n'
        }
    )

    result = pedantry("sync", "--path", str(root))

    assert result.exit_code == 0, result.output
    data = tomllib.loads((root / "pyproject.toml").read_text())
    assert data["tool"]["ruff"]["line-length"] == 120
    assert data["tool"]["ruff"]["lint"]["select"]
    assert pedantry("check", "--path", str(root)).exit_code == 0


# ----------------------------------------------------------------- vendor


def test_vendor_writes_the_js_configs_locally(
    make_repo: MAKE, pedantry: CLI, version: str
) -> None:
    root = make_repo(
        {"package.json": PACKAGE, "tsconfig.json": "{}\n", "a.css": "a {}\n"}
    )

    result = pedantry(
        "sync", "--path", str(root), "--type", "typescript", "--type", "css", "--vendor"
    )

    assert result.exit_code == 0, result.output
    vendored = root / ".pedantry"
    assert (
        f"pedantry {version}: managed by pedantry sync"
        in (vendored / "eslint.config.ts").read_text()
    )
    assert (vendored / "tsconfig.base.json").exists()
    assert (vendored / "stylelint.config.mjs").exists()
    for helper in (
        "merge",
        "vitest",
        "rollup",
        "web-test-runner",
        "custom-elements-manifest",
    ):
        assert (vendored / "helpers" / f"{helper}.js").exists()
    assert "npm install --save-dev eslint" in result.output
    pin = tomllib.loads((root / "pedantry.toml").read_text())
    assert pin["vendor"] is True

    assert pedantry("check", "--path", str(root)).exit_code == 0
    (vendored / "tsconfig.base.json").write_text("{}\n")
    drift = pedantry("check", "--path", str(root), "--json")
    assert (
        json.loads(drift.output)["changes"][0]["path"] == ".pedantry/tsconfig.base.json"
    )


def test_without_vendor_there_are_no_local_js_configs(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"package.json": PACKAGE, "tsconfig.json": "{}\n"})

    pedantry("sync", "--path", str(root), "--type", "typescript")

    assert sorted(p.name for p in (root / ".pedantry").iterdir()) == ["AGENTS.md"]


def test_vendored_copy_matches_the_npm_package_source(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"package.json": PACKAGE})
    pedantry("sync", "--path", str(root), "--type", "javascript", "--vendor")

    source = Path(__file__).parent.parent / "src/pedantry/data/js/eslint.js"
    vendored = (root / ".pedantry/eslint.config.ts").read_text()

    assert vendored.endswith(source.read_text())


def test_write_helper_creates_parents(tmp_path: Path) -> None:
    write(tmp_path, {"a/b/c.txt": "x"})
    assert (tmp_path / "a/b/c.txt").read_text() == "x"


def test_this_repo_is_in_sync_with_its_own_pin(pedantry: CLI) -> None:
    root = Path(__file__).parent.parent

    result = pedantry("check", "--path", str(root))

    assert result.exit_code == 0, result.output
