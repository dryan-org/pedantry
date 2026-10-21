"""Small, forgiving parsers for the files sync and migrate edit.

They split text into units (TOML tables, editorconfig sections, lefthook
commands) without needing a YAML or TOML-editing dependency. Results that are
written back are always re-validated by the caller.
"""

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field

# ---------------------------------------------------------------- hashing


def digest(value: object) -> str:
    """Stable short hash of a JSON-able value (used for legacy matching)."""
    data = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()[:16]


# ------------------------------------------------------------------- TOML

_TOML_HEADER = re.compile(r"^\[\[?\s*([A-Za-z0-9_.\-\"' ]+?)\s*\]\]?\s*(?:#.*)?$")


@dataclass
class TomlSection:
    """A table: ``header`` is None for the text before the first table."""

    header: str | None
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def value(self) -> dict[str, object]:
        """The table's own keys, parsed (sub-tables are separate sections)."""
        body = "\n".join(self.lines[1:] if self.header is not None else self.lines)
        if self.header is None:
            return tomllib.loads(body)
        node: object = tomllib.loads(f"[{self.header}]\n{body}")
        for part in self.header.split("."):
            if not isinstance(node, dict):
                raise KeyError(part)
            node = node[part.strip("\"'")]
        if not isinstance(node, dict):
            raise KeyError(self.header)
        return node


def normalize_header(raw: str) -> str:
    return ".".join(part.strip() for part in raw.split("."))


def split_toml(text: str) -> list[TomlSection]:
    """Split TOML text into table sections, line-preserving."""
    sections = [TomlSection(None)]
    multiline: str | None = None
    for line in text.split("\n"):
        if multiline is None:
            match = _TOML_HEADER.match(line)
            if match and not line.startswith("[["):
                sections.append(TomlSection(normalize_header(match.group(1)), [line]))
                continue
            if match:  # array of tables: keep as its own section, never managed
                sections.append(
                    TomlSection(f"[[{normalize_header(match.group(1))}]]", [line])
                )
                continue
        for quote in ('"""', "'''"):
            if line.count(quote) % 2 == 1:
                multiline = None if multiline == quote else (multiline or quote)
        sections[-1].lines.append(line)
    return sections


def join_toml(sections: list[TomlSection]) -> str:
    return "\n".join(line for section in sections for line in section.lines)


# ---------------------------------------------------------------- JSONC


def strip_jsonc(text: str) -> str:
    """Remove comments and trailing commas so ``json.loads`` can read JSONC."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        char = text[i]
        if char == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(char)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def dump_json(value: object, indent: int = 2, _level: int = 0, width: int = 80) -> str:
    """Pretty JSON that keeps short scalar arrays on one line (Prettier-like)."""
    pad = " " * indent * (_level + 1)
    end = " " * indent * _level
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [
            f"{pad}{json.dumps(key)}: {dump_json(item, indent, _level + 1, width)}"
            for key, item in value.items()
        ]
        return "{\n" + ",\n".join(items) + f"\n{end}}}"
    if isinstance(value, list):
        inline = (
            "["
            + ", ".join(json.dumps(item, ensure_ascii=False) for item in value)
            + "]"
        )
        scalar = all(not isinstance(item, dict | list) for item in value)
        if scalar and len(inline) + len(end) <= width:
            return inline
        items = [f"{pad}{dump_json(item, indent, _level + 1, width)}" for item in value]
        return "[\n" + ",\n".join(items) + f"\n{end}]"
    return json.dumps(value, ensure_ascii=False)


def loads_jsonc(text: str) -> object:
    return json.loads(strip_jsonc(text))


# ----------------------------------------------------------- editorconfig


@dataclass
class EditorConfigSection:
    header: str | None
    lines: list[str] = field(default_factory=list)

    def properties(self) -> dict[str, str]:
        props: dict[str, str] = {}
        for line in self.lines:
            stripped = line.strip()
            if not stripped or stripped[0] in "#;[":
                continue
            key, _, value = stripped.partition("=")
            props[key.strip().lower()] = value.strip().lower()
        return props


def split_editorconfig(text: str) -> list[EditorConfigSection]:
    sections = [EditorConfigSection(None)]
    for line in text.split("\n"):
        match = re.match(r"^\[(.+)\]\s*$", line)
        if match:
            sections.append(EditorConfigSection(match.group(1), [line]))
        else:
            sections[-1].lines.append(line)
    return sections


# --------------------------------------------------------------- lefthook


@dataclass
class LefthookCommand:
    name: str
    lines: list[str]  # verbatim, leading comments included

    def normalized(self) -> list[str]:
        """Comment-free, whitespace-trimmed lines, for comparing commands."""
        result: list[str] = []
        for line in self.lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("stage_fixed:"):
                stripped = re.sub(r"\s+#.*$", "", stripped)
            result.append(stripped)
        return result

    def key(self) -> str:
        return digest(self.normalized())


@dataclass
class Lefthook:
    """A lefthook.yml split into the pre-commit commands and everything else."""

    commands: list[LefthookCommand] = field(default_factory=list)
    # Other keys under ``pre-commit`` (parallel, piped, ...), verbatim lines.
    hook_options: list[str] = field(default_factory=list)
    # Everything outside ``pre-commit`` (other hooks, output, ...), verbatim.
    other: list[str] = field(default_factory=list)


def parse_lefthook(text: str) -> Lefthook:
    result = Lefthook()
    lines = text.split("\n")
    state = "other"  # other | hook | commands
    pending_comments: list[str] = []
    current: LefthookCommand | None = None

    def flush_comments_to(target: list[str]) -> None:
        target.extend(pending_comments)
        pending_comments.clear()

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if stripped and indent == 0 and not stripped.startswith("#"):
            current = None
            if stripped.rstrip() == "pre-commit:":
                state = "hook"
                pending_comments.clear()
                continue
            state = "other"
        if state == "other":
            result.other.append(line)
            continue
        if not stripped:
            if current is not None:
                current.lines.append(line)
            continue
        if stripped.startswith("#"):
            pending_comments.append(line)
            continue
        if state == "hook" and indent == 2:
            current = None
            if stripped == "commands:":
                state = "commands"
                pending_comments.clear()
            else:
                flush_comments_to(result.hook_options)
                result.hook_options.append(line)
            continue
        if state == "commands" and indent == 2:
            # A sibling key of ``commands`` (e.g. ``parallel`` after it).
            state = "hook"
            current = None
            flush_comments_to(result.hook_options)
            result.hook_options.append(line)
            continue
        if state == "commands" and indent == 4:
            match = re.match(r"^([\w.\-]+):\s*(?:#.*)?$", stripped)
            if match:
                current = LefthookCommand(match.group(1), list(pending_comments))
                pending_comments.clear()
                current.lines.append(line)
                result.commands.append(current)
                continue
        if current is not None:
            flush_comments_to(current.lines)
            current.lines.append(line)
        else:
            flush_comments_to(result.hook_options)
            result.hook_options.append(line)
    while (
        result.commands
        and result.commands[-1].lines
        and not result.commands[-1].lines[-1].strip()
    ):
        result.commands[-1].lines.pop()
    return result
