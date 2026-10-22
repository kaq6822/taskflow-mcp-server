from __future__ import annotations

import re

# A step publishes a value on the run record by printing, on stdout,
#
#     ::output <key>=<value>
#
# e.g. `::output commit=9535057…`. Keys share the param-name alphabet so the
# two vocabularies read the same; the value is the rest of the line. Only a
# step that ends SUCCESS gets its outputs recorded, and a later value for the
# same key wins (the engine logs a warning when one is overwritten).
_PREFIX = "::output "
_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
# C0/C1 controls, Unicode line separators, and U+FFFD (what undecodable bytes
# become) — none belong in a value a client will compare as a string.
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f  �]")
MAX_VALUE_LEN = 1024


class OutputLineError(ValueError):
    """The line starts with `::output ` but is not a usable `key=value`."""


def parse_output_line(text: str) -> tuple[str, str] | None:
    """Return (key, value) for an output line, None for any other line.

    Raises OutputLineError for a line that claims to be an output but is
    malformed, so the caller can warn instead of silently dropping it.
    """
    if not text.startswith(_PREFIX):
        return None
    body = text[len(_PREFIX) :].rstrip("\r")
    key, sep, value = body.partition("=")
    if not sep or not _KEY.fullmatch(key):
        raise OutputLineError(f"expected `::output <key>=<value>`, got {text!r}")
    if not value.strip():
        raise OutputLineError(f"output {key!r} has an empty value")
    # `echo "::output commit=$sha "` would otherwise store a value that never
    # compares equal to the real commit.
    if value != value.strip():
        raise OutputLineError(f"output {key!r} has leading or trailing whitespace")
    if _CONTROL.search(value) or len(value) > MAX_VALUE_LEN:
        raise OutputLineError(
            f"output {key!r} must be at most {MAX_VALUE_LEN} chars without control characters"
        )
    return key, value
