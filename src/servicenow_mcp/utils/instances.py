"""Environment-driven ServiceNow instance configuration helpers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from servicenow_mcp.utils import json_fast

INSTANCE_CONFIG_ENV = "SERVICENOW_INSTANCE_CONFIG"
ACTIVE_INSTANCE_ENV = "SERVICENOW_ACTIVE_INSTANCE"

_ENV_REF_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def has_env_reference(value: Any) -> bool:
    """True when *value* textually contains a ``${`` env-reference marker.

    Companion to :func:`resolve_env_reference`, which only expands FULL
    ``${VAR}`` values. A partial/embedded reference ("${VAULT}_prod", "${A}b")
    passes through resolution unchanged — callers use this check to reject such
    values loudly instead of shipping the literal ``${...}`` as a credential.
    Single source of truth for "did the user intend interpolation here".
    """
    return isinstance(value, str) and "${" in value


def resolve_env_reference(value: str | None) -> str | None:
    """Resolve ``${ENV_NAME}`` style values to the actual environment value.

    Shared by the active-instance path (cli) and the named-instance contexts
    (server) so per-instance credentials never have to be plaintext in
    SERVICENOW_INSTANCE_CONFIG. Non-placeholder values pass through unchanged;
    an unset or self-referential env var resolves to None (caller decides
    whether that is fatal — for credentials it should be, never a silent
    fallback to another instance's secret).
    """
    if not value:
        return value
    stripped = value.strip()
    match = _ENV_REF_PATTERN.match(stripped)
    if not match:
        return value
    resolved = os.getenv(match.group(1))
    if not resolved or resolved.strip() == stripped:
        return None
    return resolved


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
    """Resolve an instance's auth type: explicit entry value, else the default.

    Browser is the global default. Per-profile ``username``/``password`` do NOT
    change the auth type — they select WHO (browser prefill + declared owner for
    the G10 identity guard), overriding the global credentials for that profile.
    The former creds-present → basic auto-downgrade is gone: it silently broke
    MFA/SSO instances (basic can't pass MFA) the moment a profile declared its
    owner. Want straight Table-API auth? Say so: ``auth_type: "basic"``.
    """
    entry = entry or {}
    explicit = entry.get("auth_type")
    if explicit:
        return str(explicit).strip().lower()
    return str(default_auth_type).strip().lower()


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
