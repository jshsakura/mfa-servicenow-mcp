# Browser Auth Risk Catalog

> Structural risks in the multi-process browser auth path. **This is not a
> diagnosis of any specific reported failure.** Each risk is labeled with its
> evidence level so future investigators don't mistake speculation for fact.
>
> Last updated: 2026-05-12 (post-v1.12.6).

---

## Architecture

Each MCP host process creates **one** `AuthManager` with **in-memory** session
state and coordinates with other processes via **disk files**
(`session_*.json`, `*.lock`) and a **shared Chromium profile**.

```
MCP Host A (e.g., Claude Code)          MCP Host B (e.g., Web IDE)
┌─────────────────────────┐             ┌─────────────────────────┐
│  AuthManager (in-memory)│             │  AuthManager (in-memory)│
│  - cookie_header        │             │  - cookie_header        │
│  - session_token (g_ck) │             │  - session_token (g_ck) │
│  - self_heal_count      │             │  - self_heal_count      │
└──────────┬──────────────┘             └──────────┬──────────────┘
           │                                       │
           ▼                                       ▼
    ┌─────────────────────────────────────────────────┐
    │  Disk (shared if user_data_dir is consistent)   │
    │  - session_{instance}_{user}.json                │
    │  - session_{instance}_{user}.lock                │
    │  - profile_{instance}_{user}/  (Chromium)        │
    └─────────────────────────────────────────────────┘
```

| State                                | Location           | Shared? |
|--------------------------------------|--------------------|---------|
| `_browser_cookie_header`             | Memory             | No      |
| `_browser_session_token` (g_ck)      | Memory + disk      | Yes (since v1.12.6) |
| `_consecutive_self_heal_count`       | Memory             | **No**  |
| `_browser_login_in_progress`         | Memory             | No      |
| Session cookies + token + TTL        | `session_*.json`   | Yes     |
| Chromium profile (SSO cookies)       | `profile_*/`       | Yes     |
| Login lock (PID + timestamp)         | `session_*.lock`   | Yes     |

---

## Risks

Evidence labels:

- **VERIFIED** — confirmed by reading the code, reproducible reasoning.
- **THEORETICAL** — possible per the code path but no observed incident.
- **SPECULATIVE** — based on general reasoning, not the code or any incident.

### R1. `SERVICENOW_BROWSER_USER_DATA_DIR` inconsistent across hosts — VERIFIED

Without an explicit shared path, sandboxed launchers can each resolve `~`
differently, producing isolated `~/.servicenow_mcp/` directories. Host A's
session is invisible to Host B; Host B fires its own login, fails in headless
mode if MFA is required.

Verification: `_resolve_user_data_dir` falls back to `_get_default_user_data_dir`
in `auth/auth_manager.py`. Mismatched `$HOME` → different default paths.

Mitigation: document the env var prominently in setup guides. Detect path
mismatch by logging the resolved path at startup (already done since v1.12.x
via `logger.info("Session cache: %s", ...)`).

### R2. Cross-process `g_ck` rotation — MITIGATED in v1.12.6

ServiceNow rotates the X-UserToken (g_ck) on response headers. Before v1.12.6
each process kept its own in-memory token; one process absorbing a rotation
left siblings using the stale value, eventually triggering a 302 to
`/logout_success.do` on protected endpoints (e.g. `sp_widget.client_script`,
write operations, processflow API).

Fix shipped in v1.12.6:
- `_save_session_to_disk` / `_load_session_from_disk` / `_reload_session_from_disk`
  track the session file's mtime.
- `_reload_session_from_disk` now adopts a rotated `session_token` even when
  cookies are unchanged (returns True for the rotation case).
- `_maybe_adopt_sibling_session_update` runs at the top of the BROWSER branch
  in `get_headers()`. Single `os.stat()` fast path; reloads only when mtime is
  newer than what we last saw.

### R3. Circuit breaker state desync — VERIFIED

`_consecutive_self_heal_count` is in-memory only. Host A can be stuck in
`SELF_HEAL_CIRCUIT_OPEN` while Host B works fine. Users see intermittent
"circuit open" errors that look random across terminals.

Recovery paths today: the throttled escape probe (once per 30 s) or process
restart. Not yet persisted to disk.

### R4. Disk lock PID reuse — THEORETICAL

