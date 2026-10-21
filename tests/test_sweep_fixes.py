"""Fixes for what the v2.0.2 sweep over every consumer repo turned up."""

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Result, git
from test_migrate import add_submodule

MAKE = Callable[..., Path]
CLI = Callable[..., Result]


@pytest.fixture
def failing_npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An ``npm`` that fails the way a missing git tag does."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "npm"
    script.write_text(
        "#!/bin/sh\n"
        "echo 'npm error code 128' >&2\n"
        "echo 'npm error fatal: Remote branch v9.9.9 not found' >&2\n"
        "exit 1\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return script


# ------------------------------------------------- npm failure is reported


@pytest.mark.usefixtures("failing_npm")
def test_sync_upgrade_reports_a_failing_npm_and_keeps_the_files(
    make_repo: MAKE, pedantry: CLI, version: str
) -> None:
    package = {"name": "d", "devDependencies": {"@dryan/pedantry": "github:x#v1.0.0"}}
    root = make_repo(
        {
            "pedantry.toml": 'version = "1.0.0"\ntypes = ["javascript"]\n',
            "package.json": json.dumps(package),
        }
    )

    result = pedantry("sync", "--path", str(root), "--upgrade")

    assert result.exit_code == 0
    assert "failed (exit 1)" in result.output
    assert "Remote branch v9.9.9 not found" in result.output
    assert "Traceback" not in result.output
    assert f'version = "{version}"' in (root / "pedantry.toml").read_text()


@pytest.mark.usefixtures("failing_npm")
def test_sync_upgrade_json_says_npm_did_not_run(make_repo: MAKE, pedantry: CLI) -> None:
    package = {"name": "d", "devDependencies": {"@dryan/pedantry": "github:x#v1.0.0"}}
    root = make_repo(
        {
            "pedantry.toml": 'version = "1.0.0"\ntypes = ["javascript"]\n',
            "package.json": json.dumps(package),
        }
    )

    result = pedantry("sync", "--path", str(root), "--upgrade", "--json")

    npm = json.loads(result.output)["npm"]
    assert npm["ran"] is False
    assert "failed (exit 1)" in npm["note"]


@pytest.mark.usefixtures("failing_npm")
def test_migrate_reports_a_failing_npm_and_still_writes_the_files(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "package.json": '{\n  "name": "demo"\n}\n',
            "eslint.config.ts": "export default [];\n",
            "src/a.ts": "export {};\n",
        }
    )

    result = pedantry("migrate", "--path", str(root), "--type", "typescript")

    assert result.exit_code == 0
    assert "failed (exit 1)" in result.output
    assert "ran `npm install" not in result.output
    assert (root / "lefthook.yml").is_file()
    assert (root / "pedantry.toml").is_file()


# --------------------------------------------- repos with no project types


def test_migrate_pins_no_types_for_a_repo_without_tooling_files(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            ".editorconfig": "root = true\n\n[*.swift]\nindent_size = 4\n",
            "App/main.swift": "print(1)\n",
        }
    )

    result = pedantry("migrate", "--path", str(root))

    assert result.exit_code == 0
    assert "no project types detected" in result.output
    assert "types = []" in (root / "pedantry.toml").read_text()
    assert "[*.swift]" in (root / ".editorconfig").read_text()
    assert pedantry("check", "--path", str(root)).exit_code == 0
    assert pedantry("sync", "--path", str(root)).exit_code == 0


def test_sync_without_pin_or_type_still_fails(make_repo: MAKE, pedantry: CLI) -> None:
    root = make_repo({"a.txt": "x\n"})

    assert pedantry("sync", "--path", str(root)).exit_code == 2


# ------------------------------------------- stale .pedantry/<file> paths


def test_migrate_drops_the_stylelint_config_flag_and_writes_a_config(
    make_repo: MAKE, pedantry: CLI
) -> None:
    scripts = {
        "lint:css": 'stylelint "**/*.css" --config .pedantry/stylelint.config.mjs',
        "lint:css:fix": (
            'stylelint "**/*.css" --config=./.pedantry/stylelint.config.mjs --fix'
        ),
    }
    root = make_repo(
        {"package.json": json.dumps({"name": "d", "scripts": scripts}, indent=2)}
    )
    add_submodule(root)

    result = pedantry("migrate", "--path", str(root), "--type", "css", "--skip-npm")

    assert result.exit_code == 0
    new = json.loads((root / "package.json").read_text())["scripts"]
    assert new == {
        "lint:css": 'stylelint "**/*.css"',
        "lint:css:fix": 'stylelint "**/*.css" --fix',
    }
    assert "@dryan/pedantry/stylelint" in (root / "stylelint.config.mjs").read_text()
    assert "stylelint" in (root / "lefthook.yml").read_text()
    assert pedantry("check", "--path", str(root)).exit_code == 0
    assert "no longer exists" not in result.output


