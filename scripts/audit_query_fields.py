#!/usr/bin/env python3
"""Check every encoded-query field name in the source against a live schema.

Why this exists
---------------
ServiceNow does not reject an unknown field in an encoded query. It DROPS the
condition. So this:

    query=f"master_flow={flow_id}^ORsys_id={flow_id}"     # no such column

degenerates to "everything OR that one row" and the read comes back with the
WHOLE TABLE — measured on a live instance, 808 rows for a query meant to match
one. The caller then picked the first row and reported an unrelated flow's
structure as the answer. Nothing errored, nothing logged, and every mocked test
passed, because a mock returns whatever the fixture says.

A wrong field name is therefore invisible to unit tests by construction, and its
failure direction is the worst one available: not "no rows" but "all rows", laundered
into a confident answer. This script is the only thing that can see it, because
only a real instance knows which columns exist.

Usage
-----
    python scripts/audit_query_fields.py            # audit every table found
    python scripts/audit_query_fields.py sys_script # audit one table

Reads credentials the same way the MCP server does (.mcp.json env block, or the
ambient SERVICENOW_* environment). Read-only: one GET per table.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional, Set

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "servicenow_mcp"
sys.path.insert(0, str(REPO / "src"))

# Encoded-query operators, longest first so LIKE is not read as a bare field.
_OPERATORS = (
    "STARTSWITH",
    "ENDSWITH",
    "NOTLIKE",
    "LIKE",
    "ANYTHING",
    "ISEMPTY",
    "ISNOTEMPTY",
    "INSTANCEOF",
    "NOT IN",
    "IN",
    ">=",
    "<=",
    "!=",
    "=",
    ">",
    "<",
)
_ORDER_PREFIXES = ("ORDERBYDESC", "ORDERBY")

# Query terms that are not field comparisons.
_NON_FIELD_TERMS = {"EQ", "NQ", "OR", "^", ""}

# Field names that are meta rather than columns.
_PSEUDO_FIELDS = {"sys_created_on", "sys_updated_on"}  # real, but listed for clarity
_PSEUDO_FIELDS.clear()


def _module_constants(tree: ast.AST) -> Dict[str, str]:
    """Module-level NAME = "literal" pairs, so TABLE constants resolve."""
    out: Dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        out[target.id] = node.value.value
    return out


def _static_text(node: ast.AST) -> Optional[str]:
    """The literal text of a str or f-string, with interpolations blanked out.

    An f-string's static parts are exactly the parts we can check: field names
    are written in the source, values are not.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("\x00")  # an interpolated value; never a field name
        return "".join(parts)
    return None


def _resolve_table(node: ast.AST, consts: Dict[str, str]) -> Optional[str]:
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return _static_text(node)


def _fields_in_query(query: str) -> Set[str]:
    """Field names a query filters or orders on."""
    found: Set[str] = set()
    for raw_term in re.split(r"\^(?:OR|NQ)?", query):
        term = raw_term.strip()
        if not term or term in _NON_FIELD_TERMS or "\x00" in term[:1]:
            continue
        for prefix in _ORDER_PREFIXES:
            if term.upper().startswith(prefix):
                candidate = term[len(prefix) :].strip()
                if candidate and "\x00" not in candidate:
                    found.add(candidate)
                term = ""
                break
        if not term:
            continue
        for op in _OPERATORS:
            idx = term.find(op)
            if idx > 0:
                name = term[:idx].strip()
                if name and "\x00" not in name:
                    found.add(name)
                break
    return found


# Both URL shapes the package builds: the full path, and `{config.api_url}/table/x`
# where api_url already ends in /api/now. Matching only the first form made
# this audit silently skip every knowledge-base write — a gap in the checker
# reads exactly like a clean checker.
_TABLE_URL = re.compile(r"(?:/api/now)?/table/([a-z0-9_]+|\x00)")


def _dict_keys(node: ast.AST) -> Set[str]:
    """Literal string keys of a dict expression. Computed keys contribute none —
    they cannot be checked statically, and guessing would make this audit lie in
    the reassuring direction."""
    keys: Set[str] = set()
    if isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
    return keys


def _body_fields(func: ast.AST, name: str) -> Set[str]:
    """Every literal key put into the local called *name* within *func*.

    Covers both shapes the package uses: ``body = {"a": 1}`` and the
    conditional ``body["b"] = value`` that follows it.
    """
    fields: Set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    fields |= _dict_keys(node.value)
                elif (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == name
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                ):
                    fields.add(target.slice.value)
    return fields


