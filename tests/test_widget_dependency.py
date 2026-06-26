"""Tests for manage_widget_dependency — unified CRUD + link/unlink for
Service Portal widget Angular providers and CSS/JS dependencies.

Live write tool: every path must return a meaningful dict (success message or
error+hint) so the LLM never flails. These tests exercise real routing/logic —
not just mock pass-through.
"""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.widget_dependency_tools import (
    ManageWidgetDependencyParams,
    _build_record_fields,
    _ref_value,
    manage_widget_dependency,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

DEV = "servicenow_mcp.tools.portal_dev_tools"
PORTAL = "servicenow_mcp.tools.portal_tools"


@pytest.fixture(autouse=True)
def _stub_provider_m2m_resolver():
    """link/unlink/list resolve the provider junction table against the live
    instance; stub it to a fixed name so discovery round-trips don't perturb the
    _sn_get mock sequences here. Resolver logic: tests/test_provider_m2m_resolver.py."""
    import servicenow_mcp.tools.portal_dev_tools as _pdt

    _pdt._ANGULAR_PROVIDER_M2M_RESOLVED.clear()
    with patch.object(_pdt, "resolve_angular_provider_m2m", return_value="m2m_sp_ng_pro_sp_widget"):
        yield
    _pdt._ANGULAR_PROVIDER_M2M_RESOLVED.clear()


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


def _resp(json_body, status=200):
    r = MagicMock()
    r.status_code = status
    r.content = b"{}"
    r.json.return_value = json_body
    r.raise_for_status.return_value = None
    return r


def _p(**kw):
    return ManageWidgetDependencyParams(**kw)


# ---------------------------------------------------------------------------
# Pure helpers — exercised directly (not via mocks)
# ---------------------------------------------------------------------------


class TestRetirement:
    def test_retired_resolvers_gone_new_tool_present(self):
        from importlib.resources import files

        import yaml

        raw = files("servicenow_mcp.config").joinpath("tool_packages.yaml").read_text()
        cfg_text = str(yaml.safe_load(raw))
        for old in (
            "get_provider_dependency_map",
            "resolve_widget_chain",
            "resolve_page_dependencies",
        ):
            assert old not in cfg_text, f"{old} must be de-registered from packages"
        assert "manage_widget_dependency" in cfg_text


class TestRefValue:
    def test_plain_string(self):
        assert _ref_value("abc") == "abc"

    def test_dict_prefers_value_over_display(self):
        assert _ref_value({"value": "SYS123", "display_value": "Pretty Name"}) == "SYS123"

    def test_empty_value_does_not_leak_display_name(self):
        # The bug guard: blank sys_id must NOT fall through to the display name.
        assert _ref_value({"value": "", "display_value": "Pretty Name"}) == ""

    def test_dict_without_value_key_uses_display(self):
        assert _ref_value({"display_value": "X"}) == "X"

    def test_none(self):
        assert _ref_value(None) == ""


class TestBuildRecordFields:
    def test_name_only(self):
        assert _build_record_fields(_p(action="create", target="provider", name="P")) == {
            "name": "P"
        }

    def test_module_dependency_only(self):
        f = _build_record_fields(_p(action="create", target="dependency", name="d", module="m"))
        assert f == {"name": "d", "module": "m"}

    def test_module_dropped_for_provider(self):
        f = _build_record_fields(_p(action="create", target="provider", name="p", module="m"))
        assert "module" not in f

    def test_fields_override_named_params(self):
        # `fields` is the raw escape hatch and must win over name/module.
        f = _build_record_fields(
            _p(
                action="update",
                target="dependency",
                record_id="D1",
                name="a",
                fields={"name": "b", "x": 1},
            )
        )
        assert f == {"name": "b", "x": 1}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    @pytest.mark.parametrize(
        "kw",
        [
            dict(action="list", target="provider"),
            dict(action="get", target="provider"),
            dict(action="create", target="provider"),
            dict(action="update", target="provider", record_id="x"),
            dict(action="delete", target="provider"),
            dict(action="link", target="provider", widget_id="w"),
            dict(action="unlink", target="provider", record_id="r"),
            dict(action="link", target="page", widget_id="w", record_id="r"),
            dict(action="bogus", target="provider"),
            dict(action="list", target="bogus", widget_ids=["w"]),
        ],
    )
    def test_invalid_rejected(self, kw):
        with pytest.raises(ValueError):
            _p(**kw)

    @pytest.mark.parametrize(
        "kw",
        [
            dict(action="list", target="provider", widget_ids=["w"]),
            dict(action="list", target="page", page_id="index"),
            dict(action="get", target="provider", record_id="p1"),
            dict(action="get", target="dependency", widget_id="w1"),
            dict(action="create", target="dependency", name="d", module="m"),
            dict(action="update", target="provider", record_id="p1", name="n"),
            dict(action="delete", target="dependency", record_id="d1"),
            dict(action="link", target="provider", widget_id="w", record_id="p1"),
            dict(action="unlink", target="dependency", widget_id="w", record_id="d1"),
        ],
    )
    def test_valid_accepted(self, kw):
        assert _p(**kw).action == kw["action"]


# ---------------------------------------------------------------------------
# Read routing — the C1/C2 correctness bugs
# ---------------------------------------------------------------------------


class TestReadRouting:
    def test_get_by_record_id_fetches_the_record(self):
        # C1: get + record_id (no widget_id) must do a direct sys_id lookup,
        # NOT fall through to a "missing filter" error.
        with (
            patch(
                f"{DEV}._sn_get",
                return_value=([{"sys_id": "P1", "name": "Prov", "extra": ""}], None),
            ) as g,
            patch(f"{DEV}.get_provider_dependency_map") as gpm,
        ):
            out = manage_widget_dependency(
                _config(), MagicMock(), _p(action="get", target="provider", record_id="P1")
            )
        assert out["success"] is True
        assert out["record"]["sys_id"] == "P1"
        assert "extra" not in out["record"]  # _compact_record stripped empty field
        assert "sys_id=P1" in g.call_args.args[3]  # queried by sys_id
        gpm.assert_not_called()  # did NOT route to the metadata graph

    def test_get_record_not_found_has_hint(self):
        with patch(f"{DEV}._sn_get", return_value=([], None)):
            out = manage_widget_dependency(
                _config(), MagicMock(), _p(action="get", target="dependency", record_id="missing")
            )
        assert out["success"] is False
        assert "hint" in out

    def test_get_dependency_by_widget_lists_deps_not_source(self):
        # C2: get(target=dependency, widget_id) must return the CSS/JS dep list,
        # NOT delegate to the source-chain resolver.
        side = [
            ([{"sys_id": "W1", "name": "Widget A"}], None),  # widget filter
            ([{"sys_id": "M1", "sp_widget": "W1", "sp_dependency": "D1"}], None),  # m2m
            ([{"sys_id": "D1", "name": "Common CSS", "module": "modA"}], None),  # detail
        ]
        with (
            patch(f"{DEV}._sn_get", side_effect=side),
            patch(f"{PORTAL}.resolve_widget_chain") as chain,
        ):
            out = manage_widget_dependency(
                _config(), MagicMock(), _p(action="get", target="dependency", widget_id="W1")
            )
        assert "dependency_map" in out
        assert out["dependency_map"][0]["dependencies"][0]["name"] == "Common CSS"
        chain.assert_not_called()  # source chain must NOT be hit

    def test_dependency_fetch_failure_points_to_offline_graph(self):
        # P2 no-dead-end: when the live widget fetch fails (instance unreachable),
        # the error must hand back the OFFLINE alternative, not a flat dead-end.
        with patch(f"{DEV}._sn_get", side_effect=Exception("connection refused")):
            out = manage_widget_dependency(
                _config(), MagicMock(), _p(action="get", target="dependency", widget_id="W1")
            )
        assert out["success"] is False
        assert out["offline_alternative"] == "query_local_graph"
        assert "query_local_graph" in out["hint"]

    def test_include_source_is_only_source_trigger(self):
        sentinel = {"success": True, "_via": "chain"}
        with patch(f"{PORTAL}.resolve_widget_chain", return_value=sentinel) as chain:
            out = manage_widget_dependency(
                _config(),
                MagicMock(),
                _p(action="get", target="provider", widget_id="w1", include_source=True),
            )
        assert out is sentinel
        assert chain.call_args.args[2].widget_id == "w1"
        assert chain.call_args.args[2].depth == 2

    def test_list_provider_translates_all_params(self):
        # M4: verify FULL param translation, not just pass-through.
        sentinel = {"success": True}
        with patch(f"{DEV}.get_provider_dependency_map", return_value=sentinel) as gpm:
            manage_widget_dependency(
                _config(),
                MagicMock(),
                _p(
                    action="list",
                    target="provider",
                    widget_ids=["w1"],
                    scope="x_app",
                    developer="dev@x",
                    include_si_refs=False,
                    max_widgets=5,
                ),
            )
        inner = gpm.call_args.args[2]
        assert inner.widget_ids == ["w1"]
        assert inner.scope == "x_app"
        assert inner.developer == "dev@x"
        assert inner.include_script_include_refs is False  # renamed field
        assert inner.max_widgets == 5

    def test_list_page_translates_save_to_disk_and_depth(self):
        sentinel = {"success": True}
        with patch(f"{PORTAL}.resolve_page_dependencies", return_value=sentinel) as page:
            manage_widget_dependency(
                _config(),
                MagicMock(),
                _p(action="list", target="page", page_id="index", depth=3, save_to_disk=True),
            )
        inner = page.call_args.args[2]
        assert inner.page_id == "index"
        assert inner.depth == 3
        assert inner.save_to_disk is True


# ---------------------------------------------------------------------------
# _list_dependencies — chunking, dict refs, errors
# ---------------------------------------------------------------------------


class TestListDependencies:
    def test_dict_format_references_flattened(self):
        # Real API (display_value=True) returns {"value","display_value"} dicts.
        side = [
            ([{"sys_id": {"value": "W1", "display_value": "W1"}, "name": "A"}], None),
            (
                [
                    {
                        "sys_id": "M1",
                        "sp_widget": {"value": "W1", "display_value": "A"},
                        "sp_dependency": {"value": "D1", "display_value": "CSS"},
                    }
                ],
                None,
            ),
            ([{"sys_id": "D1", "name": "Common CSS", "module": "modA"}], None),
        ]
        with patch(f"{DEV}._sn_get", side_effect=side):
            out = manage_widget_dependency(
                _config(), MagicMock(), _p(action="list", target="dependency", widget_ids=["W1"])
            )
        assert out["dependency_map"][0]["widget"]["sys_id"] == "W1"
        assert out["dependency_map"][0]["dependencies"][0]["sys_id"] == "D1"

    def test_two_widgets_two_deps(self):
        side = [
            ([{"sys_id": "W1", "name": "A"}, {"sys_id": "W2", "name": "B"}], None),
            (
                [
                    {"sys_id": "M1", "sp_widget": "W1", "sp_dependency": "D1"},
                    {"sys_id": "M2", "sp_widget": "W2", "sp_dependency": "D2"},
                ],
                None,
            ),
            (
                [
                    {"sys_id": "D1", "name": "dep1", "module": "m1"},
                    {"sys_id": "D2", "name": "dep2", "module": "m2"},
                ],
                None,
            ),
        ]
        with patch(f"{DEV}._sn_get", side_effect=side):
            out = manage_widget_dependency(
                _config(),
                MagicMock(),
                _p(action="list", target="dependency", widget_ids=["W1", "W2"]),
            )
        assert out["summary"]["dependencies"] == 2
        assert len(out["dependency_map"]) == 2

    def test_zero_dependencies(self):
        side = [([{"sys_id": "W1", "name": "A"}], None), ([], None)]
        with patch(f"{DEV}._sn_get", side_effect=side):
            out = manage_widget_dependency(
                _config(), MagicMock(), _p(action="list", target="dependency", widget_ids=["W1"])
            )
        assert out["success"] is True
        assert out["dependency_map"] == []

    def test_m2m_failure_surfaces_warning(self):
        side = [([{"sys_id": "W1", "name": "A"}], None), RuntimeError("acl denied")]
        with patch(f"{DEV}._sn_get", side_effect=side):
            out = manage_widget_dependency(
                _config(), MagicMock(), _p(action="list", target="dependency", widget_ids=["W1"])
            )
        assert out["success"] is True
        assert "warnings" in out and out["warnings"]


# ---------------------------------------------------------------------------
# Record writes: create / update / delete
# ---------------------------------------------------------------------------


class TestRecordWrites:
    def test_create_provider_posts_and_hints_link(self):
        auth = MagicMock()
        auth.make_request.return_value = _resp({"result": {"sys_id": "P1"}})
        with patch(
            "servicenow_mcp.tools.sn_api._safe_json", return_value={"result": {"sys_id": "P1"}}
        ):
            out = manage_widget_dependency(
                _config(), auth, _p(action="create", target="provider", name="MyProvider")
            )
        assert out["success"] is True and out["sys_id"] == "P1"
        assert "action=link" in out["next"]
        method, url = auth.make_request.call_args.args[:2]
        assert method == "POST" and url.endswith("/api/now/table/sp_angular_provider")
        assert auth.make_request.call_args.kwargs["json"] == {"name": "MyProvider"}

    def test_update_provider_patches_correct_url_and_body(self):
        # H1: real update happy-path coverage (was missing entirely).
        auth = MagicMock()
        auth.make_request.return_value = _resp({"result": {"sys_id": "P1"}})
        with patch(
            "servicenow_mcp.tools.sn_api._safe_json", return_value={"result": {"sys_id": "P1"}}
        ):
            out = manage_widget_dependency(
                _config(),
                auth,
                _p(action="update", target="provider", record_id="P1", name="renamed"),
            )
        assert out["success"] is True
        method, url = auth.make_request.call_args.args[:2]
        assert method == "PATCH" and url.endswith("/sp_angular_provider/P1")
        assert auth.make_request.call_args.kwargs["json"] == {"name": "renamed"}

    def test_update_dry_run_no_http(self):
        auth = MagicMock()
        out = manage_widget_dependency(
            _config(),
            auth,
            _p(action="update", target="dependency", record_id="D1", module="m", dry_run=True),
        )
        assert out["dry_run"] is True
        assert auth.make_request.call_count == 0

    def test_create_dry_run_no_http(self):
        auth = MagicMock()
        out = manage_widget_dependency(
            _config(), auth, _p(action="create", target="provider", name="x", dry_run=True)
        )
        assert out["dry_run"] is True
        assert auth.make_request.call_count == 0

    def test_delete_calls_delete(self):
        auth = MagicMock()
        auth.make_request.return_value = _resp({}, status=204)
        out = manage_widget_dependency(
            _config(), auth, _p(action="delete", target="dependency", record_id="D1")
        )
        assert out["success"] is True
        method, url = auth.make_request.call_args.args[:2]
        assert method == "DELETE" and url.endswith("/sp_dependency/D1")

    def test_write_failure_returns_hint(self):
        auth = MagicMock()
        auth.make_request.side_effect = RuntimeError("boom")
        out = manage_widget_dependency(
            _config(), auth, _p(action="update", target="provider", record_id="P1", name="n")
        )
        assert out["success"] is False and "boom" in out["error"] and "hint" in out


# ---------------------------------------------------------------------------
# Link / unlink — m2m junction, idempotent, partial failure
# ---------------------------------------------------------------------------


class TestLink:
    def test_link_creates_m2m_when_absent(self):
        auth = MagicMock()
        auth.make_request.return_value = _resp({"result": {"sys_id": "M1"}})
        with (
            patch(f"{DEV}._sn_get", side_effect=[([{"sys_id": "W1"}], None), ([], None)]),
            patch(
                "servicenow_mcp.tools.sn_api._safe_json", return_value={"result": {"sys_id": "M1"}}
            ),
        ):
            out = manage_widget_dependency(
                _config(), auth, _p(action="link", target="provider", widget_id="w", record_id="P1")
            )
        assert out["success"] is True
        assert auth.make_request.call_args.kwargs["json"] == {
            "sp_widget": "W1",
            "sp_angular_provider": "P1",
        }

    def test_link_posts_to_resolved_junction_table(self):
        # The provider link must hit the junction table resolved for the
        # instance (stubbed here to m2m_sp_ng_pro_sp_widget), not a guessed name.
        auth = MagicMock()
        auth.make_request.return_value = _resp({"result": {"sys_id": "M1"}})
        with (
            patch(f"{DEV}._sn_get", side_effect=[([{"sys_id": "W1"}], None), ([], None)]),
            patch(
                "servicenow_mcp.tools.sn_api._safe_json", return_value={"result": {"sys_id": "M1"}}
            ),
        ):
            out = manage_widget_dependency(
                _config(), auth, _p(action="link", target="provider", widget_id="w", record_id="P1")
            )
        assert out["success"] is True
        method, url = auth.make_request.call_args.args[:2]
        assert method == "POST"
        assert url.endswith("/api/now/table/m2m_sp_ng_pro_sp_widget")

    def test_link_idempotent_noop(self):
        auth = MagicMock()
        with patch(
            f"{DEV}._sn_get", side_effect=[([{"sys_id": "W1"}], None), ([{"sys_id": "EX"}], None)]
        ):
            out = manage_widget_dependency(
                _config(), auth, _p(action="link", target="provider", widget_id="w", record_id="P1")
            )
        assert out["success"] is True and out["noop"] is True
        assert auth.make_request.call_count == 0

    def test_link_dry_run_when_exists_flags_dry_run(self):
        auth = MagicMock()
        with patch(
            f"{DEV}._sn_get", side_effect=[([{"sys_id": "W1"}], None), ([{"sys_id": "EX"}], None)]
        ):
            out = manage_widget_dependency(
                _config(),
                auth,
                _p(action="link", target="provider", widget_id="w", record_id="P1", dry_run=True),
            )
        assert out["noop"] is True and out["dry_run"] is True

    def test_link_widget_not_found_has_hint(self):
        auth = MagicMock()
        with patch(f"{DEV}._sn_get", side_effect=[([], None)]):
            out = manage_widget_dependency(
                _config(),
                auth,
                _p(action="link", target="dependency", widget_id="nope", record_id="D1"),
            )
        assert out["success"] is False and "hint" in out
        assert auth.make_request.call_count == 0

    def test_unlink_deletes_matching_rows(self):
        auth = MagicMock()
        auth.make_request.return_value = _resp({}, status=204)
        with patch(
            f"{DEV}._sn_get",
            side_effect=[([{"sys_id": "W1"}], None), ([{"sys_id": "M1"}, {"sys_id": "M2"}], None)],
        ):
            out = manage_widget_dependency(
                _config(),
                auth,
                _p(action="unlink", target="provider", widget_id="w", record_id="P1"),
            )
        assert out["success"] is True and out["deleted"] == ["M1", "M2"]
        assert auth.make_request.call_count == 2

    def test_unlink_partial_failure_reports_failed(self):
        # H3: one DELETE fails -> success must be False, failed listed.
        auth = MagicMock()
        auth.make_request.side_effect = [_resp({}, status=204), RuntimeError("nope")]
        with patch(
            f"{DEV}._sn_get",
            side_effect=[([{"sys_id": "W1"}], None), ([{"sys_id": "M1"}, {"sys_id": "M2"}], None)],
        ):
            out = manage_widget_dependency(
                _config(),
                auth,
                _p(action="unlink", target="provider", widget_id="w", record_id="P1"),
            )
        assert out["success"] is False
        assert out["deleted"] == ["M1"] and out["failed"] == ["M2"]
        assert "error" in out

    def test_unlink_noop_when_no_link(self):
        auth = MagicMock()
        with patch(f"{DEV}._sn_get", side_effect=[([{"sys_id": "W1"}], None), ([], None)]):
            out = manage_widget_dependency(
                _config(),
                auth,
                _p(action="unlink", target="provider", widget_id="w", record_id="P1"),
            )
        assert out["success"] is True and out["noop"] is True
        assert auth.make_request.call_count == 0
