"""Document, tenant and chunk identifiers as the three systems write them.

The same document can be ``2329961`` (a number) in a database column, ``"2329961"`` (text) in a file name and
``2329961.0`` in a payload that went through a spreadsheet or a JSON library that reads every number as a decimal.
They are the same document, so identifiers are compared as text, and a whole number is always written the way
``str(int)`` writes it: no ``.0``, no ``.00``, no exponent.

Only the *type* is reconciled here. Anything that changes the characters of an identifier (spaces, upper and lower
case, leading zeros, file extensions) is a different question: those identifiers do not match, and the setup check
says so instead of guessing.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

# the text a whole number has when written by str(int): no sign on zero, no leading zeros, at most 18 digits (fits int64)
_PLAIN_INT = re.compile(r"^(0|-?[1-9][0-9]{0,17})$")
_DIGITS = re.compile(r"^[0-9]+$")


def normalize_id(value: Any) -> str | None:
    """An identifier as text: ``170``, ``170.0``, ``Decimal("170.00")`` and ``"170"`` all become ``"170"``."""
    if value is None:
        return None
    if isinstance(value, bool):  # a flag is not a number here
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, Decimal):
        if value.is_finite() and value == value.to_integral_value():
            return str(int(value))
        return str(value)
    return value if isinstance(value, str) else str(value)


def number_form(text: str) -> int | None:
    """The whole number an identifier stands for, when it is written exactly the way a number is written.

    ``"170"`` -> 170, but ``"0170"``, ``" 170"`` and ``"170.0"`` -> None: they are text, a number would not be stored that way."""
    return int(text) if isinstance(text, str) and _PLAIN_INT.match(text) else None


def id_kind(value: Any) -> str:
    """How an identifier is stored: ``integer``, ``decimal`` (2329961.0), ``digits`` (text made only of digits), ``text`` or ``other``."""
    if isinstance(value, bool):
        return "other"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, (float, Decimal)):
        return "decimal"
    if isinstance(value, str):
        return "digits" if _DIGITS.match(value) else "text"
    return "other"


def loose_id(text: str) -> str:
    """An identifier with the differences people do not mean removed (spaces, case, leading zeros), only used to *suggest* a match."""
    t = text.strip().lower()
    stripped = t.lstrip("0")
    return stripped if _DIGITS.match(t) and stripped else t
