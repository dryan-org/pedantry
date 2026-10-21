"""Move an existing repo from the pedantry submodule and copied files to v2."""

import json
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pedantry import __version__, legacy
from pedantry.blocks import find_block, without_block
from pedantry.config import load_pin
from pedantry.content import (
    DJANGO_TABLES,
    EDITORCONFIG_BODY,
    PRETTIERIGNORE_BODY,
    PYTHON_TABLES,
    RETIRED_TABLES,
    data_file,
    pyproject_tables,
    render_lefthook,
    table_value,
)
from pedantry.formats import (
    TomlSection,
    digest,
    dump_json,
    join_toml,
    loads_jsonc,
    parse_lefthook,
    split_editorconfig,
    split_toml,
)
from pedantry.model import PedantryError, Pin, ProjectType, effective, read_text
from pedantry.sync import ResolvedPin, compute, resolve_pin

if TYPE_CHECKING:
    from pathlib import Path

IMPORT_LINE = "@.pedantry/AGENTS.md"
ESLINT_CONFIGS = (
    "eslint.config.ts",
    "eslint.config.mts",
    "eslint.config.js",
    "eslint.config.mjs",
)
COPIED_CONFIGS = (
    "stylelint.config.mjs",
    "rollup.config.js",
    "vitest.config.ts",
    "web-test-runner.config.js",
    "custom-elements-manifest.config.js",
)


@dataclass
class Report:
    """What migrate did, in the words a reviewer needs."""

    actions: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "actions": self.actions,
            "replaced": self.replaced,
            "preserved": self.preserved,
            "manual": self.manual,
        }


@dataclass
class Plan:
    report: Report
    # Final text per path; None deletes the file.
    edits: dict[str, str | None]
    remove_submodule: bool
    npm_install: str | None
    types: list[ProjectType]
    symlinks: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- helpers


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=check, capture_output=True, text=True
    )


def has_submodule(root: Path) -> bool:
    if not (root / ".git").exists():
        return False
    staged = git(root, "ls-files", "-s", "--", ".pedantry", check=False).stdout
    if any(line.startswith("160000") for line in staged.splitlines()):
        return True
    modules = read_text(root / ".gitmodules") or ""
    return bool(re.search(r"^\s*path\s*=\s*\.pedantry\s*$", modules, re.MULTILINE))


def tracked_files(root: Path, pattern: str) -> list[str]:
    if (root / ".git").exists():
        out = git(root, "ls-files", "--", pattern, f"**/{pattern}", check=False).stdout
        return out.split()
    skip = {"node_modules", ".venv", "venv", ".git", ".pedantry"}
    return [
        match.relative_to(root).as_posix()
        for match in root.rglob(pattern)
        if not skip & set(match.relative_to(root).parts)
    ]


def submodule_symlinks(root: Path) -> list[str]:
    """Tracked files that are symlinks into the old submodule (v1 linked them)."""
    if not (root / ".git").exists():
        return []
    listing = git(root, "ls-files", "-s", check=False).stdout
    found: list[str] = []
    for line in listing.splitlines():
        meta, _, name = line.partition("\t")
        link = root / name
        if (
            meta.startswith("120000")
            and link.is_symlink()
            and (root / ".pedantry").resolve() in link.resolve().parents
        ):
            found.append(name)
    return found


def infer_types(root: Path) -> list[ProjectType]:
    types: list[ProjectType] = []
    pyproject = read_text(root / "pyproject.toml")
    if pyproject is not None or (root / "manage.py").is_file():
        is_django = (root / "manage.py").is_file() or bool(
            re.search(r"""(?im)["']django(?![\w-])""", pyproject or "")
        )
        types.append(ProjectType.DJANGO if is_django else ProjectType.PYTHON)
    if (root / "tsconfig.json").is_file() or tracked_files(root, "*.ts"):
        types.append(ProjectType.TYPESCRIPT)
    elif (root / "package.json").is_file():
        types.append(ProjectType.JAVASCRIPT)
    if tracked_files(root, "*.css"):
        types.append(ProjectType.CSS)
    return types


