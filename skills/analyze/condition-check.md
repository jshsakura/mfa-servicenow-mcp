---
name: condition-check
description: Settle how an encoded query or condition really behaves (empty values, !=, OR order, unknown fields) by counting on a live instance
context_cost: low
safety_level: none
delegatable: yes
required_input: the query or condition text and its table
output: report
tools:
  - sn_aggregate
  - sn_query
  - sn_schema
triggers:
  - "빈 값도 걸려"
  - "조건 맞아"
  - "이 쿼리 어떻게 동작"
  - "같지 않음이면"
  - "ISEMPTY"
  - "does this condition match empty"
  - "how does this query behave"
---

# Instructions

Never answer a query-semantics question from memory or docs. ServiceNow
silently changes a query it does not like (an unknown field DROPS its condition
and returns the whole table), so the only answer is a count on the live
instance the question is about. Say which instance the numbers came from.

## Pipeline

1. **Field exists?** `sn_schema(table=T)` or the local `_schema/<T>.json`.
   A misspelled field is the most common wrong answer — it never errors.

2. **Split the question into counts — all with `sn_aggregate`, never by reading rows:**

   | Count | query |
   |---|---|
   | A  all | (none) |
   | B  the condition | `<the query as written>` |
   | E  empty | `FISEMPTY` |
   | N  not empty | `FISNOTEMPTY` |
   | V  equals the value | `F=<value>` |

   CALL `sn_aggregate(table=T, query="<q>")` for each. Group instead of listing when
   you need a breakdown: `group_by="F"`.

3. **Read the answer off the numbers:**
   - `B == A` while the condition should filter → the condition was DROPPED
     (unknown field, bad operator). Not "everything matches".
   - `F!=X` includes empties ⇔ `B == A - V` (empties counted in); excludes ⇔ `B == N - V`.
   - `E + N != A` → F is not a plain column (dot-walk, journal, glide_list): say so.
   - OR chains: the first term decides how bad a dropped name is — measure the
     chain as written, not each term alone.

4. **Database query vs condition on one record.** These counts prove how the
   DATABASE filters (lists, GlideRecord queries, `sn_query`). A business-rule
   condition, a flow trigger condition or a UI policy is evaluated on ONE record
   in memory by a different engine and can treat empty differently. If the
   question is "will this rule/flow fire", the proof is a record that went
   through it (`flow-trigger-tracing` step 4). Creating a test record to find
   out is a write: ask first.

## Report

```
<T>: <query> on <instance>
A=<n> B=<n> E=<n> N=<n> V=<n>
Answer: <one sentence>, measured — <database query | record condition not proven>
```

## ON ERROR

- Aggregate refused / 403 → say the count is unread; do not fall back to reading rows
- A count that cannot be split (journal, list fields) → report it as not decidable by count

## DELEGATE hint

Delegatable. Return the report block only.
