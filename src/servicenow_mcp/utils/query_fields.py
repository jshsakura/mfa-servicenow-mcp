"""Field names in an encoded query, and whether the table actually has them.

Why this exists
---------------
Measured on a live instance, the same mistake has two symptoms and neither says
what is wrong:

- on a normal table, a condition naming a column the table does not have is
  **dropped**, the read comes back ``success: true`` with rows, and nothing
  anywhere mentions it. Proven: ``incident`` + ``definitely_not_a_field=xyz``
  returns rows.
- on a scoped table with a role-gated ACL, the same mistake comes back
  **403 Forbidden** — which reads as a permissions problem, and the tool's own
  403 hint then names two causes (scope context, account ACL) and not this one.
  That hint cost three days of investigation on the wrong branch: ACL scripts,
  ``admin_overrides``, seven sibling tables, a role that turned out to be
  irrelevant. The field name was never checked because nothing suggested it.

A confident enumeration that excludes the answer is worse than no hint at all:
it hands the reader a search space the answer is not in.

What this checks, and what it refuses to claim
----------------------------------------------
``unknown_query_fields`` returns ``None`` when it could not find out — an
unreadable dictionary is not a clean bill of health, and the caller must be able
to tell that apart from "every field exists".

Inheritance is the trap. ``sys_dictionary`` rows live on the table that DECLARES
the column, so ``incident`` alone does not list ``short_description`` (declared
on ``task``). Validating against one table's rows would report inherited columns
as unknown — the same false confidence in the opposite direction, and far more
damaging here because it would send someone chasing a field that is fine. So the
ancestry is walked via ``sys_db_object.super_class`` and the union is used; if
any step of that walk fails, the answer is ``None``.

The parser is deliberately timid. A token is only reported as a field when it
looks unambiguously like one; anything it cannot parse is skipped rather than
guessed at, because a false "this field does not exist" is exactly the kind of
wrong signpost this module exists to remove.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

# Conditions are joined by `^`; `^OR` and `^NQ` are the same separator carrying a
# combinator. Splitting on `^` and stripping the combinator off the front of each
# piece handles all three.
_COMBINATORS = ("OR", "NQ")

# Sort prefixes: the rest of the token is a field name.
_ORDER_PREFIXES = ("ORDERBYDESC", "ORDERBY")

# Operators that can follow a field name, longest first so `>=` is not read as
# `>` and `ISNOTEMPTY` is not read as `ISEMPTY`. Only used to find where the
# field name ends.
_OPERATORS: Tuple[str, ...] = (
    "ISNOTEMPTY",
    "ISEMPTY",
    "ANYTHING",
    "STARTSWITH",
    "ENDSWITH",
    "NOT LIKE",
    "NOTLIKE",
    "LIKE",
    "NOT IN",
    "NOTIN",
    "IN",
    "BETWEEN",
    "SAMEAS",
    "NSAMEAS",
    "DYNAMIC",
    "INSTANCEOF",
    "VALCHANGES",
    "CHANGESFROM",
    "CHANGESTO",
    # Safe to list now that the field is matched first: searching for "ON"
    # inside the string would have cut `sys_created_on` in half.
    "ONTODAY",
    "ON",
    "!=",
    ">=",
    "<=",
    "=",
    ">",
    "<",
)

# Whole conditions that are not `field<op>value` at all. `EQ`/`NQ` ARE the whole
# condition, so they match exactly — as prefixes they swallowed every field
# starting with those two letters (`equipment`, `nqueue`), which then went
# unchecked without anyone being told. The rest genuinely carry a payload after
# the prefix. Compared case-sensitively: all of these are written uppercase and
# a field name is not.
_NON_FIELD_EXACT = ("EQ", "NQ")
_NON_FIELD_PREFIXES = ("123TEXTQUERY321", "GOTO", "RLQUERY")

# A field name as ServiceNow writes them. Dot-walks are allowed; only the first
# segment is checkable here, because the far side lives on another table.
_FIELD = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_.]+)?$")

# The same shape, anchored and capturing, for reading a name off the front of a
# condition. Lowercase-only is load-bearing: it is what makes the boundary
# between `main_index` and the `IN` operator unambiguous.
_FIELD_HEAD = re.compile(r"^([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)")


def query_field_names(query: str) -> List[str]:
    """First-segment field names this encoded query filters or sorts on.

    Skips anything it cannot read as a field. Order-preserving, de-duplicated.
    """
    names: List[str] = []
    seen: Set[str] = set()
    for raw in str(query or "").split("^"):
        piece = raw.strip()
        if not piece:
            continue
        # ORDER prefixes are checked before the combinators because `ORDERBY`
        # starts with `OR`: stripping the combinator first turns
        # `^ORDERBYDESCsys_updated_on` into `DERBYDESC...` and the sort field is
        # lost. Longer and more specific wins.
        upper = piece.upper()
        # Case-SENSITIVE on purpose. A combinator is always written uppercase
        # (`^OR`, `^NQ`) and a field name is always lowercase — the same
        # premise `_FIELD_HEAD` already relies on. Comparing case-insensitively
        # ate the first two letters of every field starting with those letters:
        # `order_typeISNOTEMPTY` became `der_typeISNOTEMPTY`, and the caller was
        # told its own table has no column `der_type`.
        if not any(upper.startswith(prefix) for prefix in _ORDER_PREFIXES):
            for combinator in _COMBINATORS:
                if piece.startswith(combinator) and len(piece) > len(combinator):
                    piece = piece[len(combinator) :]
                    upper = piece.upper()
                    break
        if piece in _NON_FIELD_EXACT or any(
            piece.startswith(prefix) for prefix in _NON_FIELD_PREFIXES
        ):
            continue

        candidate = ""
        for prefix in _ORDER_PREFIXES:
            if upper.startswith(prefix):
                candidate = piece[len(prefix) :].strip()
                break
        else:
            # Match the FIELD first and require an operator to follow it, rather
            # than searching for an operator inside the string. Searching finds
            # the `IN` in `main_index=1` and cuts the name to `ma`, which reports
            # a real column as unknown — the false signpost this module exists to
            # remove, produced by the module itself. ServiceNow field names are
            # lowercase, operators are not, so the lowercase run IS the boundary.
            match = _FIELD_HEAD.match(piece)
            if not match:
                continue
            candidate = match.group(1)
            rest = piece[match.end() :]
            if rest and not any(rest.startswith(operator) for operator in _OPERATORS):
                # Something followed the name that is not an operator we know.
                # Skipping is the timid answer, and timid is correct here.
                continue

        if not candidate or not _FIELD.match(candidate):
            continue
        root = candidate.split(".", 1)[0]
        if root not in seen:
            seen.add(root)
            names.append(root)
    return names


def _rows(auth_manager: Any, url: str, params: Dict[str, Any], timeout: int) -> Optional[list]:
    """One Table API read, or None. None is 'could not find out', always."""
    try:
        response = auth_manager.make_request("GET", url, params=params, timeout=timeout)
        payload = response.json() if hasattr(response, "json") else {}
        result = payload.get("result")
        return result if isinstance(result, list) else None
    except Exception as exc:  # noqa: BLE001 - a diagnostic must never raise
        logger.debug("Field-check read failed (%s): %s", url, exc)
        return None


def table_ancestry(config: Any, auth_manager: Any, table: str) -> Optional[List[str]]:
    """``table`` plus every table it extends, or None if the walk broke.

    Bounded: a cycle or an unexpectedly deep hierarchy stops the walk and returns
    None rather than a partial list, because a partial ancestry produces exactly
    the false "unknown field" this module must not produce.
    """
    url = f"{config.instance_url}/api/now/table/sys_db_object"
    timeout = getattr(config, "timeout", 15)
    chain: List[str] = []
    # `super_class` is a REFERENCE to sys_db_object, so its raw value is a
    # sys_id and its display value is the table's LABEL ("Task"), not its name
    # ("task"). Measured on a live instance, which is the only place this could
    # have been measured: a mock answers with whatever key it was written with.
    # Walking on the label finds no sys_dictionary rows for the parent, and every
    # inherited column then reports as unknown — the precise false signpost this
    # module exists to remove. So the walk is by sys_id and the name is read off
    # the parent record.
    query = f"name={table}"
    for _ in range(12):
        rows = _rows(
            auth_manager,
            url,
            {
                "sysparm_query": query,
                "sysparm_fields": "name,super_class",
                "sysparm_limit": 1,
            },
            timeout,
        )
        if rows is None:
            return None
        if not rows:
            # Nothing above it, or a table nobody declared. Either way the walk
            # is finished rather than broken; the table itself still gets checked.
            return chain or [table]
        name = str(rows[0].get("name") or "").strip()
        if not name or name in chain:
            logger.debug("Cycle or unnamed row in the table hierarchy at %s", name or "?")
            return None
        chain.append(name)
        parent = rows[0].get("super_class") or ""
        if isinstance(parent, dict):
            parent = parent.get("value") or ""
        parent = str(parent).strip()
        if not parent:
            return chain
        query = f"sys_id={parent}"
    logger.debug("Table hierarchy for %s did not terminate within the bound", table)
    return None


# A table's column set does not change during a session, and the check costs an
# ancestry walk plus a dictionary read — worth paying once per table, never
# twice. A failed lookup is deliberately NOT cached: "could not find out" must
# stay retryable, or one transient error would silence the check for the session.
_COLUMN_MEMO: Dict[Tuple[str, str], Set[str]] = {}


def forget_columns() -> None:
    """Drop the memo. For tests, and for a caller that changed a table's schema."""
    _COLUMN_MEMO.clear()