def _url_table(func: ast.AST, node: ast.AST) -> Optional[str]:
    """The table a request URL addresses, following one level of local variable.

    Deliberately narrow. A URL assembled at runtime, or one whose table segment
    is interpolated, yields None: attributing a write to a table it may not
    touch would invent findings, and this script's whole value is that its
    findings are real.
    """

    def _from_text(text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        found = [m for m in _TABLE_URL.findall(text) if m != "\x00"]
        return found[0] if len(found) == 1 else None

    if isinstance(node, (ast.Constant, ast.JoinedStr)):
        return _from_text(_static_text(node))
    if isinstance(node, ast.Name):
        for stmt in ast.walk(func):
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == node.id for t in stmt.targets
            ):
                table = _from_text(_static_text(stmt.value))
                if table:
                    return table
    return None


def collect_writes() -> Dict[str, Dict[str, Set[str]]]:
    """{table: {"fields": {written}, "where": {"module.func"}}}.

    Paired precisely: the fields are those of the dict handed to THIS
    ``make_request(... json=...)``, and the table is the one in THIS call's URL.
    Scanning a whole function instead would sweep up response dicts
    (``{"success": ..., "message": ...}``), header dicts and the Batch API
    envelope — and an audit that reports forty things that are fine is one
    nobody reads.
    """
    per_table: Dict[str, Dict[str, Set[str]]] = defaultdict(
        lambda: {"fields": set(), "where": set()}
    )
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(func):
                if not isinstance(call, ast.Call):
                    continue
                target = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
                if target != "make_request" or not call.args:
                    continue
                method = call.args[0]
                if not (
                    isinstance(method, ast.Constant) and method.value in ("POST", "PATCH", "PUT")
                ):
                    continue
                kw = {k.arg: k.value for k in call.keywords if k.arg}
                url_node = kw.get("url") or (call.args[1] if len(call.args) > 1 else None)
                body_node = kw.get("json")
                if url_node is None or body_node is None:
                    continue
                table = _url_table(func, url_node)
                if not table:
                    continue
                if isinstance(body_node, ast.Dict):
                    fields = _dict_keys(body_node)
                elif isinstance(body_node, ast.Name):
                    fields = _body_fields(func, body_node.id)
                else:
                    continue
                if not fields:
                    continue
                per_table[table]["fields"] |= fields
                per_table[table]["where"].add(f"{path.stem}.{func.name}")
    return per_table


def collect_field_maps() -> Dict[str, Dict[str, Set[str]]]:
    """{table: {"query": {fields}, "fields": {fields}}} from config-style registries.

    ``collect()`` only sees field names written literally at a call site. The
    ones that actually broke were not written there: ``SOURCE_CONFIG`` in
    source_tools.py maps a source type to a table plus ``search_fields`` /
    ``lookup_fields`` (which become an encoded query) and ``summary_fields`` /
    ``source_fields`` (which become ``sysparm_fields``), and the query is
    assembled from them at runtime. So a name that no column matches —
    ``sys_transform_script.name``, ``sp_angular_provider.client_script``,
    ``sp_page.description`` — was invisible to this audit while being sent to
    the server on every search. Any module-level dict whose values carry a
    ``table`` key and ``*_fields`` lists is read here, so a new registry of the
    same shape is covered without being named.
    """
    query_keys = ("search_fields", "lookup_fields", "filter_fields")
    select_keys = ("summary_fields", "source_fields", "folder_fields", "detail_fields")
    per_table: Dict[str, Dict[str, Set[str]]] = defaultdict(
        lambda: {"query": set(), "fields": set()}
    )
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            value = (
                node.value
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
                else None
            )
            if not isinstance(value, ast.Dict):
                continue
            try:
                mapping = ast.literal_eval(value)
            except (ValueError, TypeError, SyntaxError):
                continue
            if not isinstance(mapping, dict):
                continue
            for entry in mapping.values():
                if not isinstance(entry, dict):
                    continue
                table = entry.get("table")
                if not isinstance(table, str) or not re.fullmatch(r"[a-z0-9_]+", table):
                    continue
                for key in query_keys:
                    per_table[table]["query"] |= {
                        f for f in entry.get(key, []) or [] if isinstance(f, str)
                    }
                for key in select_keys:
                    per_table[table]["fields"] |= {
                        f for f in entry.get(key, []) or [] if isinstance(f, str)
                    }
                # `identifier_field` is deliberately NOT collected: it is a
                # display key read off a record that was fetched by other
                # names, and one entry relies on it being absent so the folder
                # composer falls through to `folder_fields`.
    return per_table