# --------------------------------------------------------------- pyproject


def migrate_pyproject(
    root: Path, types: frozenset[ProjectType], report: Report
) -> tuple[str | None, list[str]]:
    """Drop managed tables that match pedantry; list the ones the repo changed."""
    text = read_text(root / "pyproject.toml")
    if text is None:
        return None, []
    base = without_block(text) if find_block(text) else text
    managed = dict(pyproject_tables(types))
    unused = {
        header: body
        for header, body in PYTHON_TABLES + DJANGO_TABLES
        if header not in managed
    }
    keep: list[str] = []
    kept: list[TomlSection] = []
    for section in split_toml(base):
        header = section.header
        if header is None or header.startswith("[["):
            kept.append(section)
            continue
        if header not in managed and header not in RETIRED_TABLES:
            if header in unused and _is_stale(section, header, unused[header]):
                report.replaced.append(
                    f"pyproject.toml: [{header}] (not needed for this repo's types)"
                )
            else:
                kept.append(section)
            continue
        try:
            value = section.value()
        except (tomllib.TOMLDecodeError, KeyError):
            kept.append(section)
            if header in managed:
                keep.append(header)
            report.manual.append(
                f"pyproject.toml: [{header}] could not be parsed; kept as is"
            )
            continue
        if header in RETIRED_TABLES:
            if not value or legacy.known("pyproject", header, digest(value)):
                report.replaced.append(f"pyproject.toml: [{header}] (retired table)")
            else:
                kept.append(section)
                report.preserved.append(
                    f"pyproject.toml: [{header}] (pedantry no longer manages it)"
                )
        elif value == table_value(header, managed[header]):
            report.replaced.append(
                f"pyproject.toml: [{header}] (identical to pedantry)"
            )
        elif legacy.known("pyproject", header, digest(value)):
            report.replaced.append(
                f"pyproject.toml: [{header}] (stale copy of an older pedantry)"
            )
        else:
            kept.append(section)
            keep.append(header)
            report.preserved.append(
                f"pyproject.toml: [{header}] differs from pedantry; kept in place "
                "and listed "
                "under `keep` in [tool.pedantry]"
            )
    return join_toml(kept), keep


def _is_stale(section: TomlSection, header: str, body: str) -> bool:
    """Whether a table is pedantry's own text, current or from an older version."""
    try:
        value = section.value()
    except (tomllib.TOMLDecodeError, KeyError):
        return False
    return value == table_value(header, body) or legacy.known(
        "pyproject", header, digest(value)
    )


# ---------------------------------------------------------------- lefthook


def migrate_lefthook(
    root: Path, version: str, types: frozenset[ProjectType], report: Report
) -> str | None:
    """Return the lefthook-local.yml text for repo extras (None if there are none)."""
    old = read_text(root / "lefthook.yml")
    if old is None:
        return None
    parsed = parse_lefthook(old)
    generated = {
        command.name: command
        for command in parse_lefthook(render_lefthook(version, types)).commands
    }
    extra_commands: list[str] = []
    for command in parsed.commands:
        target = generated.get(command.name)
        if target is not None and command.key() == target.key():
            report.replaced.append(
                f"lefthook.yml: command `{command.name}` (identical)"
            )
        elif legacy.known("lefthook", command.name, command.key()):
            note = "stale copy of an older pedantry"
            if target is None:
                note += ", not needed for this repo's types"
            report.replaced.append(f"lefthook.yml: command `{command.name}` ({note})")
        else:
            extra_commands.extend(command.lines)
            report.preserved.append(
                f"lefthook.yml: command `{command.name}` moved to lefthook-local.yml"
                + (" (overrides pedantry's)" if target else "")
            )

    extra_options = [
        line
        for line in parsed.hook_options
        if line.strip() and line.strip() != "parallel: false"
    ]
    other = [line for line in parsed.other if line.strip()]
    if extra_options:
        report.preserved.append(
            "lefthook.yml: pre-commit options moved to lefthook-local.yml"
        )
    if other:
        report.preserved.append("lefthook.yml: other hooks moved to lefthook-local.yml")
    if not (extra_commands or extra_options or other):
        return None

    parts = [
        "# Repo-specific lefthook config, moved out of lefthook.yml by pedantry "
        "migrate.",
        "# lefthook merges this file into the managed lefthook.yml.",
    ]
    if extra_commands or extra_options:
        parts.append("pre-commit:")
        parts += extra_options
        if extra_commands:
            parts.append("  commands:")
            parts += extra_commands
    parts += other
    return "\n".join(parts).rstrip() + "\n"