def test_migrate_keeps_an_existing_stylelint_config(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "package.json": json.dumps(
                {
                    "name": "d",
                    "scripts": {
                        "lint:css": "stylelint --config .pedantry/stylelint.config.mjs"
                    },
                }
            ),
            "stylelint.config.mjs": "export default {};\n",
        }
    )
    add_submodule(root)

    pedantry("migrate", "--path", str(root), "--type", "css", "--skip-npm")

    assert (root / "stylelint.config.mjs").read_text() == "export default {};\n"
    scripts = json.loads((root / "package.json").read_text())["scripts"]
    assert scripts["lint:css"] == "stylelint"


def test_migrate_with_vendor_keeps_the_stylelint_flag(
    make_repo: MAKE, pedantry: CLI
) -> None:
    flag = "stylelint --config .pedantry/stylelint.config.mjs x"
    root = make_repo(
        {"package.json": json.dumps({"name": "d", "scripts": {"lint:css": flag}})}
    )
    add_submodule(root)

    result = pedantry(
        "migrate", "--path", str(root), "--type", "css", "--vendor", "--skip-npm"
    )

    assert (root / ".pedantry/stylelint.config.mjs").is_file()
    assert (
        json.loads((root / "package.json").read_text())["scripts"]["lint:css"] == flag
    )
    assert "no longer exists" not in result.output


def test_migrate_lists_files_that_still_name_a_removed_pedantry_path(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "package.json": '{\n  "name": "d"\n}\n',
            "eslint.config.ts": (
                'const path = join(__dirname, ".pedantry/eslint.config.ts");\n'
                "export default [];\n"
            ),
            "docs/notes.md": "See `.pedantry/tsconfig.json`, @.pedantry/AGENTS.md.\n",
            ".gitignore": ".pedantry/cache\n",
            "logo.bin": "x",
        }
    )
    add_submodule(root)
    (root / "logo.bin").write_bytes(b"\xff\xfe\x00.pedantry/x")
    git(root, "add", "logo.bin", "eslint.config.ts", "docs", ".gitignore")

    result = pedantry(
        "migrate", "--path", str(root), "--type", "typescript", "--skip-npm"
    )

    assert (
        "eslint.config.ts: line 1 names `.pedantry/eslint.config.ts`, which no longer "
        "exists" in result.output
    )
    assert "import `@dryan/pedantry/eslint`" in result.output
    assert "docs/notes.md: line 1 names `.pedantry/tsconfig.json`" in result.output
    assert 'extend "@dryan/pedantry/tsconfig"' in result.output
    assert ".pedantry/cache" not in result.output
    assert "logo.bin" not in result.output


def test_migrate_does_not_list_the_agents_import(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"AGENTS.md": "# Demo\n\n@.pedantry/AGENTS.md\n"})
    add_submodule(root)

    result = pedantry("migrate", "--path", str(root), "--type", "python", "--skip-npm")

    assert "no longer exists" not in result.output


def test_migrate_drops_a_lefthook_extends_of_the_old_copy(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "package.json": '{\n  "name": "d"\n}\n',
            "lefthook.yml": (
                "extends:\n  - .pedantry/lefthook.yml\n\n"
                "pre-commit:\n  commands:\n    eslint:\n      skip: true\n"
            ),
        }
    )
    add_submodule(root)

    result = pedantry(
        "migrate", "--path", str(root), "--type", "javascript", "--skip-npm"
    )

    local = (root / "lefthook-local.yml").read_text()
    assert "extends" not in local
    assert ".pedantry/lefthook.yml" not in local
    assert "skip: true" in local
    assert "extends` of .pedantry/lefthook.yml" in result.output


