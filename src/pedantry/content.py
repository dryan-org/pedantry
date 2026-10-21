"""The text pedantry manages, as a function of version and project types."""

import tomllib
from importlib.resources import files

from pedantry.blocks import wrap_block
from pedantry.model import MANAGED_PHRASE, ProjectType, effective

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


def lefthook_commands(types: frozenset[ProjectType]) -> list[tuple[str, str]]:
    """(command name, YAML text) for each pre-commit hook the types need."""
    kinds = effective(types)
    commands = [("prettier", _PRETTIER)]
    if kinds & {ProjectType.TYPESCRIPT, ProjectType.JAVASCRIPT}:
        commands.append(
            (
                "eslint",
                _staged(
                    "npx eslint --fix",
                    comment="Lint JavaScript and TypeScript",
                    name="eslint",
                    glob="*.{js,ts,json}",
                ),
            )
        )
    if ProjectType.CSS in kinds:
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
            (
                "vulture",
                _staged(
                    "uv run vulture",
                    fix=False,
                    comment="Find dead Python code",
                    name="vulture",
                    glob="*.py",
                ),
            ),
        ]
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


def render_lefthook(version: str, types: frozenset[ProjectType]) -> str:
    header = (
        f"# {stamp(version)}\n"
        "# Repo-specific hooks go in lefthook-local.yml, which lefthook merges in.\n"
    )
    body = "\n".join(text for _, text in lefthook_commands(types))
    return f"{header}pre-commit:\n  parallel: false\n  commands:\n{body}"


# ------------------------------------------------------------ pyproject.toml

_RUFF = """\
# Target Python 3.14+ (adjust as needed for your projects)
target-version = "py314"

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

_PYTEST = """\
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "--strict-markers",
    "--strict-config",
    "--showlocals",
]
"""

_TY_ENVIRONMENT = """\
python-version = "3.14"
"""

_TY_SRC = """\
# Files to check
include = ["src"]

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

# Ordered (header, body). Each is one TOML table.
PYTHON_TABLES: list[tuple[str, str]] = [
    ("tool.ruff", _RUFF),
    ("tool.ruff.lint", _RUFF_LINT),
    ("tool.ruff.format", _RUFF_FORMAT),
    ("tool.pytest.ini_options", _PYTEST),
    ("tool.ty.environment", _TY_ENVIRONMENT),
    ("tool.ty.src", _TY_SRC),
    ("tool.ty.rules", _TY_RULES),
    ("tool.ty.terminal", _TY_TERMINAL),
    ("tool.vulture", _VULTURE),
]
DJANGO_TABLES: list[tuple[str, str]] = [("tool.django-upgrade", _DJANGO_UPGRADE)]
# Tables v1 copies carried that are gone in v2: dropped on migrate when stale.
RETIRED_TABLES = ["tool.pyupgrade", "tool.pyright"]


def pyproject_tables(types: frozenset[ProjectType]) -> list[tuple[str, str]]:
    kinds = effective(types)
    if ProjectType.PYTHON not in kinds:
        return []
    tables = list(PYTHON_TABLES)
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
    version: str, types: frozenset[ProjectType], keep: list[str]
) -> str | None:
    tables = [(h, b) for h, b in pyproject_tables(types) if h not in keep]
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
