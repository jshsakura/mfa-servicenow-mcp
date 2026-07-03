# Security Policy

## Supported Versions

Security fixes land on the latest released version only. This project ships
frequent patch releases (`x.y.z → x.y.(z+1)`); please upgrade to the newest
release before reporting.

| Version  | Supported          |
| -------- | ------------------ |
| 1.18.x   | :white_check_mark: |
| < 1.18   | :x:                |

## Reporting a Vulnerability

Please report suspected vulnerabilities **privately** — do not open a public
issue for anything exploitable.

- **Preferred**: open a [GitHub Security Advisory](https://github.com/jshsakura/mfa-servicenow-mcp/security/advisories/new)
  (private, coordinated disclosure).
- **Alternative**: contact the maintainer via the email on the GitHub profile.

**What to expect:**

| Stage | Target |
| --- | --- |
| Acknowledgement of your report | within 72 hours |
| Initial assessment (accepted / needs-info / declined) | within 7 days |
| Fix or mitigation for accepted reports | as a prioritized patch release |

Please include: affected version, reproduction steps, and the impact you
observed. If a report is accepted, you will be credited in the release notes
unless you request otherwise.

## Scope Notes

This is a personal-use, open-source tool that operates against **live
ServiceNow instances** using the caller's own authenticated session. Read the
project's Safety Policy (in the README) for the trust model: the write
`confirm='approve'` gate prevents *accidental* mutations by an LLM, not a
determined adversary who controls the prompt. Cached sessions are stored under
`~/.servicenow_mcp/` with `0600`/`0700` permissions but **not** encrypted at
rest — treat that directory as sensitive and keep it off cloud-synced paths.