`_acquire_login_lock` checks staleness via `os.kill(pid, 0)`. On Linux, PIDs
are recycled. If an unrelated process takes the same PID after the original
crashed, the staleness check passes and other hosts block up to 180 s waiting
for a login that never comes.

Probability: low in practice (PID space is large, MCP processes are
short-lived). But the failure mode is severe (multi-minute hang on every
host) so it's worth a defensive timestamp-only check at some point.

### R5. Chromium profile lock contention — THEORETICAL, partially handled

Two processes that both try to open the same persistent Chromium profile race
on the profile's filesystem lock. `_launch_persistent_with_retry` already
retries 5 times with backoff on this exact case. Survives the typical 1-2 s
contention window. Pathological cases (one process hangs holding the profile)
still result in the other timing out.

### R6. Incomplete cookie set after profile restore — RESOLVED pre-v1.12.0

v1.12.0 removed `_try_profile_cookies_directly()` because it sometimes
adopted an incomplete cookie set (missing `JSESSIONID` and `BIGipServer*`).
Profile restore now goes through Playwright navigation, which is slower but
captures the full cookie set.

### R7. Concurrent `get_headers()` race on the same profile — RESOLVED in current code

The in-process `_browser_login_lock` wraps both `_try_restore_browser_session`
and the full login path (see `get_headers()` BROWSER branch, around the
`acquired = self._browser_login_lock.acquire(...)` line). Earlier drafts of
this catalog flagged the restore as running outside the lock — that was a
misread.

### R8. Headless gate forces interactive even without DISPLAY — THEORETICAL

When the headless probe fails the MFA-cookie gate, the wrapper retries with
`force_interactive=True`, which launches Chromium without `headless=True`. On
a server with no `DISPLAY`/`WAYLAND_DISPLAY` the visible launch fails or
hangs until timeout, incrementing the cooldown backoff. Affects only deploys
where the MCP host runs on a different machine than the user's GUI; not the
typical local install.

---

## Diagnosis Checklist

| Check                          | Command / Method                                          | Look for                                |
|--------------------------------|-----------------------------------------------------------|-----------------------------------------|
| Path consistency               | `find / -name "session_*.json" 2>/dev/null`               | Files in different home directories     |
| Lock file staleness            | `cat ~/.servicenow_mcp/*.lock` (or active cache dir)      | PID that doesn't exist anymore          |
| Circuit breaker state          | Log search `SELF_HEAL_CIRCUIT_OPEN`                       | Only appearing in some hosts            |
| Profile lock contention        | Log search `Chromium profile locked`                      | Concurrent login attempts               |
| Cross-process g_ck rotation    | Log search `Cross-process X-UserToken rotation adopted`   | Confirms v1.12.6 adoption fired         |
| User-cancelled login           | Log search `LOGIN_CANCELLED_BY_USER`                      | User closed browser window              |
| Grace-period rapid relogin     | Log search `Fresh session born dead`                      | Cookie propagation lag                  |

When triaging a real failure, the **decisive signal** is the response
`Location` header on the failing call:
- `/login.do` → cookies untrusted (full re-auth needed)
- `/logout_success.do` → server already terminated the session
- anywhere else → check ACL / instance routing, not auth

---

## Key Files

| File                                            | Lines  | Role |
|-------------------------------------------------|--------|------|
| `src/servicenow_mcp/auth/auth_manager.py`       | ~3,800 | Browser login, session cache, probes, self-heal, circuit breaker, cross-process coordination |
| `src/servicenow_mcp/utils/config.py`            | ~85    | `BrowserAuthConfig`, `AuthConfig`, `ServerConfig` |
| `src/servicenow_mcp/cli.py`                     | ~400   | Arg parsing, config construction, Playwright pre-install |
| `src/servicenow_mcp/server.py`                  | ~960   | Creates AuthManager, delegates tool calls |

---

## Outstanding Improvements

Ordered roughly by impact for the typical multi-terminal user:

1. **Persist `_consecutive_self_heal_count` to disk** so all hosts share the
   circuit breaker state (R3). Mirror the v1.12.6 mtime-poll pattern.
2. **Replace PID-based lock staleness with timestamp-only check** (R4) — 5
   min max lock age regardless of PID liveness.
3. **Surface path mismatch loudly** at startup (R1) — if any other process's
   resolved cache dir differs from this one, log a WARNING.
4. **Document `SERVICENOW_BROWSER_USER_DATA_DIR`** in the README setup
   section (R1) — the single most common cause of "session not shared"
   confusion.
