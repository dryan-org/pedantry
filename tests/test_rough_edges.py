"""Fixes for rough edges found in the v2.0.0 pilot migrations."""

import json
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import V1, Result, git
from test_migrate import add_submodule

MAKE = Callable[..., Path]
CLI = Callable[..., Result]

PYPROJECT = '[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n'
VULTURE = (
    "[tool.vulture]\n"
    "min_confidence = 80\n\n"
    "ignore_names = [\n"
    '    "*_test.py",\n'
    '    "test_*.py",\n'
    "]\n\n"
    "exclude = [\n"
    '    ".venv/",\n'
    '    "venv/",\n'
    '    "node_modules/",\n'
    '    "migrations/",\n'
    "]\n"
)


def migrate(pedantry: CLI, root: Path, *args: str) -> Result:
    return pedantry("migrate", "--path", str(root), "--skip-npm", *args)


# ------------------------------------------------------------ 1. TypeScript 7


@pytest.mark.parametrize(
    ("spec", "scoped"),
    [("~7.0.0", True), ("^7", True), (">=7.0.0", True), ("~6.0.0", False)],
)
def test_the_eslint_hook_skips_typescript_files_on_typescript_7(
    spec: str, scoped: bool, make_repo: MAKE, pedantry: CLI
) -> None:
    package = {"name": "d", "devDependencies": {"typescript": spec}}
    root = make_repo(
        {
            "package.json": json.dumps(package),
            "a.ts": "export {};\n",
            "eslint.config.ts": "export default [];\n",
        }
    )

    assert pedantry("sync", "--path", str(root), "--type", "typescript").exit_code == 0

    lefthook = (root / "lefthook.yml").read_text()
    if scoped:
        assert 'glob: "*.{js,json}"' in lefthook
        assert "typescript-eslint cannot run on TypeScript 7" in lefthook
    else:
        assert 'glob: "*.{js,ts,json}"' in lefthook
        assert "Lint JavaScript and TypeScript" in lefthook
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_migrate_reports_typescript_7(make_repo: MAKE, pedantry: CLI) -> None:
    package = {"name": "d", "devDependencies": {"typescript": "~7.0.0"}}
    root = make_repo({"package.json": json.dumps(package), "a.ts": "export {};\n"})

    result = migrate(pedantry, root, "--type", "typescript")

    assert "asks for TypeScript 7" in result.output
    assert "typescript-eslint cannot run" in result.output


def test_migrate_does_not_flag_the_eslint_hook_as_a_repo_edit_on_typescript_7(
    make_repo: MAKE, pedantry: CLI
) -> None:
    package = {"name": "d", "devDependencies": {"typescript": "~7.0.0"}}
    root = make_repo(
        {
            "package.json": json.dumps(package),
            "a.ts": "export {};\n",
            "eslint.config.ts": "export default [];\n",
        }
    )
    pedantry("sync", "--path", str(root), "--type", "typescript")

    result = migrate(pedantry, root)

    assert not (root / "lefthook-local.yml").exists()
    assert "moved to lefthook-local.yml" not in result.output


# ------------------------------------------------- 2. pyproject comments, order


def test_migrate_drops_the_comments_of_a_dropped_table_and_keeps_order(
    make_repo: MAKE, pedantry: CLI
) -> None:
    text = (
        "# Demo project\n"
        "# Header comments stay\n"
        "\n"
        f"{PYPROJECT}\n"
        "# Pyupgrade is redundant\n"
        "# with ruff\n"
        "[tool.pyupgrade]\n"
        "\n"
        "# Vulture settings\n"
        f"{VULTURE}\n"
        "# Mine\n"
        "[tool.mine]\n"
        "x = 1\n"
        "\n"
        "[tool.uv.sources]\n"
        "y = 2\n"
    )
    root = make_repo({"pyproject.toml": text})

    assert migrate(pedantry, root, "--type", "python").exit_code == 0

    out = (root / "pyproject.toml").read_text()
    assert out.startswith("# Demo project\n# Header comments stay\n")
    assert "[tool.pyupgrade]" not in out
    assert "Pyupgrade is redundant" not in out
    assert "Vulture settings" not in out
    assert "# Mine\n[tool.mine]" in out
    order = [
        out.index("[project]"),
        out.index("# >>> pedantry"),
        out.index("# <<< pedantry"),
        out.index("[tool.mine]"),
        out.index("[tool.uv.sources]"),
    ]
    assert order == sorted(order)
    tomllib.loads(out)


def test_migrate_puts_the_block_at_the_end_when_no_managed_table_was_dropped(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT + "\n[tool.mine]\nx = 1\n"})

    migrate(pedantry, root, "--type", "python")

    out = (root / "pyproject.toml").read_text()
    assert out.index("[tool.mine]") < out.index("# >>> pedantry")