# ------------------------------------------------------------ editorconfig


def migrate_editorconfig(root: Path, report: Report) -> str | None:
    """The repo's own editorconfig sections, minus what pedantry now manages."""
    old = read_text(root / ".editorconfig")
    if old is None:
        return None
    base = without_block(old) if find_block(old) else old
    managed = {
        s.header: s.properties()
        for s in split_editorconfig(EDITORCONFIG_BODY)
        if s.header is not None
    }
    kept: list[str] = []
    same: list[str] = []
    stale: list[str] = []
    for section in split_editorconfig(base):
        if section.header is None:
            continue
        props = section.properties()
        if section.header in managed and props == managed[section.header]:
            same.append(f"[{section.header}]")
        elif legacy.known("editorconfig", section.header, digest(props)):
            stale.append(f"[{section.header}]")
        else:
            kept += section.lines
            report.preserved.append(
                f".editorconfig: [{section.header}] kept after the managed block"
                + (" (differs from pedantry)" if section.header in managed else "")
            )
    if same:
        report.replaced.append(f".editorconfig: {', '.join(same)} (identical)")
    if stale:
        report.replaced.append(f".editorconfig: {', '.join(stale)} (stale copy)")
    text = "\n".join(kept).strip("\n")
    return text + "\n" if text else ""


def migrate_prettierignore(root: Path, report: Report) -> str | None:
    old = read_text(root / ".prettierignore")
    if old is None:
        return None
    base = without_block(old) if find_block(old) else old
    managed = {
        line.strip() for line in PRETTIERIGNORE_BODY.splitlines() if line.strip()
    }
    kept: list[str] = []
    for line in base.splitlines():
        stripped = line.strip()
        if not stripped or stripped in managed or legacy.known_line(stripped):
            continue
        kept.append(line)
        if not stripped.startswith("#"):
            report.preserved.append(
                f".prettierignore: `{stripped}` kept after the managed block"
            )
    return "\n".join(kept) + "\n" if kept else ""


# ---------------------------------------------------------------- tsconfig