def test_migrate_removes_the_comment_after_an_eslint_ignore_entry(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "package.json": '{\n  "name": "d"\n}\n',
            "eslint.config.ts": (
                'import pedantryConfig from "./.pedantry/eslint.config.ts";\n\n'
                "export default [\n  ...pedantryConfig,\n  {\n    ignores: [\n"
                '      "dist/**",\n      ".pedantry/**", // Pedantry submodule\n'
                "    ],\n  },\n];\n"
            ),
        }
    )
    add_submodule(root)

    pedantry("migrate", "--path", str(root), "--type", "typescript", "--skip-npm")

    text = (root / "eslint.config.ts").read_text()
    assert "Pedantry submodule" not in text
    assert '"dist/**",' in text
    assert "@dryan/pedantry/eslint" in text


# ------------------------------------------- prettier-clean rewritten files


def test_migrate_collapses_an_eslint_ignores_array_that_now_fits_on_one_line(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "package.json": '{\n  "name": "d"\n}\n',
            "eslint.config.ts": (
                'import pedantryConfig from "./.pedantry/eslint.config.ts";\n\n'
                "export default [\n  ...pedantryConfig,\n  {\n    ignores: [\n"
                '      "dist/**",\n      "coverage/**",\n      ".pedantry/**",\n'
                '      ".venv/**",\n    ],\n  },\n];\n'
            ),
        }
    )
    add_submodule(root)

    pedantry("migrate", "--path", str(root), "--type", "typescript", "--skip-npm")

    text = (root / "eslint.config.ts").read_text()
    assert '    ignores: ["dist/**", "coverage/**", ".venv/**"],\n' in text


def test_migrate_keeps_a_long_eslint_ignores_array_one_entry_per_line(
    make_repo: MAKE, pedantry: CLI
) -> None:
    names = [f'"some/long/directory/name-{n}/**"' for n in range(4)]
    items = "".join(f"      {name},\n" for name in names)
    root = make_repo(
        {
            "package.json": '{\n  "name": "d"\n}\n',
            "eslint.config.ts": (
                'import pedantryConfig from "./.pedantry/eslint.config.ts";\n\n'
                "export default [\n  ...pedantryConfig,\n  {\n    ignores: [\n"
                f'{items}      ".pedantry/**",\n    ],\n  }},\n];\n'
            ),
        }
    )
    add_submodule(root)

    pedantry("migrate", "--path", str(root), "--type", "typescript", "--skip-npm")

    text = (root / "eslint.config.ts").read_text()
    assert f"    ignores: [\n{items}    ],\n" in text


# --------------------------------------- tsconfig keeps its old strictness


def test_migrate_does_not_turn_on_checks_the_old_tsconfig_lacked(
    make_repo: MAKE, pedantry: CLI
) -> None:
    old = {
        "compilerOptions": {"target": "ES2022", "strict": True, "noEmit": True},
        "include": ["src"],
    }
    root = make_repo(
        {"package.json": '{\n  "name": "d"\n}\n', "tsconfig.json": json.dumps(old)}
    )
    add_submodule(root)

    result = pedantry(
        "migrate", "--path", str(root), "--type", "typescript", "--skip-npm"
    )

    options = json.loads((root / "tsconfig.json").read_text())["compilerOptions"]
    assert options["noUncheckedIndexedAccess"] is False
    assert options["noPropertyAccessFromIndexSignature"] is False
    assert "strict" not in options
    assert "compilerOptions.noUncheckedIndexedAccess set to false" in result.output
    assert "now also inherits noUncheckedIndexedAccess" not in result.output


def test_a_second_migrate_does_not_loosen_the_tsconfig_again(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "package.json": '{\n  "name": "d"\n}\n',
            "tsconfig.json": json.dumps({"extends": "@dryan/pedantry/tsconfig"}),
        }
    )
    add_submodule(root)

    pedantry("migrate", "--path", str(root), "--type", "typescript", "--skip-npm")

    assert "compilerOptions" not in json.loads((root / "tsconfig.json").read_text())


# ------------------------------------------- another Prettier config exists


