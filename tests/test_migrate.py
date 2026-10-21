import json
import tomllib
from collections.abc import Callable
from pathlib import Path

from conftest import V1, Result, git, write

MAKE = Callable[..., Path]
CLI = Callable[..., Result]

V1_PYPROJECT = (V1 / "pyproject.toml.txt").read_text()
V1_LEFTHOOK = (V1 / "lefthook.yml.txt").read_text()
V1_TSCONFIG = (V1 / "tsconfig.json.txt").read_text()
V1_EDITORCONFIG = (V1 / "editorconfig.txt").read_text()
V1_PRETTIERIGNORE = (V1 / "prettierignore.txt").read_text()
V1_AGENTS = (V1 / "AGENTS.md.txt").read_text()

OLD_ESLINT = """import type { Linter } from "eslint";
import pedantryConfig from "./.pedantry/eslint.config";

const config: Linter.Config[] = [
  ...pedantryConfig,
  {
    ignores: ["dist/**", ".pedantry/**"],
  },
];

export default config;
"""


def add_submodule(root: Path) -> None:
    """Make ``.pedantry`` look like the v1 submodule (a gitlink plus .gitmodules)."""
    git(root, "init", "-q")
    write(
        root,
        {
            ".gitmodules": '[submodule ".pedantry"]\n\tpath = .pedantry\n'
            "\turl = https://github.com/dryan/pedantry.git\n",
            ".pedantry/README.md": "old pedantry\n",
        },
    )
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{'a' * 40},.pedantry")


def tracked(root: Path) -> list[str]:
    return git(root, "ls-files").split()


def v1_repo(make_repo: MAKE) -> Path:
    """A repo shaped like a v1 consumer, with per-repo edits mixed into the copies."""
    custom_lefthook = V1_LEFTHOOK + (
        '\n    # Typecheck\n    tsc:\n      glob: "*.ts"\n      run: npx tsc --noEmit\n'
        "\npre-push:\n  commands:\n    tests:\n      run: npm test\n"
    )
    pyproject = (
        V1_PYPROJECT.replace('select = [\n    "E",', 'select = [\n    "S",\n    "E",')
        + "\n[tool.ruff.lint.isort]\nforce-single-line = true\n"
    )
    tsconfig = V1_TSCONFIG.replace('"outDir": "dist"', '"outDir": "build"').replace(
        '"exclude": [', '"exclude": [".pedantry", '
    )
    root = make_repo(
        {
            "pyproject.toml": pyproject,
            "lefthook.yml": custom_lefthook,
            "tsconfig.json": tsconfig,
            ".editorconfig": V1_EDITORCONFIG + "\n[*.yml]\nindent_size = 2\n",
            ".prettierignore": V1_PRETTIERIGNORE + "my-generated/\n",
            "eslint.config.ts": OLD_ESLINT,
            "package.json": '{\n  "name": "demo",\n  "scripts": {}\n}\n',
            ".prettierrc.json5": "{\n  // defaults only\n}\n",
            "AGENTS.md": "# Demo\n\nRepo rules.\n",
            "src/a.ts": "export {};\n",
        },
        git_init=False,
    )
    add_submodule(root)
    return root