def test_migrate_keeps_the_block_where_it_already_is(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT + "\n[tool.mine]\nx = 1\n"})
    migrate(pedantry, root, "--type", "python")
    text = (root / "pyproject.toml").read_text()
    moved = text.replace("[tool.mine]\nx = 1\n", "")
    (root / "pyproject.toml").write_text(moved + "\n[tool.mine]\nx = 1\n")
    before = (root / "pyproject.toml").read_text()

    migrate(pedantry, root)

    after = (root / "pyproject.toml").read_text()
    assert after.index("# <<< pedantry") < after.index("[tool.mine]")
    assert before.splitlines() == after.splitlines()


# ------------------------------------------------------------- 3. CLAUDE.md


def test_sync_creates_claude_md_when_agents_md_exists(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT, "AGENTS.md": "# Rules\n"})

    pedantry("sync", "--path", str(root), "--type", "python")

    assert (root / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_sync_leaves_an_existing_claude_md_alone(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {"pyproject.toml": PYPROJECT, "AGENTS.md": "# Rules\n", "CLAUDE.md": "mine\n"}
    )

    pedantry("sync", "--path", str(root), "--type", "python")

    assert (root / "CLAUDE.md").read_text() == "mine\n"


def test_sync_does_not_create_claude_md_without_agents_md(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})

    pedantry("sync", "--path", str(root), "--type", "python")

    assert not (root / "CLAUDE.md").exists()


def test_migrate_creates_claude_md_next_to_an_existing_agents_md(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT, "AGENTS.md": "# Rules\n"})

    result = migrate(pedantry, root, "--type", "python")

    assert (root / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    assert "CLAUDE.md: created" in result.output


def test_migrate_creates_both_when_neither_exists(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})

    migrate(pedantry, root, "--type", "python")

    assert "@.pedantry/AGENTS.md" in (root / "AGENTS.md").read_text()
    assert (root / "CLAUDE.md").read_text() == "@AGENTS.md\n"


def test_migrate_keeps_an_existing_claude_md(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo(
        {"pyproject.toml": PYPROJECT, "AGENTS.md": "# R\n", "CLAUDE.md": "x\n"}
    )

    migrate(pedantry, root, "--type", "python")

    assert (root / "CLAUDE.md").read_text() == "x\n"


# ------------------------------------------------------------------ 4. layout


def managed(root: Path) -> dict[str, dict[str, object]]:
    tool = tomllib.loads((root / "pyproject.toml").read_text())["tool"]
    assert isinstance(tool, dict)
    return tool


def test_a_flat_repo_gets_dot_for_ty_and_no_testpaths(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT, "script.py": "x = 1\n"})

    pedantry("sync", "--path", str(root), "--type", "python")

    tool = managed(root)
    assert tool["ty"]["src"]["include"] == ["."]
    assert "testpaths" not in tool["pytest"]["ini_options"]
    assert tool["pytest"]["ini_options"]["python_files"]


def test_package_directories_are_what_ty_checks_without_src(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "pyproject.toml": PYPROJECT,
            "zeta/__init__.py": "",
            "alpha/__init__.py": "",
            "tests/__init__.py": "",
            "docs/conf.py": "",
            "test_one.py": "",
        }
    )

    pedantry("sync", "--path", str(root), "--type", "python")

    tool = managed(root)
    assert tool["ty"]["src"]["include"] == ["alpha", "zeta"]
    assert tool["pytest"]["ini_options"]["testpaths"] == ["tests"]


def test_src_and_a_test_directory_are_used(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo(
        {
            "pyproject.toml": PYPROJECT,
            "src/pkg/__init__.py": "",
            "pkg2/__init__.py": "",
            "test/test_a.py": "",
        }
    )

    pedantry("sync", "--path", str(root), "--type", "python")

    tool = managed(root)
    assert tool["ty"]["src"]["include"] == ["src"]
    assert tool["pytest"]["ini_options"]["testpaths"] == ["test"]


@pytest.mark.parametrize(
    ("requires", "target", "ty_version"),
    [
        (">=3.12", "py312", "3.12"),
        (">=3.9,<4", "py39", "3.9"),
        ("~=3.11.2", "py311", "3.11"),
        ("==3.10.*", "py310", "3.10"),
        (None, "py313", "3.13"),
    ],
)
def test_python_versions_follow_requires_python(
    requires: str | None,
    target: str,
    ty_version: str,
    make_repo: MAKE,
    pedantry: CLI,
) -> None:
    line = f'requires-python = "{requires}"\n' if requires else ""
    root = make_repo({"pyproject.toml": f'[project]\nname = "d"\n{line}'})

    pedantry("sync", "--path", str(root), "--type", "python")

    tool = managed(root)
    assert tool["ruff"]["target-version"] == target
    assert tool["ty"]["environment"]["python-version"] == ty_version
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_check_notices_a_new_test_directory(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})
    pedantry("sync", "--path", str(root), "--type", "python")
    (root / "tests").mkdir()

    assert pedantry("check", "--path", str(root)).exit_code == 1