def table_columns(config: Any, auth_manager: Any, table: str) -> Optional[Set[str]]:
    """Every column ``table`` has, inherited ones included. None when unknown."""
    memo_key = (str(getattr(config, "instance_url", "")), table)
    cached = _COLUMN_MEMO.get(memo_key)
    if cached is not None:
        return cached
    ancestry = table_ancestry(config, auth_manager, table)
    if not ancestry:
        return None
    url = f"{config.instance_url}/api/now/table/sys_dictionary"
    rows = _rows(
        auth_manager,
        url,
        {
            "sysparm_query": "nameIN" + ",".join(ancestry),
            "sysparm_fields": "element",
            "sysparm_limit": 5000,
        },
        getattr(config, "timeout", 15),
    )
    if rows is None:
        return None
    columns = {str(row.get("element") or "").strip() for row in rows}
    columns.discard("")
    if not columns:
        # A table with no dictionary rows at all means the read did not do what
        # it looks like it did. Refusing to answer beats reporting every field
        # in the query as unknown.
        return None
    # Present on every record and not always declared in sys_dictionary.
    columns.update(
        {"sys_id", "sys_created_on", "sys_updated_on", "sys_created_by", "sys_updated_by"}
    )
    _COLUMN_MEMO[memo_key] = columns
    return columns