def migrate_tsconfig(root: Path, vendor: bool, report: Report) -> str | None:
    text = read_text(root / "tsconfig.json")
    if text is None:
        return None
    data = loads_jsonc(text)
    if not isinstance(data, dict):
        report.manual.append("tsconfig.json: not a JSON object; left alone")
        return None
    target = "./.pedantry/tsconfig.base.json" if vendor else "@dryan/pedantry/tsconfig"
    current = data.get("extends")
    if current is not None and "pedantry" not in str(current):
        report.manual.append(
            f"tsconfig.json: already extends `{current}`; left alone (extend "
            f"{target} there)"
        )
        return None
    base = loads_jsonc(data_file("js", "tsconfig.base.json"))
    shared: dict[str, object] = (
        base["compilerOptions"] if isinstance(base, dict) else {}
    )
    options = data.get("compilerOptions", {})
    kept_options: dict[str, object] = {}
    same: list[str] = []
    stale: list[str] = []
    for key, value in options.items():
        if key in shared and value == shared[key]:
            same.append(key)
        elif key in shared and legacy.known("tsconfig", key, digest(value)):
            stale.append(key)
        else:
            kept_options[key] = value
            report.preserved.append(
                f"tsconfig.json: compilerOptions.{key} kept"
                + (" (differs from pedantry)" if key in shared else " (repo-specific)")
            )
    if same:
        report.replaced.append(
            f"tsconfig.json: compilerOptions {', '.join(same)} (identical to pedantry)"
        )
    if stale:
        report.replaced.append(
            f"tsconfig.json: compilerOptions {', '.join(stale)} (stale copy)"
        )
    inherited = [key for key in shared if key not in options]
    if inherited:
        report.manual.append(
            "tsconfig.json: now also inherits "
            + ", ".join(inherited)
            + " from pedantry (this repo's copy lacked them); run tsc to see the effect"
        )
    result: dict[str, object] = {"extends": target}
    if kept_options:
        result["compilerOptions"] = kept_options
    for key, value in data.items():
        if key in {"extends", "compilerOptions"}:
            continue
        if key == "exclude" and isinstance(value, list):
            value = [item for item in value if not _is_pedantry_path(str(item))]
        result[key] = value
    return dump_json(result) + "\n"


# ------------------------------------------------------------------ eslint

_ESLINT_IMPORT = re.compile(
    r"""(["'])((?:\.{1,2}/)[^"']*?pedantry/eslint\.config(?:\.[mc]?[jt]s)?)\1"""
)
_PEDANTRY_ITEM = r"""(["'])(?:\*\*/|\./)?\.pedantry(?:/\*{0,2})?\1"""
# An ignore entry, with the comma that separates it from its neighbour.
_ESLINT_IGNORE_LAST = re.compile(rf",\s*{_PEDANTRY_ITEM}(?=\s*\])")
_ESLINT_IGNORE = re.compile(rf"[ \t]*{_PEDANTRY_ITEM},?[ \t]*\n?")


def _is_pedantry_path(item: str) -> bool:
    return re.fullmatch(r"(\*\*/|\./)?\.pedantry(/\*{0,2})?", item) is not None


def migrate_eslint(root: Path, vendor: bool, report: Report) -> dict[str, str]:
    edits: dict[str, str] = {}
    for name in ESLINT_CONFIGS:
        text = read_text(root / name)
        if text is None:
            continue
        new = text
        if _ESLINT_IMPORT.search(new):
            replacement = (
                "./.pedantry/eslint.config" if vendor else "@dryan/pedantry/eslint"
            )
            new = _ESLINT_IMPORT.sub(rf"\1{replacement}\1", new)
            report.actions.append(f"{name}: import points at {replacement}")
        elif "typescript-eslint" in new and "Global ignores" in new:
            report.manual.append(
                f"{name}: holds a full copy of the old pedantry ESLint config. "
                "Replace it with "
                "a file that imports `@dryan/pedantry/eslint` and keep only your own "
                "rules"
            )
        stripped = _ESLINT_IGNORE.sub("", _ESLINT_IGNORE_LAST.sub("", new))
        if stripped != new:
            report.actions.append(f"{name}: dropped `.pedantry` from ignores")
            new = stripped
        if new != text:
            edits[name] = new
    return edits


# ------------------------------------------------------------ package.json


def _indent(text: str) -> str | int:
    return "\t" if re.search(r'^\t"', text, re.MULTILINE) else 2