# ------------------------------------------------------- 5. new ruff ruleset


def test_migrate_says_the_ruleset_is_new_when_there_was_no_ruff_config(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})

    result = migrate(pedantry, root, "--type", "python")

    assert "had no [tool.ruff]" in result.output
    assert "E, W, F, I, N, UP, B, C4, SIM, TCH, PTH" in result.output
    assert "ruff check --statistics" in result.output
    assert "pedantry sync" in result.output
    # Not softened: the managed rules are all there.
    assert managed(root)["ruff"]["lint"]["select"][0] == "E"


def test_migrate_stays_quiet_about_ruff_when_the_repo_had_a_config(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {"pyproject.toml": PYPROJECT + "\n[tool.ruff]\nline-length = 100\n"}
    )

    result = migrate(pedantry, root, "--type", "python")

    assert "had no [tool.ruff]" not in result.output


def test_migrate_stays_quiet_about_ruff_with_a_ruff_toml(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT, "ruff.toml": "line-length = 90\n"})

    result = migrate(pedantry, root, "--type", "python")

    assert "had no [tool.ruff]" not in result.output


def test_migrate_says_it_only_once_across_runs(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})
    migrate(pedantry, root, "--type", "python")

    result = migrate(pedantry, root)

    assert "had no [tool.ruff]" not in result.output


# ------------------------------------------------- 6. .prettierrc.json5, python


def test_migrate_removes_an_empty_prettierrc_in_a_python_repo(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {"pyproject.toml": PYPROJECT, ".prettierrc.json5": "{\n  // defaults\n}\n"}
    )

    result = migrate(pedantry, root, "--type", "python")

    assert not (root / ".prettierrc.json5").exists()
    assert "deleted the empty .prettierrc.json5" in result.output


def test_migrate_keeps_a_prettierrc_with_options_in_a_python_repo(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {"pyproject.toml": PYPROJECT, ".prettierrc.json5": '{"semi": false}\n'}
    )

    result = migrate(pedantry, root, "--type", "python")

    assert (root / ".prettierrc.json5").exists()
    assert ".prettierrc.json5 sets options" in result.output


# --------------------------------------------------------- 7. editorconfig


def test_migrate_keeps_editorconfig_header_comments_above_the_block(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "pyproject.toml": PYPROJECT,
            ".editorconfig": (V1 / "editorconfig.txt").read_text()
            + "\n[*.yml]\nindent_size = 2\n",
        }
    )

    migrate(pedantry, root, "--type", "python")

    text = (root / ".editorconfig").read_text()
    assert text.startswith("# EditorConfig helps maintain consistent coding styles\n")
    assert text.index("# This file takes precedence") < text.index("# >>> pedantry")
    assert text.index("# <<< pedantry") < text.index("[*.yml]")
    assert text.count("root = true") == 1
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_migrate_editorconfig_without_comments_still_gets_the_block_on_top(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "pyproject.toml": PYPROJECT,
            ".editorconfig": "root = true\n\n[*.yml]\nx = 1\n",
        }
    )

    migrate(pedantry, root, "--type", "python")

    assert (root / ".editorconfig").read_text().startswith("# >>> pedantry")


# ------------------------------------------------------------ 8. submodule


def make_remote_submodule_repo(tmp_path: Path) -> Path:
    """A repo whose .pedantry submodule is declared but not checked out."""
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "-q")
    (upstream / "README.md").write_text("old pedantry\n")
    git(upstream, "add", ".")
    git(upstream, *identity, "commit", "-q", "-m", "x")

    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q")
    (origin / "pyproject.toml").write_text(PYPROJECT)
    git(
        origin,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(upstream),
        ".pedantry",
    )
    git(origin, "add", ".")
    git(origin, *identity, "commit", "-q", "-m", "x")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True
    )
    assert not any((clone / ".pedantry").iterdir())
    return clone


