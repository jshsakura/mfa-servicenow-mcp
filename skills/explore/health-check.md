---
name: health-check
description: Verify instance connectivity and authentication in 30 seconds
context_cost: low
safety_level: none
delegatable: false
required_input: none
output: status
tools:
  - sn_health
  - sn_query
triggers:
  - "연결 확인"
  - "왜 안 되지"
  - "상태 확인"
  - "is it working"
  - "check connection"
  - "health check"
---

# Instructions

You are checking ServiceNow connectivity. Run this FIRST when anything fails.

## Pipeline

1. CALL sn_health(timeout=15)

2. INTERPRET:
   - ok=true, 200 → fully connected
   - ok=true, 403 → browser session valid, probe path ACL-blocked (normal for browser auth)
   - ok=false, 401/302 → auth failed, session expired
   - ok=false, no status → network error, wrong URL

3. IF connected, verify data access:
   CALL sn_query(table="sys_user", query="user_name=admin", fields="sys_id,name", limit=1)

4. RETURN:
   - Connection: OK/FAIL
   - Auth: valid/expired/error
   - Data access: confirmed/denied
   - Action needed (if any)

## ON ERROR

| Symptom | Fix |
|---------|-----|
| Timeout | check --instance-url starts with https:// |
| 401 | re-authenticate: --auth-type browser |
| Browser won't open | uvx playwright install chromium |
| 403 on everything | missing roles, contact admin |

## DELEGATE hint

DO NOT delegate. Quick operation, user needs immediate feedback.