def unknown_query_fields(
    config: Any, auth_manager: Any, table: str, query: str
) -> Optional[List[str]]:
    """Fields the query names that ``table`` does not have.

    ``[]`` means checked and clean. ``None`` means the check could not be made —
    never conflate the two, and never print a clean verdict on a None.
    """
    names = query_field_names(query)
    if not names:
        return []
    columns = table_columns(config, auth_manager, table)
    if columns is None:
        return None
    missing = [name for name in names if name not in columns]
    if not missing:
        return []

    # The accusing branch does not get to use the cache. A memo taken before
    # someone added a column is a stale copy of a server fact, and spending it
    # on "this column does not exist" is the exact failure this module removes —
    # with a timestamp on it. Proceeding may read from the memo; blocking reads
    # from the server. One extra round trip, only on the rare path.
    memo_key = (str(getattr(config, "instance_url", "")), table)
    if memo_key in _COLUMN_MEMO:
        del _COLUMN_MEMO[memo_key]
        fresh = table_columns(config, auth_manager, table)
        if fresh is None:
            return None
        missing = [name for name in names if name not in fresh]
    return missing


def near_matches(name: str, columns: Sequence[str], limit: int = 3) -> List[str]:
    """Columns a typo'd name plausibly meant. Empty when nothing is close."""
    import difflib

    return difflib.get_close_matches(name, list(columns), n=limit, cutoff=0.6)


__all__ = [
    "near_matches",
    "query_field_names",
    "table_ancestry",
    "table_columns",
    "unknown_query_fields",
]