def collect() -> Dict[str, Dict[str, Set[str]]]:
    """{table: {"query": {fields}, "fields": {fields}}} across the package."""
    per_table: Dict[str, Dict[str, Set[str]]] = defaultdict(
        lambda: {"query": set(), "fields": set()}
    )
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        consts = _module_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            if "table" not in kw:
                continue
            table = _resolve_table(kw["table"], consts)
            if not table or not re.fullmatch(r"[a-z0-9_]+", table):
                continue
            query_text = _static_text(kw["query"]) if "query" in kw else None
            if query_text:
                per_table[table]["query"] |= _fields_in_query(query_text)
            fields_text = _static_text(kw["fields"]) if "fields" in kw else None
            if fields_text and "\x00" not in fields_text:
                per_table[table]["fields"] |= {
                    f.strip() for f in fields_text.split(",") if f.strip()
                }
    return per_table


# ---------------------------------------------------------------------------
# Live schema
# ---------------------------------------------------------------------------


def _load_env() -> None:
    """Adopt the MCP server's env so the audit reads the same instance.

    The server key is whatever the user named it — pinning it to one spelling
    made this script die on a KeyError, i.e. the field audit silently did not
    run at all. Take any entry that carries SERVICENOW_INSTANCE_URL, and say so
    when none does rather than proceed against an unset instance.
    """
    mcp = REPO / ".mcp.json"
    if not mcp.exists() or os.environ.get("SERVICENOW_INSTANCE_URL"):
        return
    servers = json.loads(mcp.read_text()).get("mcpServers") or {}
    for name, entry in servers.items():
        env = (entry or {}).get("env") or {}
        if env.get("SERVICENOW_INSTANCE_URL"):
            print(f"Using instance env from .mcp.json server {name!r}")
            os.environ.update({k: str(v) for k, v in env.items()})
            return
    print(
        "No .mcp.json server carries SERVICENOW_INSTANCE_URL — "
        "set it in the environment, or the audit cannot reach a live schema."
    )


def _client():
    from servicenow_mcp.auth.auth_manager import AuthManager
    from servicenow_mcp.utils.config import (
        AuthConfig,
        AuthType,
        BasicAuthConfig,
        BrowserAuthConfig,
        ServerConfig,
    )

    url = os.environ["SERVICENOW_INSTANCE_URL"]
    if (os.environ.get("SERVICENOW_AUTH_TYPE") or "browser").lower() == "basic":
        auth_cfg = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(
                username=os.environ["SERVICENOW_USERNAME"],
                password=os.environ["SERVICENOW_PASSWORD"],
            ),
        )
    else:
        auth_cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(username=os.environ.get("SERVICENOW_USERNAME", "")),
        )
    config = ServerConfig(instance_url=url, auth=auth_cfg)
    return config, AuthManager(config.auth, config.instance_url)


def live_columns(config, auth, table: str) -> Optional[Set[str]]:
    """Every column of *table* INCLUDING inherited ones, or None if unreadable.

    Inheritance is the whole difficulty. `sys_dictionary` rows named for a table
    list only the columns that table declares; `rm_epic` declares almost nothing
    and inherits `short_description`, `state`, `priority` and the rest from
    `task`. Checking one level would flag every inherited field as unknown — and
    a check that is wrong every time is one people switch off, which is exactly
    how the bug this script hunts for survived in the first place.

    So: union the dictionary across the whole super_class chain, and add the
    keys of one sampled row (which carries the real, resolved column set) when
    the table has any rows at all.
    """
    from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page

    def _page(**kw):
        invalidate_query_cache()
        kw.setdefault("offset", 0)
        kw.setdefault("display_value", False)
        kw.setdefault("fail_silently", False)
        return sn_query_page(config, auth, **kw)

    cols: Set[str] = set()

    try:
        rows, _ = _page(table=table, query="", fields="", limit=1)
    except Exception as exc:  # noqa: BLE001 - reported as "could not read"
        print(f"    ! {table}: {str(exc)[:100]}")
        return None
    if rows:
        cols |= set(rows[0].keys())

    # Walk up the inheritance chain, unioning declared columns at each level.
    current: Optional[str] = table
    seen: Set[str] = set()
    while current and current not in seen:
        seen.add(current)
        try:
            dict_rows, _ = _page(
                table="sys_dictionary", query=f"name={current}", fields="element", limit=1000
            )
            cols |= {r["element"] for r in dict_rows if r.get("element")}
            parent_rows, _ = _page(
                table="sys_db_object", query=f"name={current}", fields="super_class", limit=1
            )
        except Exception:  # noqa: BLE001 - partial chain is still worth reporting
            break
        if not parent_rows:
            break
        parent_id = parent_rows[0].get("super_class") or ""
        if not parent_id:
            break
        try:
            parent_name, _ = _page(
                table="sys_db_object", query=f"sys_id={parent_id}", fields="name", limit=1
            )
        except Exception:  # noqa: BLE001
            break
        current = parent_name[0].get("name") if parent_name else None

    return cols or None