def migrate_package_json(
    root: Path, vendor: bool, report: Report
) -> tuple[str | None, bool]:
    """Set the prettier key and drop an empty .prettierrc.json5.

    Returns (new package.json text, whether to delete .prettierrc.json5).
    """
    text = read_text(root / "package.json")
    rc = read_text(root / ".prettierrc.json5")
    if text is None or rc is None or vendor:
        return None, False
    try:
        rc_data = loads_jsonc(rc)
    except json.JSONDecodeError:
        report.manual.append(".prettierrc.json5: not plain JSON(5); left alone")
        return None, False
    data = json.loads(text)
    if rc_data != {}:
        report.manual.append(
            ".prettierrc.json5 sets options, but pedantry's Prettier config is the "
            "defaults. "
            'Review it before using `"prettier": "@dryan/pedantry/prettier"`'
        )
        return None, False
    if "prettier" in data:
        return None, False
    data["prettier"] = "@dryan/pedantry/prettier"
    report.actions.append(
        'package.json: set "prettier" to @dryan/pedantry/prettier and deleted the '
        "empty "
        ".prettierrc.json5"
    )
    return json.dumps(data, indent=_indent(text), ensure_ascii=False) + "\n", True


# --------------------------------------------------------------- AGENTS.md


def migrate_agents(root: Path, report: Report) -> str:
    text = read_text(root / "AGENTS.md")
    if text is None:
        report.actions.append("AGENTS.md: created, importing @.pedantry/AGENTS.md")
        return f"# Agent Instructions\n\n{IMPORT_LINE}\n"
    if IMPORT_LINE in text:
        return text
    if legacy.known_agents(text):
        report.replaced.append("AGENTS.md: a full copy of the old pedantry rules")
        return f"# Agent Instructions\n\n{IMPORT_LINE}\n"
    report.actions.append("AGENTS.md: added the @.pedantry/AGENTS.md import")
    return text.rstrip("\n") + f"\n\n{IMPORT_LINE}\n"


# ---------------------------------------------------------------- the plan


def plan_migrate(
    root: Path,
    *,
    types: list[ProjectType] | None = None,
    vendor: bool = False,
    skip_npm: bool = False,
) -> Plan:
    report = Report()
    existing = load_pin(root)
    chosen = types or (existing.types if existing else infer_types(root))
    if not chosen:
        raise PedantryError("could not infer the project types: pass --type")
    kinds = effective(frozenset(chosen))
    vendor = vendor or bool(existing and existing.vendor)

    submodule = has_submodule(root)
    if submodule:
        report.actions.append("removed the .pedantry git submodule (not committed)")
    npm_install = None
    uses_npm = bool(
        kinds & {ProjectType.TYPESCRIPT, ProjectType.JAVASCRIPT, ProjectType.CSS}
    )
    if (root / "package.json").is_file() and uses_npm and not vendor and not skip_npm:
        npm_install = f"npm install --save-dev github:dryan-org/pedantry#v{__version__}"
        report.actions.append(f"ran `{npm_install}`")

    symlinks = submodule_symlinks(root)
    for name in symlinks:
        if (root / name).exists():
            report.actions.append(
                f"{name}: was a symlink into the old submodule; now a regular file"
            )
        else:
            report.manual.append(
                f"{name}: was a symlink into the old submodule whose target is not "
                "checked out here, so it was removed; restore from pedantry if needed"
            )

    overlay: dict[str, str] = {}
    edits: dict[str, str | None] = {}

    pyproject_text, keep = migrate_pyproject(root, frozenset(chosen), report)
    if pyproject_text is not None:
        overlay["pyproject.toml"] = pyproject_text
    editor = migrate_editorconfig(root, report)
    if editor is not None:
        overlay[".editorconfig"] = editor
    ignore = migrate_prettierignore(root, report)
    if ignore is not None:
        overlay[".prettierignore"] = ignore
    local = migrate_lefthook(root, __version__, frozenset(chosen), report)
    if local is not None:
        if (root / "lefthook-local.yml").is_file():
            report.manual.append(
                "lefthook-local.yml already exists: merge these repo-specific hooks "
                "into it "
                "by hand:\n" + local
            )
        else:
            edits["lefthook-local.yml"] = local

    base = resolve_pin(root, types=chosen, vendor=vendor, upgrade=True)
    resolved = ResolvedPin(
        Pin(
            version=base.pin.version,
            types=base.pin.types,
            vendor=base.pin.vendor,
            keep=sorted(set(base.pin.keep) | set(keep)),
        ),
        base.source,
    )

    def reader(path: str) -> str | None:
        return overlay[path] if path in overlay else read_text(root / path)

    edits.update(overlay)
    for change in compute(root, resolved, force=True, reader=reader):
        edits[change.path] = change.new

    edits.update(migrate_eslint(root, vendor, report))
    tsconfig = migrate_tsconfig(root, vendor, report)
    if tsconfig is not None:
        edits["tsconfig.json"] = tsconfig
    package, drop_rc = migrate_package_json(root, vendor, report)
    if package is not None:
        edits["package.json"] = package
    if drop_rc:
        edits[".prettierrc.json5"] = None
    edits["AGENTS.md"] = migrate_agents(root, report)

    for name in COPIED_CONFIGS:
        if (root / name).is_file():
            report.manual.append(
                f"{name}: left alone. If it is a copy of the old pedantry config, "
                "switch it to the matching `@dryan/pedantry/...` export "
                "(see the README)"
            )
    report.manual.append(
        f"CI: run `uvx --from git+https://github.com/dryan-org/pedantry@v{__version__} "
        "pedantry check` (the shared CI workflow step does this)"
    )
    if vendor:
        report.manual.append(
            "vendored configs live in .pedantry/: point eslint.config.ts, "
            "tsconfig.json and "
            "stylelint.config.mjs at them and install the npm packages `pedantry "
            "sync` listed"
        )

    pending: dict[str, str | None] = {}
    for path, text in edits.items():
        if text is None:
            if (root / path).exists():
                pending[path] = None
        elif read_text(root / path) != text:
            pending[path] = text
    return Plan(report, pending, submodule, npm_install, list(chosen), symlinks)


