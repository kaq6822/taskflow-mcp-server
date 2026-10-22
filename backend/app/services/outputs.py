from __future__ import annotations

import re

# A step publishes a value on the run record by printing, on stdout,
#
#     ::output <key>=<value>
#
# e.g. `::output commit=9535057…`. Keys share the param-name alphabet so the
# two vocabularies read the same; the value is the rest of the line verbatim.
# A later line with the same key — from the same step, a retry, or a later
# step — overwrites the earlier one.
_PREFIX = "::output "
_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
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
    if not value:
        raise OutputLineError(f"output {key!r} has an empty value")
    if _CONTROL.search(value) or len(value) > MAX_VALUE_LEN:
        raise OutputLineError(
            f"output {key!r} must be at most {MAX_VALUE_LEN} chars without control characters"
        )
    return key, value
