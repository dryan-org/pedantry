"""The text pedantry manages, as a function of version and project types."""

import json
import re
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING

from pedantry.blocks import without_block, wrap_block
from pedantry.model import MANAGED_PHRASE, ProjectType, effective

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# ------------------------------------------------------------------ stamps


def stamp(version: str) -> str:
    return f"pedantry {version}: {MANAGED_PHRASE}."


def data_file(*parts: str) -> str:
    resource = files("pedantry").joinpath("data", *parts)
    return resource.read_text(encoding="utf-8")


# ------------------------------------------------------------ .editorconfig

EDITORCONFIG_BODY = """\
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

[*.{js,ts,json,css,html}]
indent_style = space
indent_size = 2

[*.py]
indent_style = space
indent_size = 4

[*.md]
trim_trailing_whitespace = false

[Makefile]
indent_style = tab
"""


def editorconfig_block(version: str) -> str:
    return wrap_block(stamp(version), EDITORCONFIG_BODY)


# ----------------------------------------------------------- .prettierignore

PRETTIERIGNORE_BODY = """\
# Dependencies
node_modules

# Build outputs
dist
build
.rollup.cache
*.min.js
*.min.css

# Logs
*.log
npm-debug.log*
yarn-debug.log*
yarn-error.log*
pnpm-debug.log*

# Python
__pycache__
*.pyc
.pytest_cache
.ruff_cache
*.egg-info
.venv
venv

# Testing
coverage
.nyc_output

# Other
.DS_Store
.git
.env
.env.local
*.backup.*

# Written by pedantry sync
.pedantry
lefthook.yml
"""


def prettierignore_block(version: str) -> str:
    return wrap_block(stamp(version), PRETTIERIGNORE_BODY)


# ----------------------------------------------------------------- lefthook

_PRETTIER = """\
    # Format files
    prettier:
      glob: "*.{js,ts,json,css,html,md,yml,yaml}"
      run: |
        FILES=$(for f in {staged_files}; do
          [ -f "$f" ] && [ ! -L "$f" ] && echo "$f"
        done)
        [ -z "$FILES" ] || npx prettier --write $FILES
      stage_fixed: true
"""


def _staged(tool: str, *, fix: bool = True, comment: str, name: str, glob: str) -> str:
    stage = "true" if fix else "false # reports only, fixes nothing"
    return f"""\
    # {comment}
    {name}:
      glob: "{glob}"
      run: |
        FILES=$(for f in {{staged_files}}; do
          [ -f "$f" ] && echo "$f"
        done)
        [ -z "$FILES" ] || {tool} $FILES
      stage_fixed: {stage}
"""