def test_migrate_does_not_change_which_prettier_config_applies(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo(
        {
            "package.json": '{\n  "name": "d"\n}\n',
            ".prettierrc.json": '{ "singleQuote": true }\n',
            ".prettierrc.json5": "{\n  // defaults only\n}\n",
        }
    )
    add_submodule(root)

    result = pedantry(
        "migrate", "--path", str(root), "--type", "javascript", "--skip-npm"
    )

    assert "prettier" not in json.loads((root / "package.json").read_text())
    assert (root / ".prettierrc.json5").is_file()
    assert (root / ".prettierrc.json").read_text() == '{ "singleQuote": true }\n'
    assert ".prettierrc.json also configures Prettier" in result.output


# ------------------------------------- symlinked config copies become helpers


def test_migrate_replaces_symlinked_helper_configs_with_the_package_calls(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"package.json": '{\n  "name": "d"\n}\n'})
    add_submodule(root)
    for name in ("stylelint.config.mjs", "vitest.config.ts", "rollup.config.js"):
        (root / ".pedantry" / name).write_text("// old copy\n")
        (root / name).symlink_to(f".pedantry/{name}")
        git(root, "add", name)

    result = pedantry(
        "migrate", "--path", str(root), "--type", "typescript", "--skip-npm"
    )

    assert not (root / "vitest.config.ts").is_symlink()
    assert (root / "vitest.config.ts").read_text() == (
        'import { defineConfig } from "vitest/config";\n'
        'import { vitestConfig } from "@dryan/pedantry/vitest";\n\n'
        "export default defineConfig(vitestConfig());\n"
    )
    assert "@dryan/pedantry/stylelint" in (root / "stylelint.config.mjs").read_text()
    assert "@dryan/pedantry/rollup" in (root / "rollup.config.js").read_text()
    assert "vitest.config.ts: symlink to the old pedantry config" in result.output
    assert "vitest.config.ts: left alone" not in result.output


def test_migrate_with_vendor_keeps_symlinked_configs_as_copies(
    make_repo: MAKE, pedantry: CLI
) -> None:
    root = make_repo({"package.json": '{\n  "name": "d"\n}\n'})
    add_submodule(root)
    (root / ".pedantry" / "vitest.config.ts").write_text("// old copy\n")
    (root / "vitest.config.ts").symlink_to(".pedantry/vitest.config.ts")
    git(root, "add", "vitest.config.ts")

    pedantry(
        "migrate",
        "--path",
        str(root),
        "--type",
        "typescript",
        "--vendor",
        "--skip-npm",
    )

    assert (root / "vitest.config.ts").read_text() == "// old copy\n"


def test_migrate_says_to_format_the_helper_configs_when_prettier_has_options(
    make_repo: MAKE, pedantry: CLI
) -> None:
    package = {"name": "d", "prettier": {"singleQuote": True}}
    root = make_repo({"package.json": json.dumps(package)})
    add_submodule(root)
    (root / ".pedantry" / "stylelint.config.mjs").write_text("// old copy\n")
    (root / "stylelint.config.mjs").symlink_to(".pedantry/stylelint.config.mjs")
    git(root, "add", "stylelint.config.mjs")

    result = pedantry("migrate", "--path", str(root), "--type", "css", "--skip-npm")

    assert "Run `npx prettier --write stylelint.config.mjs`" in result.output


# ----------------------------------- eslint 10 peers (lockfiles npm 10 accepts)


@pytest.fixture
def recording_npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An ``npm`` that only records its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "npm.log"
    script = bin_dir / "npm"
    script.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def old_eslint_package(**extra: str) -> str:
    dev = {
        "@dryan/pedantry": "github:dryan-org/pedantry#v1.0.0",
        "eslint": "^9.39.2",
        "@eslint/js": "^9.39.2",
        "prettier": "^3.0.0",
        **extra,
    }
    return json.dumps({"name": "d", "devDependencies": dev})


def test_package_json_declares_the_eslint_peer() -> None:
    package = json.loads((Path(__file__).parent.parent / "package.json").read_text())
    assert package["peerDependencies"]["eslint"] == "^10"
    assert "eslint" not in package.get("peerDependenciesMeta", {})
    assert package["peerDependenciesMeta"]["stylelint"]["optional"] is True


def test_sync_upgrade_raises_eslint_in_the_same_npm_call(
    make_repo: MAKE, pedantry: CLI, recording_npm: Path, version: str
) -> None:
    root = make_repo(
        {
            "pedantry.toml": 'version = "1.0.0"\ntypes = ["javascript"]\n',
            "package.json": old_eslint_package(stylelint="^16.0.0"),
        }
    )

    result = pedantry("sync", "--path", str(root), "--upgrade")

    assert result.exit_code == 0
    assert recording_npm.read_text().split() == [
        "install",
        "--save-dev",
        f"github:dryan-org/pedantry#v{version}",
        "eslint@^10",
        "@eslint/js@^10",
        "stylelint@^17",
    ]
    assert "eslint ^9.39.2 -> ^10" in result.output


