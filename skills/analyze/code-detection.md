---
name: code-detection
description: Find missing conditional branches — where code handles some values but not all required ones
context_cost: medium
safety_level: none
delegatable: true
required_input: required_codes (list) + scope or widget_ids
output: report
tools:
  - detect_missing_profit_company_codes
  - get_portal_component_code
triggers:
  - "누락된 조건"
  - "분기 빠진 거"
  - "회사코드 확인"
  - "모든 케이스 처리하는지"
  - "missing branches"
  - "check all cases handled"
---

# Instructions

You are detecting incomplete conditional logic in widget code.

## Pipeline

1. CALL detect_missing_profit_company_codes
   - required_codes = INPUT_CODES (e.g., ["2400", "5K00", "2J00"])
   - target_field_patterns = INPUT_PATTERNS (e.g., ["profit_company_code", "c.data.profit_company_code"])
   - scope = INPUT_SCOPE (if given)
   - widget_ids = INPUT_WIDGET_IDS (if given)
   - include_widget_client_script = true
   - include_widget_server_script = true
   - include_angular_providers = true
   - max_widgets = 25
   - output_mode = "compact"

2. FILTER results:
   - confidence "high" → definite missing branch, report first
   - confidence "medium" → likely missing, report second
   - confidence "low" → skip (probable false positive)

3. FOR EACH high/medium finding:
   CALL get_portal_component_code(table="sp_widget", sys_id=finding.sys_id, fields=[finding.field])
   → VERIFY the missing code isn't handled in a default case or elsewhere

4. RETURN:
   - Confirmed missing: list with location, found codes, missing codes
   - Needs review: medium confidence items
   - Skipped: low confidence count

## ON ERROR

- "required_codes must contain at least 2" → need 2+ values to detect omissions
- 0 findings → all codes handled (good) or wrong scope

## DELEGATE hint

Delegatable. Return findings summary only.
