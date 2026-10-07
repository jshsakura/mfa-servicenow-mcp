"""manage_scheduled_job — the schedule of a sysauto_script job, never its script."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.policies.write_guards import MANAGE_READ_ACTIONS
from servicenow_mcp.services.scheduled_job import parse_clock, parse_duration, utc_clock
from servicenow_mcp.tools.scheduled_job_tools import (
    ManageScheduledJobParams,
    manage_scheduled_job,
)
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

SVC = "servicenow_mcp.services.scheduled_job"
JOB = "aaaa1111bbbb2222cccc3333dddd0001"
USER = "aaaa1111bbbb2222cccc3333dddd0002"


def _f(value, display=None):
    return {"value": value, "display_value": display if display is not None else value}


class FakeTables:
    def __init__(self, *, keep=True, trigger=True):
        # The stored shape: a local time is entered as-is, run_time holds it in UTC.
        self.job = {
            "sys_id": _f(JOB),
            "name": _f("Sample Daily Load"),
            "active": _f("false"),
            "run_type": _f("daily"),
            "run_time": _f("1970-01-01 16:00:00"),
            "entered_time": _f("1970-01-01 09:00:00"),
            "time_zone": _f("America/Phoenix"),
            "run_dayofweek": _f("1", "Monday"),
            "run_period": _f("1970-01-02 00:00:00"),
            "conditional": _f("false"),
            "script": _f("gs.info('x');"),
            "sys_scope": _f("aaaa1111bbbb2222cccc3333dddd0009", "My App"),
            "sys_updated_on": _f("2026-08-11 13:25:32"),
        }
        self.keep = keep
        self.trigger = trigger
        self.writes = []

    def query(self, config, auth, *, table, query, fields, limit, offset, **_):
        if table == "sysauto_script":
            return [dict(self.job)], 1
        if table == "sys_trigger":
            if not self.trigger:
                return [], 0
            return [{"next_action": _f("2026-10-08 16:00:00", "2026-10-08 09:00:00")}], 1
        if table == "sys_user":
            return ([{"sys_id": _f(USER)}], 1) if "user_name=alice" in query else ([], 0)
        return [], 0

    def request(self, method, url, json=None, **_):
        self.writes.append((method, json))
        if self.keep:
            self.job.update({k: _f(str(v)) for k, v in json.items()})
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"result": json}
        return resp


@pytest.fixture
def make_env(monkeypatch):
    def build(**kw):
        invalidate_query_cache()
        fake = FakeTables(**kw)
        monkeypatch.setattr(f"{SVC}.sn_query_page", fake.query)
        auth = MagicMock(spec=AuthManager)
        auth.get_headers.return_value = {}
        auth.make_request.side_effect = fake.request
        config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
        )

        def run(**params):
            return manage_scheduled_job(config, auth, ManageScheduledJobParams(**params))

        return fake, run

    return build


class TestConversions:
    def test_local_time_becomes_the_stored_utc_value(self):
        assert utc_clock(timedelta(hours=9), "America/Phoenix") == "1970-01-01 16:00:00"

    def test_wraps_past_midnight(self):
        assert utc_clock(timedelta(hours=20), "America/Phoenix") == "1970-01-01 03:00:00"

    def test_dst_zone_uses_the_offset_on_the_given_day(self):
        summer = datetime(2026, 7, 1, tzinfo=timezone.utc)
        assert utc_clock(timedelta(hours=9), "America/New_York", summer) == "1970-01-01 13:00:00"

    def test_unknown_zone_raises(self):
        with pytest.raises(ValueError):
            utc_clock(timedelta(hours=1), "Mars/Base")

    @pytest.mark.parametrize(
        "text,raw",
        [
            ("01:00", "1970-01-01 01:00:00"),
            ("00:15:30", "1970-01-01 00:15:30"),
            ("1d 00:00:00", "1970-01-02 00:00:00"),
            ("2 06:00", "1970-01-03 06:00:00"),
        ],
    )
    def test_durations_are_epoch_offsets(self, text, raw):
        assert parse_duration(text) == raw

    @pytest.mark.parametrize("text", ["25:00", "9", "12:60", "abc"])
    def test_bad_clock_is_rejected(self, text):
        assert parse_clock(text) is None


class TestGet:
    def test_get_reports_local_time_and_the_schedulers_next_run(self, make_env):
        _, run = make_env()
        out = run(action="get", sys_id=JOB)

        job = out["job"]
        assert job["time"] == "09:00:00" and job["run_time_utc"] == "16:00:00"
        assert job["run_dayofweek"] == "Monday"
        assert job["run_period"] == "1d 00:00:00"
        assert job["script_chars"] == len("gs.info('x');")
        assert "script" not in job
        assert out["next_run"]["next_action_utc"] == "2026-10-08 16:00:00"

    def test_no_trigger_is_reported_as_not_scheduled(self, make_env):
        _, run = make_env(trigger=False)
        out = run(action="get", sys_id=JOB)
        assert out["next_run"]["checked"] is True
        assert out["next_run"]["scheduled"] is False

    def test_read_actions_need_no_confirm(self):
        assert MANAGE_READ_ACTIONS["manage_scheduled_job"] == {"list", "get"}


class TestUpdate:
    def test_time_writes_both_the_entered_and_the_utc_value(self, make_env):
        fake, run = make_env()
        out = run(action="update", sys_id=JOB, run_time="10:00", active=True)

        assert out["success"] is True
        _, body = fake.writes[-1]
        assert body["entered_time"] == "1970-01-01 10:00:00"
        assert body["run_time"] == "1970-01-01 17:00:00"
        assert body["active"] == "true"
        assert out["after"]["time"] == "10:00:00"

    def test_changing_only_the_zone_recomputes_utc_from_the_entered_time(self, make_env):
        fake, run = make_env()
        run(action="update", sys_id=JOB, time_zone="UTC")
        _, body = fake.writes[-1]
        assert body["time_zone"] == "UTC"
        assert body["run_time"] == "1970-01-01 09:00:00"

    def test_floating_zone_refuses_a_time_it_cannot_convert(self, make_env):
        fake, run = make_env()
        fake.job["time_zone"] = _f("floating")
        out = run(action="update", sys_id=JOB, run_time="09:00")
        assert out["error"] == "time_zone_required"
        assert fake.writes == []

    def test_a_field_the_server_did_not_keep_is_not_applied(self, make_env):
        fake, run = make_env(keep=False)
        out = run(action="update", sys_id=JOB, active=True)
        assert out["success"] is False
        assert out["error"] == "not_applied"
        assert out["not_applied"]["active"] == {"sent": "true", "server": "false"}

    def test_run_as_resolves_a_user_name(self, make_env):
        fake, run = make_env()
        run(action="update", sys_id=JOB, run_as="alice")
        assert fake.writes[-1][1]["run_as"] == USER

    def test_unknown_run_as_is_refused(self, make_env):
        fake, run = make_env()
        out = run(action="update", sys_id=JOB, run_as="nobody")
        assert out["error"] == "unknown_user"
        assert fake.writes == []

    def test_pinned_version_blocks_a_moved_job(self, make_env):
        fake, run = make_env()
        out = run(
            action="update", sys_id=JOB, active=True, expected_updated_on="2026-01-01 00:00:00"
        )
        assert out["error"] == "record_changed"
        assert fake.writes == []

    def test_script_is_not_a_parameter(self):
        assert "script" not in ManageScheduledJobParams.model_fields

    def test_update_needs_a_field(self):
        with pytest.raises(ValueError):
            ManageScheduledJobParams(action="update", sys_id=JOB)