def typescript_major(package_json: str | None) -> int | None:
    """The major version package.json asks of TypeScript, if it says."""
    if not package_json:
        return None
    try:
        data = json.loads(package_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("devDependencies", "dependencies", "peerDependencies"):
        group = data.get(key)
        spec = group.get("typescript") if isinstance(group, dict) else None
        if isinstance(spec, str) and (match := re.search(r"\d+", spec)):
            return int(match.group())
    return None


ESLINT_CONFIGS = (
    "eslint.config.ts",
    "eslint.config.mts",
    "eslint.config.cts",
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.cjs",
)
STYLELINT_CONFIGS = (
    "stylelint.config.js",
    "stylelint.config.mjs",
    "stylelint.config.cjs",
    "stylelint.config.ts",
    "stylelint.config.mts",
    "stylelint.config.cts",
    ".stylelintrc",
    ".stylelintrc.json",
    ".stylelintrc.yml",
    ".stylelintrc.yaml",
    ".stylelintrc.js",
    ".stylelintrc.cjs",
    ".stylelintrc.mjs",
)
_VULTURE_DEP = re.compile(r"vulture(?![\w.-])")


def _package_json(text: str | None) -> dict[str, object]:
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _requirement_lists(data: dict[str, object]) -> list[list[object]]:
    """Every list of requirement strings a pyproject.toml declares."""
    found: list[list[object]] = []
    project = data.get("project")
    if isinstance(project, dict):
        deps = project.get("dependencies")
        if isinstance(deps, list):
            found.append(deps)
        extras = project.get("optional-dependencies")
        if isinstance(extras, dict):
            found += [v for v in extras.values() if isinstance(v, list)]
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        found += [v for v in groups.values() if isinstance(v, list)]
    tool = data.get("tool")
    uv = tool.get("uv") if isinstance(tool, dict) else None
    legacy = uv.get("dev-dependencies") if isinstance(uv, dict) else None
    if isinstance(legacy, list):
        found.append(legacy)
    return found


def detect_tools(read: Callable[[str], str | None]) -> frozenset[str]:
    """Which optional tools the repo has set up: ``eslint``, ``stylelint``, ``vulture``.

    A hook for a tool the repo lacks only fails every commit, so sync leaves it
    out. ESLint and Stylelint count once they have a config file (or a
    package.json key); vulture once it is a dependency or has a ``[tool.vulture]``
    table outside the managed block (the block's own table proves nothing).
    """
    tools: set[str] = set()
    package = _package_json(read("package.json"))
    if (
        any(read(name) is not None for name in ESLINT_CONFIGS)
        or "eslintConfig" in package
    ):
        tools.add("eslint")
    if (
        any(read(name) is not None for name in STYLELINT_CONFIGS)
        or "stylelint" in package
    ):
        tools.add("stylelint")
    pyproject = read("pyproject.toml")
    if pyproject:
        try:
            data = tomllib.loads(without_block(pyproject))
        except tomllib.TOMLDecodeError:
            data = {}
        tool = data.get("tool")
        if (isinstance(tool, dict) and "vulture" in tool) or any(
            isinstance(req, str) and _VULTURE_DEP.match(req.strip().lower())
            for reqs in _requirement_lists(data)
            for req in reqs
        ):
            tools.add("vulture")
    return frozenset(tools)


_TOOL_HINTS = {
    "eslint": "no ESLint config file found",
    "stylelint": "no Stylelint config file found",
    "vulture": "vulture is not a dependency and there is no [tool.vulture] table "
    "outside the managed block",
}


def skipped_hooks(
    types: frozenset[ProjectType], tools: frozenset[str]
) -> list[tuple[str, str]]:
    """(hook name, reason) for each hook the types call for but the repo lacks."""
    wanted = {name for name, _ in lefthook_commands(types)}
    present = {name for name, _ in lefthook_commands(types, tools=tools)}
    return [(name, _TOOL_HINTS[name]) for name in sorted(wanted - present)]


def lefthook_commands(
    types: frozenset[ProjectType],
    ts_major: int | None = None,
    tools: frozenset[str] | None = None,
) -> list[tuple[str, str]]:
    """(command name, YAML text) for each pre-commit hook the types need.

    ``ts_major`` is the TypeScript major the repo uses: typescript-eslint cannot
    run on 7 or later, so the eslint hook then covers JavaScript and JSON only.
    ``tools`` is what :func:`detect_tools` found: eslint, stylelint and vulture
    hooks appear only for tools in it (``None`` means all of them).
    """
    kinds = effective(types)

    def has(tool: str) -> bool:
        return tools is None or tool in tools

    commands = [("prettier", _PRETTIER)]
    if kinds & {ProjectType.TYPESCRIPT, ProjectType.JAVASCRIPT} and has("eslint"):
        no_ts = ts_major is not None and ts_major >= 7
        commands.append(
            (
                "eslint",
                _staged(
                    "npx eslint --fix",
                    comment=(
                        "Lint JavaScript and JSON (typescript-eslint cannot run on "
                        "TypeScript 7, so TypeScript files are left to tsc)"
                        if no_ts
                        else "Lint JavaScript and TypeScript"
                    ),
                    name="eslint",
                    glob="*.{js,json}" if no_ts else "*.{js,ts,json}",
                ),
            )
        )
    if ProjectType.CSS in kinds and has("stylelint"):
        commands.append(
            (
                "stylelint",
                _staged(
                    "npx stylelint --fix",
                    comment="Lint CSS",
                    name="stylelint",
                    glob="*.css",
                ),
            )
        )
    if ProjectType.PYTHON in kinds:
        commands += [
            (
                "ruff-format",
                _staged(
                    "uv run ruff format",
                    comment="Format Python",
                    name="ruff-format",
                    glob="*.py",
                ),
            ),
            (
                "ruff-check",
                _staged(
                    "uv run ruff check --fix",
                    comment="Lint Python",
                    name="ruff-check",
                    glob="*.py",
                ),
            ),
        ]
        if has("vulture"):
            commands.append(
                (
                    "vulture",
                    _staged(
                        "uv run vulture",
                        fix=False,
                        comment="Find dead Python code",
                        name="vulture",
                        glob="*.py",
                    ),
                )
            )
    if ProjectType.DJANGO in kinds:
        commands.append(
            (
                "django-upgrade",
                _staged(
                    f"uv run django-upgrade --target-version {DJANGO_TARGET}",
                    comment="Upgrade Django code patterns",
                    name="django-upgrade",
                    glob="*.py",
                ),
            )
        )
    return commands


DJANGO_TARGET = "5.1"


def render_lefthook(
    version: str,
    types: frozenset[ProjectType],
    ts_major: int | None = None,
    tools: frozenset[str] | None = None,
) -> str:
    header = (
        f"# {stamp(version)}\n"
        "# Repo-specific hooks go in lefthook-local.yml, which lefthook merges in.\n"
    )
    body = "\n".join(text for _, text in lefthook_commands(types, ts_major, tools))
    return f"{header}pre-commit:\n  parallel: false\n  commands:\n{body}"


# ------------------------------------------------------------ pyproject.toml

DEFAULT_PYTHON = (3, 13)


@dataclass(frozen=True)
class Layout:
    """What the repo looks like, so the managed Python config fits it."""

    python: tuple[int, int] = DEFAULT_PYTHON
    ty_include: tuple[str, ...] = ("src",)
    testpaths: tuple[str, ...] | None = ("tests",)


_REQUIRES_PYTHON = re.compile(r"(?:>=|~=|==|>)\s*(\d+)\.(\d+)")
_NOT_PACKAGES = {"tests", "test", "node_modules", "venv", "env", "build", "dist"}


def python_lower_bound(pyproject: str | None) -> tuple[int, int]:
    """Oldest Python ``requires-python`` allows (3.13 when it says nothing)."""
    if pyproject:
        try:
            spec = tomllib.loads(pyproject).get("project", {}).get("requires-python")
        except tomllib.TOMLDecodeError:
            spec = None
        if isinstance(spec, str) and (match := _REQUIRES_PYTHON.search(spec)):
            return int(match.group(1)), int(match.group(2))
    return DEFAULT_PYTHON


def detect_layout(root: Path, pyproject: str | None) -> Layout:
    """ty ``include`` and pytest ``testpaths`` follow the repo's directories."""
    if (root / "src").is_dir():
        include = ("src",)
    else:
        packages = sorted(
            child.name
            for child in root.iterdir()
            if child.is_dir()
            and not child.name.startswith(".")
            and child.name not in _NOT_PACKAGES
            and (child / "__init__.py").is_file()
        )
        include = tuple(packages) or (".",)
    tests = next((n for n in ("tests", "test") if (root / n).is_dir()), None)
    return Layout(
        python=python_lower_bound(pyproject),
        ty_include=include,
        testpaths=(tests,) if tests else None,
    )


def _ruff(layout: Layout) -> str:
    major, minor = layout.python
    return f"""\
# Oldest Python this repo supports: [project] requires-python, else 3.13
target-version = "py{major}{minor}"

# Same as Black
line-length = 88

# Exclude common directories
exclude = [
    ".git",
    ".ruff_cache",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    "*.egg-info",
]
"""


_RUFF_LINT = """\
# Enable pycodestyle (`E`), pyflakes (`F`), isort (`I`), and more
select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings
    "F",      # pyflakes
    "I",      # isort
    "N",      # pep8-naming
    "UP",     # pyupgrade
    "B",      # flake8-bugbear
    "C4",     # flake8-comprehensions
    "SIM",    # flake8-simplify
    "TCH",    # flake8-type-checking
    "PTH",    # flake8-use-pathlib
]

# Ignore specific rules if needed
ignore = []

# Allow autofix for all enabled rules
fixable = ["ALL"]
unfixable = []
"""

_RUFF_FORMAT = """\
# Use double quotes for strings
quote-style = "double"

# Indent with spaces
indent-style = "space"

# Like Black, respect magic trailing commas
skip-magic-trailing-comma = false

# Like Black, automatically detect line ending
line-ending = "auto"
"""


def _pytest(layout: Layout) -> str:
    testpaths = (
        ""
        if layout.testpaths is None
        else f"testpaths = {_toml_list(layout.testpaths)}\n"
    )
    return testpaths + _PYTEST


def _toml_list(items: tuple[str, ...]) -> str:
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


_PYTEST = """\
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "--strict-markers",
    "--strict-config",
    "--showlocals",
]
"""


def _ty_environment(layout: Layout) -> str:
    return f'python-version = "{layout.python[0]}.{layout.python[1]}"\n'


def _ty_src(layout: Layout) -> str:
    return f"""\
# Files to check
include = {_toml_list(layout.ty_include)}

{_TY_EXCLUDE}"""


_TY_EXCLUDE = """\
# Files to exclude from type checking
exclude = [
    "**/__pycache__",
    "**/node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
]
"""

_TY_RULES = """\
# All rules default to "error" unless specified otherwise.
# Example: possibly-unresolved-reference = "warn"
"""

_TY_TERMINAL = """\
# Output format: "full" (default) or "concise"
output-format = "full"

# Treat warnings as errors
error-on-warning = false
"""

_VULTURE = """\
# Minimum confidence for reporting unused code (0-100)
min_confidence = 80

# Ignore certain patterns
ignore_names = [
    "*_test.py",
    "test_*.py",
]

# Paths to exclude
exclude = [
    ".venv/",
    "venv/",
    "node_modules/",
    "migrations/",  # Django migrations
]
"""

_DJANGO_UPGRADE = f"""\
# Target Django version
target-version = "{DJANGO_TARGET}"
"""


def python_tables(layout: Layout) -> list[tuple[str, str]]:
    """Ordered (header, body); each is one TOML table."""
    return [
        ("tool.ruff", _ruff(layout)),
        ("tool.ruff.lint", _RUFF_LINT),
        ("tool.ruff.format", _RUFF_FORMAT),
        ("tool.pytest.ini_options", _pytest(layout)),
        ("tool.ty.environment", _ty_environment(layout)),
        ("tool.ty.src", _ty_src(layout)),
        ("tool.ty.rules", _TY_RULES),
        ("tool.ty.terminal", _TY_TERMINAL),
        ("tool.vulture", _VULTURE),
    ]


DEFAULT_LAYOUT = Layout()
PYTHON_TABLES = python_tables(DEFAULT_LAYOUT)
DJANGO_TABLES: list[tuple[str, str]] = [("tool.django-upgrade", _DJANGO_UPGRADE)]
# Tables v1 copies carried that are gone in v2: dropped on migrate when stale.
RETIRED_TABLES = ["tool.pyupgrade", "tool.pyright"]


def pyproject_tables(
    types: frozenset[ProjectType], layout: Layout = DEFAULT_LAYOUT
) -> list[tuple[str, str]]:
    kinds = effective(types)
    if ProjectType.PYTHON not in kinds:
        return []
    tables = python_tables(layout)
    if ProjectType.DJANGO in kinds:
        tables += DJANGO_TABLES
    return tables


def table_value(header: str, body: str) -> dict[str, object]:
    """The parsed content of one managed table."""
    node: object = tomllib.loads(f"[{header}]\n{body}")
    for part in header.split("."):
        assert isinstance(node, dict)  # noqa: S101 - built from our own table text
        node = node[part]
    assert isinstance(node, dict)  # noqa: S101
    return node


def render_pyproject_block(
    version: str,
    types: frozenset[ProjectType],
    keep: list[str],
    layout: Layout = DEFAULT_LAYOUT,
) -> str | None:
    tables = [(h, b) for h, b in pyproject_tables(types, layout) if h not in keep]
    if not tables:
        return None
    body = "\n".join(f"[{header}]\n{text}" for header, text in tables)
    return wrap_block(stamp(version), body)


# -------------------------------------------------------------- AGENTS.md


def render_agents(version: str) -> str:
    header = (
        f"<!-- {stamp(version)} "
        "Put repo-specific rules in the repo's own AGENTS.md. -->\n\n"
    )
    return header + data_file("AGENTS.md")


# -------------------------------------------------------------- vendored JS

VENDOR_DIR = ".pedantry"


def _slash_header(version: str) -> str:
    return f"// {stamp(version)}\n"


def vendored_files(version: str, types: frozenset[ProjectType]) -> dict[str, str]:
    """Local copies of the npm configs, for repos that cannot install the package.

    Written under ``.pedantry/`` so the repo's own eslint.config.ts, tsconfig.json
    and stylelint.config.mjs stay unmanaged and can import or extend them.
    """
    kinds = effective(types)
    files_out: dict[str, str] = {}
    header = _slash_header(version)
    js = kinds & {ProjectType.TYPESCRIPT, ProjectType.JAVASCRIPT}
    if js:
        files_out[f"{VENDOR_DIR}/eslint.config.ts"] = header + data_file(
            "js", "eslint.js"
        )
        for name in (
            "merge",
            "vitest",
            "rollup",
            "web-test-runner",
            "custom-elements-manifest",
        ):
            files_out[f"{VENDOR_DIR}/helpers/{name}.js"] = header + data_file(
                "js", f"{name}.js"
            )
    if ProjectType.TYPESCRIPT in kinds:
        files_out[f"{VENDOR_DIR}/tsconfig.base.json"] = header + data_file(
            "js", "tsconfig.base.json"
        )
    if ProjectType.CSS in kinds:
        files_out[f"{VENDOR_DIR}/stylelint.config.mjs"] = header + data_file(
            "js", "stylelint.js"
        )
    return files_out


def vendor_install_hint(types: frozenset[ProjectType]) -> str | None:
    """The npm packages vendored configs import (the npm package would bring them)."""
    kinds = effective(types)
    packages: list[str] = []
    if kinds & {ProjectType.TYPESCRIPT, ProjectType.JAVASCRIPT}:
        packages += [
            "eslint", "@eslint/js", "@eslint/json", "eslint-config-prettier",
            "globals", "typescript-eslint", "jiti",
        ]  # fmt: skip
    if ProjectType.CSS in kinds:
        packages += [
            "stylelint",
            "stylelint-config-standard",
            "stylelint-config-recess-order",
        ]
    if not packages:
        return None
    return "npm install --save-dev " + " ".join(packages)