RECORDED = REPO / "tests" / "fixtures" / "live_schema.json"
# Instance-specific columns: never recorded, never checked.
CUSTOMISATION = re.compile(r"^(u_|x_)")


def record(config, auth, tables) -> None:
    """Freeze the measured column sets so CI can run this check without a server.

    A recorded schema is the only way the rest of the suite can tell a real
    column from an invented one. It is a SNAPSHOT, not the truth: it says what
    one instance had on one day, which is why the test that consumes it only
    ever rejects names that are absent everywhere, and why refreshing it is a
    deliberate act with a diff to read.
    """
    snapshot = {}
    for table in sorted(tables):
        cols, sampled = live_columns_with_provenance(config, auth, table)
        if cols and sampled:
            # Customisation columns are STRIPPED. `u_*` and `x_*` are the
            # customer's own schema — a live sys_user here carries their HR
            # model (cost centre, line manager, employee number), and this file
            # goes into a public repository. They are also unverifiable from a
            # snapshot: another instance simply will not have them. The checker
            # skips the same prefixes, so the two sides agree.
            snapshot[table] = sorted(c for c in cols if not CUSTOMISATION.match(c))
    RECORDED.parent.mkdir(parents=True, exist_ok=True)
    RECORDED.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    print(f"recorded {len(snapshot)} tables -> {RECORDED.relative_to(REPO)}")


