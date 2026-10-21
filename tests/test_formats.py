import json

from pedantry.formats import (
    dump_json,
    loads_jsonc,
    parse_lefthook,
    split_editorconfig,
    split_toml,
    strip_jsonc,
)


def test_split_toml_ignores_header_lookalikes_in_multiline_strings() -> None:
    text = 'a = """\n[not.a.header]\n"""\n\n[real]\nx = 1\n'

    assert [s.header for s in split_toml(text)] == [None, "real"]


def test_split_toml_normalizes_headers_and_parses_values() -> None:
    sections = split_toml(
        '[ tool . ruff ]\nline-length = 88\n\n[tool.ruff.lint]\nselect = ["E"]\n'
    )

    assert [s.header for s in sections] == [None, "tool.ruff", "tool.ruff.lint"]
    assert sections[1].value() == {"line-length": 88}


def test_split_toml_round_trips_text() -> None:
    from pedantry.formats import join_toml

    text = '[project]\nname = "x"\n\n# note\n[tool.a]\nb = [\n  1,\n  2,\n]\n'

    assert join_toml(split_toml(text)) == text


def test_strip_jsonc_keeps_urls_in_strings() -> None:
    text = '{\n  // comment\n  "a": "http://x//y", /* c */\n  "b": [1, 2,],\n}\n'

    assert loads_jsonc(text) == {"a": "http://x//y", "b": [1, 2]}
    assert "comment" not in strip_jsonc(text)


def test_dump_json_keeps_short_arrays_inline() -> None:
    value = {"a": ["x", "y"], "b": {"c": [], "d": {}}, "long": ["z" * 50, "z" * 50]}

    out = dump_json(value)

    assert '"a": ["x", "y"]' in out
    assert json.loads(out) == value
    assert out.count("\n") > 5


def test_parse_lefthook_splits_commands_options_and_other_hooks() -> None:
    text = (
        "pre-commit:\n  parallel: true\n  commands:\n"
        "    # Format\n    prettier:\n      run: a\n\n"
        "    mine:\n      run: |\n        echo 1\n"
        "pre-push:\n  commands:\n    t:\n      run: b\n"
    )

    parsed = parse_lefthook(text)

    assert [c.name for c in parsed.commands] == ["prettier", "mine"]
    assert parsed.commands[0].lines[0].strip() == "# Format"
    assert [line.strip() for line in parsed.hook_options] == ["parallel: true"]
    assert [line.strip() for line in parsed.other if line.strip()] == [
        "pre-push:",
        "commands:",
        "t:",
        "run: b",
    ]


def test_lefthook_command_key_ignores_comments_and_whitespace() -> None:
    a = parse_lefthook(
        "pre-commit:\n  commands:\n    x:\n      run: a\n      stage_fixed: true\n"
    )
    b = parse_lefthook(
        "pre-commit:\n  commands:\n    # c\n    x:\n      run: a   \n"
        "      stage_fixed: true # why\n"
    )

    assert a.commands[0].key() == b.commands[0].key()


def test_split_editorconfig_properties_are_case_insensitive() -> None:
    sections = split_editorconfig("root = true\n[*.py]\nIndent_Size = 4\n# c\n")

    assert sections[0].header is None
    assert sections[1].properties() == {"indent_size": "4"}