def test_sync_upgrade_json_lists_the_bumps(
    make_repo: MAKE, pedantry: CLI, recording_npm: Path
) -> None:
    root = make_repo(
        {
            "pedantry.toml": 'version = "1.0.0"\ntypes = ["javascript"]\n',
            "package.json": old_eslint_package(),
        }
    )

    result = pedantry("sync", "--path", str(root), "--upgrade", "--json")

    npm = json.loads(result.output)["npm"]
    assert npm["ran"] is True
    assert npm["bumped"] == ["eslint ^9.39.2 -> ^10", "@eslint/js ^9.39.2 -> ^10"]
    assert "eslint@^10 @eslint/js@^10" in npm["command"]
    assert recording_npm.is_file()


def test_sync_upgrade_leaves_current_and_unversioned_peers_alone(
    make_repo: MAKE, pedantry: CLI, recording_npm: Path, version: str
) -> None:
    package = {
        "name": "d",
        "devDependencies": {
            "@dryan/pedantry": "github:dryan-org/pedantry#v1.0.0",
            "eslint": "^10.2.0",
            "@eslint/js": "*",
            "stylelint": "latest",
        },
    }
    root = make_repo(
        {
            "pedantry.toml": 'version = "1.0.0"\ntypes = ["javascript"]\n',
            "package.json": json.dumps(package),
        }
    )

    pedantry("sync", "--path", str(root), "--upgrade")

    assert recording_npm.read_text().split() == [
        "install",
        "--save-dev",
        f"github:dryan-org/pedantry#v{version}",
    ]


def test_sync_upgrade_failing_npm_prints_the_bumps_in_the_rerun_command(
    make_repo: MAKE, pedantry: CLI, failing_npm: Path
) -> None:
    root = make_repo(
        {
            "pedantry.toml": 'version = "1.0.0"\ntypes = ["javascript"]\n',
            "package.json": old_eslint_package(),
        }
    )

    result = pedantry("sync", "--path", str(root), "--upgrade", "--json")

    npm = json.loads(result.output)["npm"]
    assert result.exit_code == 0
    assert npm["ran"] is False
    assert "eslint@^10 @eslint/js@^10" in npm["note"]
    assert failing_npm.is_file()


def test_migrate_raises_eslint_in_the_same_npm_call(
    make_repo: MAKE, pedantry: CLI, recording_npm: Path, version: str
) -> None:
    root = make_repo(
        {
            "package.json": old_eslint_package(),
            "eslint.config.ts": "export default [];\n",
            "src/a.ts": "export {};\n",
        }
    )

    result = pedantry("migrate", "--path", str(root), "--type", "typescript")

    assert result.exit_code == 0
    assert recording_npm.read_text().split() == [
        "install",
        "--save-dev",
        f"github:dryan-org/pedantry#v{version}",
        "eslint@^10",
        "@eslint/js@^10",
    ]
    assert "eslint ^9.39.2 -> ^10" in result.output


def test_migrate_json_reports_the_bump_as_an_action(
    make_repo: MAKE, pedantry: CLI, recording_npm: Path
) -> None:
    root = make_repo(
        {
            "package.json": old_eslint_package(),
            "eslint.config.ts": "export default [];\n",
            "src/a.ts": "export {};\n",
        }
    )

    result = pedantry("migrate", "--path", str(root), "--type", "typescript", "--json")

    actions = json.loads(result.output)["actions"]
    assert any("@eslint/js ^9.39.2 -> ^10" in action for action in actions)
    assert recording_npm.is_file()


def test_migrate_failing_npm_drops_the_bump_action_and_prints_the_command(
    make_repo: MAKE, pedantry: CLI, failing_npm: Path
) -> None:
    root = make_repo(
        {
            "package.json": old_eslint_package(),
            "eslint.config.ts": "export default [];\n",
            "src/a.ts": "export {};\n",
        }
    )

    result = pedantry("migrate", "--path", str(root), "--type", "typescript", "--json")

    report = json.loads(result.output)
    assert result.exit_code == 0
    assert not any("raised" in action for action in report["actions"])
    assert any("eslint@^10 @eslint/js@^10" in note for note in report["manual"])
    assert failing_npm.is_file()