def main() -> int:
    argv = [a for a in sys.argv[1:] if a != "--record"]
    if "--record" in sys.argv[1:]:
        _load_env()
        config, auth = _client()
        tables = set(collect()) | set(collect_writes()) | set(collect_field_maps())
        record(config, auth, set(argv) or tables)
        return 0
    wanted = set(argv)
    per_table = collect()
    # A registry-declared search field is ORed with the others into one query.
    # Measured here: when the dropped term came FIRST the surviving real term
    # did not save the read — `nameLIKEx^ORscriptLIKEx` on sys_transform_script
    # answered every query with the same rows. So these are merged in and, below,
    # judged without the "something else still filters" allowance.
    config_tables = collect_field_maps()
    strict_query_fields = {t: set(v["query"]) for t, v in config_tables.items()}
    for table, used in config_tables.items():
        per_table[table]["query"] |= used["query"]
        per_table[table]["fields"] |= used["fields"]
    if wanted:
        per_table = {t: v for t, v in per_table.items() if t in wanted}

    print(f"Found {len(per_table)} tables referenced with literal field names.\n")
    _load_env()
    config, auth = _client()

    writes = collect_writes()
    if wanted:
        writes = {t: v for t, v in writes.items() if t in wanted}

    filter_defects: list[tuple[str, str]] = []
    select_defects: list[tuple[str, str]] = []
    write_defects: list[tuple[str, str, str]] = []
    unreadable: list[str] = []
    unresolved: list[str] = []

    # Writes first: a PATCH naming a column the table does not have is accepted,
    # ignored, and answered 200. `raise_for_status` passes and the tool reports
    # the change it did not make — strictly worse than a bad read, which at least
    # returns something a human might notice is wrong.
    for table in sorted(writes):
        cols, sampled = live_columns_with_provenance(config, auth, table)
        if cols is None:
            unreadable.append(table)
            continue
        if not sampled:
            unresolved.append(table)
            continue
        for field in sorted(writes[table]["fields"]):
            if "." in field or field in cols:
                continue
            write_defects.append((table, field, ", ".join(sorted(writes[table]["where"]))))

    for table in sorted(per_table):
        used = per_table[table]
        # Dot-walked references are resolved by the server against another table.
        asked = {f for f in (used["query"] | used["fields"]) if f and "." not in f}
        if not asked:
            continue
        cols, sampled = live_columns_with_provenance(config, auth, table)
        if cols is None:
            unreadable.append(table)
            continue
        # A dropped condition is only dangerous when nothing is left to filter
        # on. Measured against a live instance:
        #     parent_flow=F                 ->  21 rows
        #     master_flow=F  (no such col)  -> 808 rows  (nothing filters)
        #     parent_flow=F^ORmaster_flow=F ->  21 rows  (the bad term vanishes)
        # So a query that also names a real column still filters correctly, and
        # spelling a field two ways on purpose — to survive a rename between
        # releases — is a legitimate pattern, not a defect. Flagging it would
        # make this script wrong exactly where the code is being careful.
        #
        # POSITION DECIDES IT, though, and this check cannot see position.
        # Measured on sys_transform_script (67 rows), same two terms:
        #     scriptLIKEzz               ->  0    real column, no match
        #     nameLIKEzz                 -> 67    no such column: everything
        #     nameLIKEzz^ORscriptLIKEzz  -> 67    bogus FIRST: nothing filters
        #     scriptLIKEzz^ORnameLIKEzz  ->  0    bogus second: filter holds
        # The allowance therefore holds only for a bad term that is not first.
        # Registry-declared chains (`strict_query_fields`) set their own order
        # and had the bad name at index 0, so they are judged without it.
        query_fields = used["query"]
        has_a_real_filter = any(f in cols for f in query_fields if "." not in f)

        for field in sorted(asked):
            if field in cols:
                continue
            if field in query_fields and (
                not has_a_real_filter or field in strict_query_fields.get(table, set())
            ):
                # Nothing else constrains the read: the condition is dropped and
                # the whole table comes back, dressed as an answer.
                filter_defects.append((table, field))
            elif sampled:
                # Only claimed when a real row resolved the column set. Without
                # one, an unlisted field is indistinguishable from a plugin that
                # is not installed here, and guessing would make this noisy —
                # which is how a check stops being run.
                select_defects.append((table, field))
        if not sampled and any(f not in cols for f in asked):
            unresolved.append(table)

    if write_defects:
        print("WRITES a field the table does not have — accepted, ignored, reported as done:\n")
        for table, field, where in write_defects:
            print(f"  {table:<30} {field:<24} ({where})")
        print()
    else:
        print("No write payload names a field its table does not have.\n")

    if filter_defects:
        print("FILTERS on a field the table does not have — returns the WHOLE TABLE:\n")
        for table, field in filter_defects:
            print(f"  {table:<34} {field}")
        print()
    else:
        print("No query FILTERS on an unknown field in any readable table.\n")

    if select_defects:
        print("Selects a field the table does not have (server omits it; cosmetic):\n")
        for table, field in select_defects:
            print(f"  {table:<34} {field}")
        print()

    print("-" * 72)
    if unreadable:
        print(f"NOT CLEARED — schema unreadable (ACL / not installed): {', '.join(unreadable)}")
    if unresolved:
        print(
            "NOT CLEARED — no sample row, so selected-field checks are inconclusive: "
            f"{', '.join(sorted(set(unresolved)))}"
        )
    if write_defects:
        print(
            f"\n{len(write_defects)} write-class defect(s). These report success and change nothing."
        )
    if filter_defects:
        print(f"{len(filter_defects)} filter-class defect(s). This is the one that lies.")
    if write_defects or filter_defects:
        return 1
    return 1 if unreadable else 0


def live_columns_with_provenance(config, auth, table: str):
    """(columns, sampled_a_real_row). Provenance decides what may be claimed."""
    from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page

    invalidate_query_cache()
    sampled = False
    try:
        rows, _ = sn_query_page(
            config,
            auth,
            table=table,
            query="",
            fields="",
            limit=1,
            offset=0,
            display_value=False,
            fail_silently=False,
        )
        sampled = bool(rows)
    except Exception:  # noqa: BLE001 - live_columns reports the reason
        pass
    return live_columns(config, auth, table), sampled


if __name__ == "__main__":
    raise SystemExit(main())
