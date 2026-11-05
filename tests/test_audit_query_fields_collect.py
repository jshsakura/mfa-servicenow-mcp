"""collect_source(): positional table/field pairs and f-string query prefixes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import audit_query_fields as audit  # noqa: E402


def test_positional_pair_collected_as_select():
    src = 'x = _page(config, auth, "my_tbl", q, "sys_id,alpha,beta", 200)\n'
    got = audit.collect_source(src)
    assert got["my_tbl"]["fields"] == {"sys_id", "alpha", "beta"}


def test_constant_field_list_and_list_query():
    src = (
        'FIELDS = "sys_id,alpha,inactive"\n'
        "def f():\n"
        '    return _read_all(c, a, "my_tbl", [f"questionIN{ids}", "active=true"], FIELDS, t)\n'
    )
    got = audit.collect_source(src)
    assert got["my_tbl"]["fields"] == {"sys_id", "alpha", "inactive"}
    assert got["my_tbl"]["query"] == {"question", "active"}


def test_fstring_prefix_and_concat_query_fields():
    src = (
        'a = _page(c, a, "my_tbl", f"parentIN{ids}^ORDERBYorder", "sys_id,order")\n'
        'b = _page(c, a, "my_tbl", "request_item=" + x, "sys_id,value")\n'
    )
    got = audit.collect_source(src)
    assert got["my_tbl"]["query"] == {"parent", "order", "request_item"}


def test_lone_string_arg_is_not_a_table():
    src = 'log("some_word", 3)\nother(a, "x_y")\n'
    assert dict(audit.collect_source(src)) == {}


def test_known_table_without_field_list_takes_query_only():
    src = 'g(c, a, "my_tbl", "stateIN1,2^active=true")\n'
    assert dict(audit.collect_source(src)) == {}
    got = audit.collect_source(src, known={"my_tbl"})
    assert got["my_tbl"]["query"] >= {"active"}


def test_keyword_path_unchanged():
    src = 'f(table="my_tbl", query="active=true", fields="a,b")\n'
    got = audit.collect_source(src)
    assert got["my_tbl"] == {"query": {"active"}, "fields": {"a", "b"}}