def test_migrate_initializes_an_unchecked_out_submodule(
    tmp_path: Path, pedantry: CLI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    clone = make_remote_submodule_repo(tmp_path)

    result = migrate(pedantry, clone, "--type", "python")

    assert result.exit_code == 0, result.output
    assert "initialized the .pedantry submodule" in result.output
    assert "could not initialize" not in result.output
    assert not (clone / ".gitmodules").exists()


def test_migrate_reports_and_continues_when_the_submodule_cannot_be_fetched(
    tmp_path: Path, pedantry: CLI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    clone = make_remote_submodule_repo(tmp_path)
    shutil.rmtree(tmp_path / "upstream")

    result = migrate(pedantry, clone, "--type", "python")

    assert result.exit_code == 0, result.output
    assert "could not initialize the .pedantry submodule" in result.output
    assert "[tool.ruff]" in (clone / "pyproject.toml").read_text()
    assert not (clone / ".gitmodules").exists()


def test_migrate_does_not_touch_a_submodule_that_is_checked_out(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})
    add_submodule(root)

    result = migrate(pedantry, root, "--type", "python")

    assert "initialized the .pedantry submodule" not in result.output
    assert "could not initialize" not in result.output


# ---------------------------------------------------------------- 9. reports


def test_migrate_points_at_agents_md_lines_that_say_submodule(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "pyproject.toml": PYPROJECT,
            "AGENTS.md": "# R\n\nFrom the pedantry submodule.\n\nSubmodule!\n",
        }
    )

    result = migrate(pedantry, root, "--type", "python")

    assert 'AGENTS.md: mentions "submodule" on line 3, 5' in result.output


def test_migrate_is_quiet_when_agents_md_does_not_say_submodule(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT, "AGENTS.md": "# R\n"})

    result = migrate(pedantry, root, "--type", "python")

    assert 'mentions "submodule"' not in result.output


def test_a_dangling_symlink_into_the_submodule_is_removed_not_restored(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})
    (root / ".vscode").mkdir()
    (root / ".vscode/settings.json").symlink_to("../.pedantry/.vscode/settings.json")
    add_submodule(root)
    git(root, "add", "-f", ".vscode/settings.json")

    result = migrate(pedantry, root, "--type", "python")

    assert not (root / ".vscode/settings.json").is_symlink()
    assert not (root / ".vscode/settings.json").exists()
    assert "removed (nothing to restore)" in result.output
    assert "restore from pedantry" not in result.output
    assert "typechange" not in result.output


# ----------------------------------------------------------- 10. typechanges


def test_migrate_warns_that_symlinks_becoming_files_need_two_commits(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {"pyproject.toml": PYPROJECT, ".pedantry/.editorconfig": "root = true\n"}
    )
    (root / ".editorconfig").symlink_to(".pedantry/.editorconfig")
    add_submodule(root)
    git(root, "add", "-f", ".editorconfig")

    result = migrate(pedantry, root, "--type", "python")

    assert not (root / ".editorconfig").is_symlink()
    assert "typechange" in result.output
    assert "two steps" in result.output
    assert "infra-core 1.2.2" in result.output
    assert ".editorconfig: git sees" in result.output


def test_no_typechange_warning_without_symlinks(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo({"pyproject.toml": PYPROJECT})

    result = migrate(pedantry, root, "--type", "python")

    assert "typechange" not in result.output


# ------------------------------------------ 7. submodule removal is fully staged


def real_submodule_repo(make_repo: MAKE, tmp_path: Path) -> Path:
    """A committed repo with .pedantry as a real submodule (not a faked gitlink)."""
    env = ("-c", "protocol.file.allow=always", "-c", "user.name=t", "-c")
    ident = ("user.email=t@t", "-c", "commit.gpgsign=false")
    sub = tmp_path / "sub"
    sub.mkdir()
    git(sub, "init", "-q")
    (sub / "README.md").write_text("old pedantry\n")
    git(sub, "add", ".")
    git(sub, *env, *ident, "commit", "-qm", "init")
    root = make_repo({"pyproject.toml": PYPROJECT, "AGENTS.md": "# Demo\n"})
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, *env, *ident, "commit", "-qm", "init")
    git(root, *env, *ident, "submodule", "add", "-q", str(sub), ".pedantry")
    git(root, *env, *ident, "commit", "-qm", "add submodule")
    return root


def test_migrate_stages_the_submodule_removal_completely(
    make_repo: MAKE, pedantry: CLI, tmp_path: Path
) -> None:
    root = real_submodule_repo(make_repo, tmp_path)

    result = migrate(pedantry, root, "--type", "python")

    assert result.exit_code == 0, result.output
    status = git(root, "status", "--porcelain").splitlines()
    # The gitlink deletion and .gitmodules removal are staged.
    assert "D  .pedantry" in status
    assert "D  .gitmodules" in status
    assert (root / ".pedantry" / "AGENTS.md").is_file()
    # Everything migrate wrote is staged too: no `git add -A` needed.
    assert git(root, "ls-files", "--", ".pedantry").strip() == ".pedantry/AGENTS.md"
    assert not [line for line in status if line.startswith(("??", " M", " D"))]
