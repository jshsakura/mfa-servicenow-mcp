"""Environment-driven ServiceNow instance configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from servicenow_mcp.utils import json_fast

INSTANCE_CONFIG_ENV = "SERVICENOW_INSTANCE_CONFIG"
ACTIVE_INSTANCE_ENV = "SERVICENOW_ACTIVE_INSTANCE"


@dataclass(frozen=True)
class InstanceDefinition:
    alias: str
    url: str
    allow_writes: bool = False
    raw: dict[str, Any] | None = None


def coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_instance_config_env(raw: str | None) -> dict[str, dict[str, Any]]:
    """Parse SERVICENOW_INSTANCE_CONFIG JSON into alias -> config mapping."""
    if not raw or not raw.strip():
        return {}
    parsed = json_fast.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{INSTANCE_CONFIG_ENV} must be a JSON object")
    result: dict[str, dict[str, Any]] = {}
    for alias, entry in parsed.items():
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError(f"{INSTANCE_CONFIG_ENV} aliases must be non-empty strings")
        if not isinstance(entry, dict):
            raise ValueError(f"{INSTANCE_CONFIG_ENV}.{alias} must be a JSON object")
        result[alias.strip()] = dict(entry)
    return result


def build_instance_definition(alias: str, entry: dict[str, Any]) -> InstanceDefinition:
    url = str(entry.get("url") or entry.get("instance_url") or "").strip()
    if not url:
        raise ValueError(f"{INSTANCE_CONFIG_ENV}.{alias}.url is required")
    # Writes are opt-in per instance: omit allow_writes and the instance is
    # read-only. Safer default for prod/test peers where a forgotten flag
    # should never silently enable writes.
    allow_writes = coerce_bool(entry.get("allow_writes"), default=False)
    return InstanceDefinition(
        alias=alias,
        url=url,
        allow_writes=allow_writes,
        raw=dict(entry),
    )


def resolve_auth_type(entry: dict[str, Any] | None, default_auth_type: str) -> str:
    """Resolve an instance's auth type, honoring an explicit opt-out of browser.

    Browser is the global default (headless), and instances that specify nothing
    keep it. But an instance that brings its OWN ``username`` + ``password`` almost
    always means "use these directly" — so it opts OUT of browser to ``basic`` (no
    browser window, straight Table-API auth). This is the common "attach a temp
    service account to prod for read-only checks" case: just add username/password,
    no need to also spell out ``auth_type``.

    Precedence:
      1. explicit ``auth_type`` on the entry always wins (set ``"browser"`` to keep
         browser even with creds present, or ``"oauth"``/``"api_key"`` as needed);
      2. else, if the default is browser AND the entry carries both username and
         password, use ``basic``;
      3. else, the global default.
    """
    entry = entry or {}
    explicit = entry.get("auth_type")
    if explicit:
        return str(explicit).strip().lower()
    default = str(default_auth_type).strip().lower()
    if default == "browser" and entry.get("username") and entry.get("password"):
        return "basic"
    return default


def select_active_alias(
    entries: dict[str, dict[str, Any]],
    *,
    active_alias: str | None,
    legacy_instance_url: str | None,
) -> str | None:
    """Choose the active alias without changing legacy single-instance behavior."""
    if not entries:
        return None
    if active_alias:
        alias = active_alias.strip()
        if alias not in entries:
            raise ValueError(
                f"{ACTIVE_INSTANCE_ENV}='{alias}' is not present in {INSTANCE_CONFIG_ENV}"
            )
        return alias
    if legacy_instance_url:
        return None
    if len(entries) == 1:
        return next(iter(entries))
    raise ValueError(
        f"{ACTIVE_INSTANCE_ENV} is required when {INSTANCE_CONFIG_ENV} defines multiple instances"
    )


def safe_instance_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.hostname or url