def remove_submodule(root: Path) -> None:
    git(root, "rm", "--cached", "-q", "-f", "--ignore-unmatch", "--", ".pedantry")
    modules = root / ".gitmodules"
    if modules.is_file():
        blocks = re.split(r"(?m)^(?=\[submodule )", modules.read_text(encoding="utf-8"))
        remaining = [
            block
            for block in blocks
            if not re.search(r"(?m)^\s*path\s*=\s*\.pedantry\s*$", block)
        ]
        if "".join(remaining).strip():
            modules.write_text("".join(remaining), encoding="utf-8")
            git(root, "add", ".gitmodules")
        else:
            git(root, "rm", "-q", "-f", "--ignore-unmatch", "--", ".gitmodules")
            modules.unlink(missing_ok=True)
    git(
        root,
        "config",
        "--local",
        "--remove-section",
        "submodule..pedantry",
        check=False,
    )
    shutil.rmtree(root / ".pedantry", ignore_errors=True)
    module_dir = git(
        root, "rev-parse", "--git-path", "modules/.pedantry"
    ).stdout.strip()
    shutil.rmtree(root / module_dir, ignore_errors=True)


def execute(root: Path, plan: Plan) -> None:
    """Apply a plan: the submodule removal first, then npm, then the file edits."""
    for name in plan.symlinks:
        link = root / name
        content = link.read_bytes() if link.exists() else None
        link.unlink()
        if content is not None:
            link.write_bytes(content)
    if plan.remove_submodule:
        remove_submodule(root)
    if plan.npm_install:
        subprocess.run(plan.npm_install.split(), cwd=root, check=True)
    for path, text in plan.edits.items():
        target = root / path
        if text is None:
            target.unlink(missing_ok=True)
            continue
        if path == "package.json" and plan.npm_install:
            # npm rewrote package.json (the new devDependency): add our key on top.
            current_text = target.read_text(encoding="utf-8")
            current = json.loads(current_text)
            current["prettier"] = json.loads(text)["prettier"]
            text = (
                json.dumps(current, indent=_indent(current_text), ensure_ascii=False)
                + "\n"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            target.unlink()
        target.write_text(text, encoding="utf-8")