def test_migrate_moves_a_v1_repo_to_v2(
    make_repo: MAKE, pedantry: CLI, version: str, fake_npm: Path
) -> None:
    root = v1_repo(make_repo)

    result = pedantry(
        "migrate", "--path", str(root), "--type", "python", "--type", "typescript"
    )

    assert result.exit_code == 0, result.output

    # The submodule is gone from the index, .gitmodules and disk; nothing is committed.
    assert ".pedantry" not in tracked(root)
    assert not (root / ".gitmodules").exists()
    assert not (root / ".pedantry" / "README.md").exists()
    assert "no commits yet" in git(root, "status").lower()

    # npm dependency added, ESLint import and tsconfig rewired.
    assert "install --save-dev github:dryan-org/pedantry#v" in fake_npm.read_text()
    package = json.loads((root / "package.json").read_text())
    assert package["devDependencies"]["@dryan/pedantry"]
    assert package["prettier"] == "@dryan/pedantry/prettier"
    assert not (root / ".prettierrc.json5").exists()
    eslint = (root / "eslint.config.ts").read_text()
    assert 'from "@dryan/pedantry/eslint"' in eslint
    assert ".pedantry/**" not in eslint
    tsconfig = json.loads((root / "tsconfig.json").read_text())
    assert tsconfig["extends"] == "@dryan/pedantry/tsconfig"
    assert tsconfig["compilerOptions"]["outDir"] == "build"
    assert "strict" not in tsconfig["compilerOptions"]
    assert "paths" in tsconfig["compilerOptions"]
    assert ".pedantry" not in tsconfig["exclude"]

    # Per-repo edits survive.
    local = (root / "lefthook-local.yml").read_text()
    assert "tsc:" in local
    assert "npx tsc --noEmit" in local
    assert "pre-push:" in local
    assert "prettier:" not in local
    lefthook = (root / "lefthook.yml").read_text()
    assert "managed by pedantry sync" in lefthook
    assert "tsc:" not in lefthook
    pyproject = (root / "pyproject.toml").read_text()
    data = tomllib.loads(pyproject)
    assert data["tool"]["ruff"]["lint"]["select"][0] == "S"
    assert data["tool"]["ruff"]["lint"]["isort"]["force-single-line"] is True
    assert data["tool"]["pedantry"]["keep"] == ["tool.ruff.lint"]
    assert "pyupgrade" not in data["tool"]
    assert data["tool"]["pedantry"]["types"] == ["python", "typescript"]
    editorconfig = (root / ".editorconfig").read_text()
    assert editorconfig.count("[*.py]") == 1
    assert editorconfig.index("# <<< pedantry") < editorconfig.index("[*.yml]")
    prettierignore = (root / ".prettierignore").read_text()
    assert prettierignore.count("node_modules") == 1
    assert prettierignore.index("# <<< pedantry") < prettierignore.index(
        "my-generated/"
    )
    agents = (root / "AGENTS.md").read_text()
    assert agents.startswith("# Demo") and agents.rstrip().endswith(
        "@.pedantry/AGENTS.md"
    )
    assert (root / ".pedantry" / "AGENTS.md").exists()

    # The report separates stale copies from kept edits.
    assert "Replaced" in result.output and "Preserved" in result.output
    assert "[tool.ruff.lint] differs from pedantry" in result.output
    assert "command `tsc` moved to lefthook-local.yml" in result.output
    assert "stale copy of an older pedantry" in result.output

    # And the result is a fixed point.
    assert pedantry("check", "--path", str(root)).exit_code == 0
    again = pedantry("sync", "--path", str(root), "--json")
    assert json.loads(again.output)["changes"] == []


def test_migrate_dry_run_changes_nothing(make_repo: MAKE, pedantry: CLI) -> None:
    root = v1_repo(make_repo)
    before = {
        p: p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and ".git/" not in str(p)
    }

    result = pedantry(
        "migrate", "--path", str(root), "--type", "python", "--dry-run", "--skip-npm"
    )

    assert result.exit_code == 0, result.output
    assert "Plan (nothing changed)" in result.output
    assert "lefthook-local.yml" in result.output
    after = {
        p: p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and ".git/" not in str(p)
    }
    assert after == before
    assert ".pedantry" in tracked(root)


def test_migrate_dry_run_json(make_repo: MAKE, pedantry: CLI) -> None:
    root = v1_repo(make_repo)

    result = pedantry(
        "migrate",
        "--path",
        str(root),
        "--type",
        "python",
        "--dry-run",
        "--json",
        "--skip-npm",
    )

    report = json.loads(result.output)
    assert report["dry_run"] is True
    assert "lefthook-local.yml" in report["files"]
    assert any("tsc" in item for item in report["preserved"])


def test_migrate_infers_types(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo(
        {
            "pyproject.toml": '[project]\nname = "d"\n'
            'dependencies = ["django>=5", "django-upgrade"]\n',
            "a.css": "a {}\n",
        }
    )

    result = pedantry("migrate", "--path", str(root), "--skip-npm", "--json")

    assert json.loads(result.output)["types"] == ["django", "css"]


def test_migrate_does_not_mistake_django_upgrade_for_django(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "pyproject.toml": '[project]\nname = "d"\n[dependency-groups]\n'
            'dev = ["django-upgrade"]\n'
        }
    )

    result = pedantry("migrate", "--path", str(root), "--skip-npm", "--json")

    assert json.loads(result.output)["types"] == ["python"]


def test_migrate_keeps_a_local_lefthook_file_it_cannot_merge(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "pyproject.toml": "[project]\nname = 'd'\n",
            "lefthook.yml": V1_LEFTHOOK + "\n    mine:\n      run: echo hi\n",
            "lefthook-local.yml": "# mine\n",
        }
    )

    result = pedantry("migrate", "--path", str(root), "--type", "python", "--skip-npm")

    assert result.exit_code == 0, result.output
    assert (root / "lefthook-local.yml").read_text() == "# mine\n"
    assert "merge these repo-specific hooks into it by hand" in result.output
    assert "echo hi" in result.output


