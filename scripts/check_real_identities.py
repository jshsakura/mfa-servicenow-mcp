#!/usr/bin/env python3
"""Block real people, accounts and companies from entering a public repo.

This exists because the rule in CLAUDE.md was prose, and prose is advisory: it
only works if whoever writes the line happens to remember it. Three real
identifiers reached the public history anyway — a colleague's full name + login
in a test fixture, a work email in a source comment, and a second colleague's
ServiceNow login in two more fixtures. Every one arrived the same way: real debug
output pasted from a live session straight into a test.

A push cannot be taken back. The string stays reachable by SHA even after a later
commit "fixes" the file, and the only real remedy is a full history rewrite plus
asking the host to purge cached objects. So the check belongs BEFORE the commit,
not in a review someone might skip.

Default-deny by shape: an identity-shaped value is refused unless it is a known
placeholder. Adding a new placeholder is a deliberate one-line edit here.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Identity-carrying fields. A value landing in one of these IS an account name.
_IDENTITY_FIELDS = (
    "sys_updated_by",
    "sys_created_by",
    "sys_recorded_by",
    "held_by",
    "updated_by",
    "created_by",
    "user_name",
    "login",
    "baseline_by",
    "remote_updated_by",
    "live_updated_by",
    "impersonating",
)
_FIELD_VALUE = re.compile(
    r"""['"](?:%s)['"]\s*[:=]\s*['"]([^'"]+)['"]""" % "|".join(_IDENTITY_FIELDS)
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")

# Placeholders. Obviously-fake names only — extend deliberately, never to make a
# real value pass. If you are tempted to add someone's actual login here, that is
# the check working.
ALLOWED_ACTORS = {
    "",
    "admin",
    "system",
    "guest",
    "anonymous",
    "unknown",
    "nobody",
    "somebody",
    "someone",
    "whoever",
    "me",
    "you",
    "user",
    "tester",
    "test",
    "test_user",
    "alice",
    "alice2",
    "alice.radiology",
    "bob",
    "bob.chiefradiology",
    "carol",
    "dave",
    "eve",
    "mallory",
    "trent",
    "dev",
    "dev1",
    "dev2",
    "dev.user",
    "other.dev",
    "newbie",
    "maint",
    "jane.doe",
    "john.doe",
    "jdoe",
    "abel.tuter",
    "beth.anglin",
    "employee",
    "manager",
    "requester",
    "approver",
    "developer",
    "x",
    "y",
    "z",
    "a",
    "b",
    "c",
}
ALLOWED_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "test.com",
    "corp.com",
    "company.co.kr",
    "domain.com",
    "mail.com",
    "localhost",
    "x.com",
    "y.com",
    "w.com",
    "e.com",
    "ex.com",
    "acme.com",
    "users.noreply.github.com",
    "noreply.github.com",
    "anthropic.com",
    "a.com",
    "b.com",
    "c.com",
    "d.com",
    "z.com",
    "foo.com",
    "bar.com",
    "service-now.com",
}

# `given.surname` in free text — the shape a work email or a display name takes
# when it is pasted out of a live session. Deliberately narrow: a SEPARATOR is
# required and two-letter surnames are excluded, because without both, ordinary
# words match (`json` = j+son, `README.ko`) and a check that cries wolf gets
# disabled, which is worse than not having one. A bare-concatenated login like
# `gsomething` is caught by the identity-field default-deny above instead.
_SURNAMES = (
    "choi|kim|lee|park|jang|jung|jeong|yoon|shin|hwang|kang|cho|song|han|seo"
    "|nam|ryu|lim|bae|baek|noh|moon|yang|son|jeon|hong|gwon|kwon"
)
_SURNAME_LOGIN = re.compile(rf"\b[a-z]{{3,12}}[._-](?:{_SURNAMES})\b", re.IGNORECASE)

# A scoped ServiceNow application is `x_<vendor-code>_<app>`, and the vendor code
# is assigned to a real company — so it names a customer just as surely as a
# domain does, and it arrives the same way: pasted out of a live session along
# with the table names hanging off it, which spell out what the customer's
# system does. The person rules above could not see any of that, which is how a
# real scope sat in four test files.
#
# Default-deny on the VENDOR segment only, so `x_myapp_billing_request_header`
# passes on its prefix and the table half stays free — inventing an allowlist of
# table names would fail on the first fixture nobody thought of.
ALLOWED_SCOPE_VENDORS = {
    # Already in the suite before this rule existed, and all obviously invented.
    "my",
    "other",
    "multifactor",
    "usertoken",
    "myapp",
    "app",
    "acme",
    "company",
    "test",
    "demo",
    "example",
    "sample",
    "scope",
    "custom",
    "vendor",
    "foo",
    "bar",
}
_SCOPE_NAMESPACE = re.compile(r"\bx_([a-z0-9]{2,})_[a-z0-9_]+\b")

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "site", "dist", "build"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf", ".lock", ".bundle"}


def _staged_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return []
    return [REPO / line for line in out.splitlines() if line.strip()]


def _all_files() -> list[Path]:
    """TRACKED files only. An untracked/gitignored file (a local .mcp.json with
    the real instance in it) was never pushed and is not this check's business —
    flagging it teaches people to ignore the output."""
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return []
    return [REPO / line for line in out.splitlines() if line.strip()]


def scan(path: Path) -> list[str]:
    """Identity-shaped values in one file. Empty list = clean."""
    if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
        return []
    # This file names the patterns it blocks; scanning it would flag itself.
    if path.resolve() == Path(__file__).resolve():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    hits: list[str] = []
    for num, line in enumerate(text.splitlines(), 1):
        for actor in _FIELD_VALUE.findall(line):
            value = actor.strip().lower()
            # An identity field holding an address is judged as an address —
            # the domain is what says whether it is real.
            email = _EMAIL.fullmatch(value)
            if email and email.group(1).lower() in ALLOWED_EMAIL_DOMAINS:
                continue
            if value not in ALLOWED_ACTORS:
                hits.append(
                    f"{path.relative_to(REPO)}:{num}: account '{actor}' is not a placeholder"
                )
        for domain in _EMAIL.findall(line):
            if domain.lower() not in ALLOWED_EMAIL_DOMAINS:
                hits.append(
                    f"{path.relative_to(REPO)}:{num}: email domain '{domain}' is not a placeholder"
                )
        for match in _SURNAME_LOGIN.findall(line):
            hits.append(
                f"{path.relative_to(REPO)}:{num}: '{match}' looks like a real person's login"
            )
        for vendor in _SCOPE_NAMESPACE.findall(line):
            if vendor.lower() not in ALLOWED_SCOPE_VENDORS:
                hits.append(
                    f"{path.relative_to(REPO)}:{num}: scope vendor 'x_{vendor}_' is not a "
                    "placeholder — a scope prefix identifies a real company"
                )
    return hits


def main() -> int:
    targets = _all_files() if "--all" in sys.argv else _staged_files()
    hits: list[str] = []
    for path in targets:
        hits.extend(scan(path))
    if not hits:
        return 0
    print("REAL IDENTITY BLOCKED — do not commit this.\n")
    for hit in hits[:40]:
        print(f"  {hit}")
    if len(hits) > 40:
        print(f"  ... and {len(hits) - 40} more")
    print(
        "\nThis is a public repo. A push cannot be taken back: the string stays\n"
        "reachable by SHA even after a later commit removes it, and undoing it\n"
        "means rewriting every commit and asking the host to purge its cache.\n\n"
        "Replace it with a placeholder (alice / bob / other.dev / example.com).\n"
        "If the value really is fake, add it to ALLOWED_* in scripts/check_real_identities.py\n"
        "— deliberately, and never to make a real value pass."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
