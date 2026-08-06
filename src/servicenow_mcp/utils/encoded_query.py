"""Putting a caller's value into a ServiceNow encoded query.

Why this deletes rather than escapes
------------------------------------
An encoded query is ``field=value^field2=value2^ORfield3=value3``. ``^``
separates conditions and ``^OR`` / ``^NQ`` change how they combine, so a value
that contains one stops being a value and becomes query STRUCTURE.

There is no documented escape for ``^`` inside a value, and this repo had five
different guesses at one: ``^``→``^^`` plus ``=``→``\\=`` in four modules, plain
deletion in three others, and nothing at all in the two service modules an
adversarial review found. Five answers to one question means at least four are
wrong, and nobody could say which.

The ``^^`` form has never been proven against a live instance, and CLAUDE.md
rule 7 is about exactly that: **ServiceNow accepts what it does not understand.**
An encoded-query condition the server cannot parse is DROPPED, and a query with
a dropped condition returns the WHOLE TABLE. So a wrong escape does not fail
loudly — it fails toward over-fetch, and the caller reads 808 rows as an answer.

Deleting the structural character cannot be wrong about the server, because what
comes out contains nothing the server has to interpret. It changes the search
TERM, which is a bounded and visible cost — and this reports what it removed so
the caller can say so rather than quietly answering a different question.

What is deliberately NOT removed
--------------------------------
``=`` stays. It cannot start a new condition: ``category=a=b`` is one condition
whose value happens to contain ``=``. Stripping it would corrupt legitimate
values (a description containing "a=b") to buy nothing. Two older helpers in
this repo strip it; they are not a reason to.

``,`` stays, for the same reason — with one caveat that belongs to the caller,
not here: inside an ``IN`` list a comma IS a separator, so a value going into
``fieldIN...`` needs its own handling. Nothing in this repo builds an ``IN``
clause from free-typed text today; if something does, it must not reach for this
function and assume it is covered.
"""

from dataclasses import dataclass
from typing import Tuple

# `^` is the only character that can end a condition and begin another, which is
# what makes it the whole risk. CR/LF ride along because they break the query
# string as an HTTP parameter rather than as a query.
_STRUCTURAL: Tuple[str, ...] = ("^", "\r", "\n")


@dataclass(frozen=True)
class SafeValue:
    """A value fit for an encoded query, plus what had to go. Never just a str.

    The report is the point. A silently-cleaned value answers a different
    question than the one asked, and the caller is the only layer that can say
    so — see :meth:`note`.
    """

    value: str
    removed: Tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.removed)

    def note(self, *, field: str = "") -> str:
        """One line for a tool response, or "" when nothing was touched."""
        if not self.removed:
            return ""
        what = ", ".join(repr(char) for char in self.removed)
        where = f" in '{field}'" if field else ""
        return (
            f"Removed {what}{where} before querying: those characters are encoded-query "
            f"structure, not text, so the filter searched for '{self.value}' instead."
        )

    def __str__(self) -> str:  # so an f-string cannot silently embed the wrapper
        return self.value


def safe_value(value: object) -> SafeValue:
    """Strip encoded-query structure out of ``value``. Never raises.

    ``None`` and non-strings become "" rather than the string "None" — a filter
    built from the literal text "None" matches nothing and looks like a real
    empty result.
    """
    if value is None:
        return SafeValue("")
    text = str(value)
    removed = tuple(char for char in _STRUCTURAL if char in text)
    if not removed:
        return SafeValue(text)
    for char in removed:
        text = text.replace(char, "")
    return SafeValue(text, removed)


def encoded_value(value: object) -> str:
    """``safe_value`` when the caller genuinely has nowhere to put the report.

    Prefer :func:`safe_value` and surface ``note()``. This exists so a helper
    being migrated off a hand-rolled escape does not have to grow a return
    value in the same change.
    """
    return safe_value(value).value


__all__ = ["SafeValue", "encoded_value", "safe_value"]