def test_migrate_replaces_symlinks_into_the_submodule(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "pyproject.toml": "[project]\nname = 'd'\n",
            ".pedantry/.editorconfig": V1_EDITORCONFIG,
        }
    )
    (root / ".editorconfig").symlink_to(".pedantry/.editorconfig")
    (root / ".prettierrc.json5").write_text("{}\n")
    (root / ".vscode").mkdir()
    (root / ".vscode/settings.json").symlink_to("../.pedantry/.vscode/settings.json")
    add_submodule(root)
    git(root, "add", "-f", ".editorconfig", ".vscode/settings.json")

    result = pedantry("migrate", "--path", str(root), "--type", "python", "--skip-npm")

    assert result.exit_code == 0, result.output
    assert not (root / ".editorconfig").is_symlink()
    assert "# >>> pedantry" in (root / ".editorconfig").read_text()
    assert not (root / ".vscode/settings.json").exists()
    assert ".vscode/settings.json" in result.output


def test_migrate_vendor_points_configs_at_local_files(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "package.json": '{\n  "name": "demo"\n}\n',
            "tsconfig.json": V1_TSCONFIG,
            "eslint.config.ts": OLD_ESLINT,
            ".prettierrc.json5": "{}\n",
        }
    )
    add_submodule(root)

    result = pedantry(
        "migrate", "--path", str(root), "--type", "typescript", "--vendor"
    )

    assert result.exit_code == 0, result.output
    assert 'from "./.pedantry/eslint.config"' in (root / "eslint.config.ts").read_text()
    tsconfig = json.loads((root / "tsconfig.json").read_text())
    assert tsconfig["extends"] == "./.pedantry/tsconfig.base.json"
    assert (root / ".pedantry/eslint.config.ts").exists()
    assert (root / ".prettierrc.json5").exists()
    assert "npm install" not in result.output.split("Needs a human")[0]
    assert pedantry("check", "--path", str(root)).exit_code == 0


def test_migrate_reports_a_full_eslint_copy_instead_of_rewriting_it(
    make_repo: MAKE, pedantry: CLI
) -> None:
    full_copy = (
        '// Global ignores\nimport tseslint from "typescript-eslint";\n'
        "export default [];\n"
    )
    root = make_repo(
        {"package.json": "{}\n", "eslint.config.ts": full_copy, "a.ts": "\n"}
    )

    result = pedantry(
        "migrate", "--path", str(root), "--type", "typescript", "--skip-npm"
    )

    assert result.exit_code == 0, result.output
    assert (root / "eslint.config.ts").read_text() == full_copy
    assert "holds a full copy of the old pedantry ESLint config" in result.output


def test_migrate_leaves_a_foreign_tsconfig_extends_alone(
    make_repo: MAKE, pedantry: CLI
) -> None:
    text = '{\n  "extends": "@tsconfig/node22/tsconfig.json"\n}\n'
    root = make_repo({"package.json": "{}\n", "tsconfig.json": text, "a.ts": "\n"})

    result = pedantry(
        "migrate", "--path", str(root), "--type", "typescript", "--skip-npm"
    )

    assert (root / "tsconfig.json").read_text() == text
    assert "already extends" in result.output


def test_migrate_a_full_v1_agents_copy_becomes_the_import(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {"pyproject.toml": "[project]\nname = 'd'\n", "AGENTS.md": V1_AGENTS}
    )

    pedantry("migrate", "--path", str(root), "--type", "python", "--skip-npm")

    assert (
        root / "AGENTS.md"
    ).read_text() == "# Agent Instructions\n\n@.pedantry/AGENTS.md\n"


def test_migrate_is_repeatable(make_repo: MAKE, pedantry: CLI) -> None:
    root = v1_repo(make_repo)
    pedantry("migrate", "--path", str(root), "--type", "python", "--skip-npm")
    snapshot = {
        p: p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and ".git/" not in str(p)
    }

    second = pedantry("migrate", "--path", str(root), "--skip-npm")

    assert second.exit_code == 0, second.output
    assert {
        p: p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and ".git/" not in str(p)
    } == snapshot


def test_migrate_drops_stale_tables_for_types_the_repo_does_not_use(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {"pyproject.toml": V1_PYPROJECT, "package.json": "{}\n", "a.js": "\n"}
    )

    result = pedantry(
        "migrate", "--path", str(root), "--type", "javascript", "--skip-npm"
    )

    assert result.exit_code == 0, result.output
    data = tomllib.loads((root / "pyproject.toml").read_text())
    assert set(data["tool"]) == {"pedantry"}
    assert "not needed for this repo's types" in result.output
