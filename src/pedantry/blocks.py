"""Marker blocks: managed text inside a file the repo also edits."""

from pedantry.model import BLOCK_BEGIN, BLOCK_END


def find_block(text: str) -> tuple[int, int] | None:
    """Line index range [start, end] (inclusive) of the managed block, if any."""
    lines = text.split("\n")
    start = next(
        (i for i, line in enumerate(lines) if line.strip() == BLOCK_BEGIN), None
    )
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].strip() == BLOCK_END),
        None,
    )
    if end is None:
        return None
    return start, end


def without_block(text: str) -> str:
    """The text with the managed block removed."""
    span = find_block(text)
    if span is None:
        return text
    lines = text.split("\n")
    del lines[span[0] : span[1] + 1]
    return "\n".join(lines)


def put_block(text: str | None, block: str, *, at_top: bool = False) -> str:
    """Replace the managed block in ``text`` or add it (top or bottom).

    ``block`` is the full block including both marker lines, with no trailing
    newline. Everything outside the markers is returned unchanged.
    """
    if not text:
        return block + "\n"
    span = find_block(text)
    lines = text.split("\n")
    if span is not None:
        lines[span[0] : span[1] + 1] = block.split("\n")
        return "\n".join(lines)
    if at_top:
        return block + "\n\n" + text
    separator = (
        "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    )
    return text + separator + block + "\n"


def wrap_block(stamp: str, body: str) -> str:
    """Build a marker block around ``body`` with the version stamp inside."""
    body = body.strip("\n")
    return f"{BLOCK_BEGIN}\n# {stamp}\n{body}\n{BLOCK_END}"
