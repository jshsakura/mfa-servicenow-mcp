#!/usr/bin/env python3
"""Regenerate every hand-maintained tool count in the docs from live config.

The count column of TOOL_PACKAGES had no generator and no accuracy test — it was
hand-edited, so every tool/package change silently drifted it (and the website
mirrors with it). This script is the single source of truth: it loads each
package through the real server and rewrites the count cell in every language
file, then resyncs the website mirrors.

v1.24.24 widened it past TOOL_PACKAGES, because that file was never where the
drift hurt: a sweep found the SAME counts stale in README ×6 (four releases
behind), WINDOWS_INSTALL ×6 (`portal_developer` off by twelve), the website
landing pages ×6, llm-setup, and the translated inventories — every one of them
hand-maintained, none of them checked. Numbers a person has to remember to
update in thirty files across six languages are numbers that will be wrong.

Covered now:
  * package-count table rows — identical `| \\`pkg\\` | N |` shape in
    TOOL_PACKAGES, README and WINDOWS_INSTALL, all languages
  * total-registry / `full` / unpackaged counts written as prose, matched
    through a per-language anchor (see ``PROSE_RULES``)
  * the website landing hero stat

Usage:
    python scripts/regenerate_doc_counts.py          # rewrite in place
    python scripts/regenerate_doc_counts.py --check   # exit 1 if any file is stale

The `~Tokens` column is an approximate footprint and is left untouched (it needs
tiktoken over compacted schemas; a one-tool delta is within its stated slop).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DOCS_DIR = ROOT / "docs"
# Starlight content collection: English lives at the collection root (Starlight's
# `root` locale, no URL prefix); every other locale gets its own subdirectory.
SITE_CONTENT_DIR = ROOT / "website" / "src" / "content" / "docs"
REPO_FILES_DIR = ROOT

LANGS = ["", ".es", ".hi", ".ja", ".ko", ".zh"]
LOCALE_DIR = {"": "", ".es": "es", ".hi": "hi", ".ja": "ja", ".ko": "ko", ".zh": "zh"}
# Only so a rewrite failure can name the canonical docs/ file the caller has to
# fix, rather than the generated mirror they must not edit.
_LANG_FOR_LOCALE_DIR = {directory: lang for lang, directory in LOCALE_DIR.items()}

# docs/ files that carry package-count table rows and/or prose counts.
DOC_FILES = (
    [f"TOOL_PACKAGES{lang}.md" for lang in LANGS]
    + [f"WINDOWS_INSTALL{lang}.md" for lang in LANGS]
    + [f"TOOL_INVENTORY{lang}.md" for lang in LANGS if lang]  # EN is fully generated
    + [
        "llm-setup.md",
    ]
)

# Files outside docs/ with no mirror: the READMEs at the repo root and the
# website landing pages. Same rewrite rules, different home.
UNMIRRORED_FILES = [(REPO_FILES_DIR, f"README{lang}.md") for lang in LANGS] + [
    (SITE_CONTENT_DIR / LOCALE_DIR[lang], "index.mdx") for lang in LANGS
]

# The 8 nav pages that get mirrored into the Starlight content collection, one
# directory per locale (Starlight's i18n convention), with generated
# frontmatter — NOT a byte-for-byte copy like the old mkdocs mirror, because
# Starlight pages need `title`/`description` frontmatter and render their own
# H1 from `title` (a body H1 would duplicate it). `docs/*.md` stays plain
# Markdown (no frontmatter) since it's also read raw — curl'd directly by the
# LLM setup flow, viewed as-is on GitHub, and consumed by
# regenerate_tool_inventory.py.
MIRRORED_PAGES: dict[str, str] = {
    "llm-setup": "Step-by-step setup instructions for AI coding agents installing this MCP server.",
    "CLIENT_SETUP": "MCP client configuration for Claude, Cursor, Zed, Codex, OpenCode, and more.",
    "WINDOWS_INSTALL": "Windows-specific installation notes, including Smart App Control workarounds.",
    "TOOL_INVENTORY": "Full list of registered ServiceNow MCP tools, grouped by package.",
    "TOOL_PACKAGES": "Advanced reference for the read/write tool package system.",
    "catalog": "ServiceNow Service Catalog integration tools and workflows.",
    "change_management": "Change management tools available in the ServiceNow MCP server.",
    "workflow_management": "Workflow and Flow Designer tooling exposed by the MCP server.",
}

# The single mkdocs-admonition holdout (see MIRRORED_PAGES docstring above) —
# `!!! danger "title"` (4-space-indented body) -> Starlight's native
# `:::danger[title]` aside (unindented body). Only TOOL_PACKAGES*.md uses it.
_DANGER_RE = re.compile(
    r'^!!! danger "(?P<title>.+)"\n(?P<body>(?:^(?:[ \t]{4}.*)?\n?)+)',
    re.MULTILINE,
)


def _convert_admonitions(text: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        body_lines = [
            line[4:] if line.startswith("    ") else line for line in m.group("body").splitlines()
        ]
        while body_lines and body_lines[-1] == "":
            body_lines.pop()
        return f':::danger[{m.group("title")}]\n' + "\n".join(body_lines) + "\n:::\n"

    return _DANGER_RE.sub(repl, text)


# Links between docs/ pages are written as repo-relative Markdown filenames
# (`TOOL_INVENTORY.md`, `WINDOWS_INSTALL.ko.md`) because docs/ is also read raw:
# on GitHub, and curl'd by the LLM setup flow. Mirrored verbatim onto the site
# the same string becomes a dead URL — `/mfa-servicenow-mcp/ko/TOOL_INVENTORY.md`
# is not a route — and nothing anywhere says so: the Astro build is green, the
# page renders, and the link 404s only when somebody clicks it. 29 of them
# shipped that way.
#
# So the mirror rewrites them, and a target this cannot resolve is a hard
# failure rather than a link that looks fine until it is used.
#
# `../<PAGE>/` rather than an absolute path: every mirrored page sits exactly one
# directory below its locale root, so one relative form is correct for the root
# locale and for `ko/` alike, and it does not hard-code Astro's `base`.
#
# A locale suffix on the TARGET is dropped rather than honoured. The link's
# locale is the locale of the page holding it: `TOOL_INVENTORY.ko.md` inside the
# ko mirror and a bare `TOOL_INVENTORY.md` inside the same file must both land on
# `/ko/TOOL_INVENTORY/`, and docs/ mixes the two forms today.
#
# The ONE exception is a page linking to its own base from a non-root locale.
# `docs/TOOL_INVENTORY.ko.md` is a summary whose whole point is to hand the
# reader the full English inventory, and on GitHub `./TOOL_INVENTORY.md` says
# exactly that. Folded into the locale like every other link it became a link to
# the page you are already reading — the promised document, replaced by itself,
# in five locales. A self-link is never the intent, so it resolves one directory
# further up: `../../<PAGE>/`, the root locale.
_DOC_LINK_RE = re.compile(r"\]\((?P<target>[^)\s]+\.md)\)")
_LOCALE_SUFFIXES = tuple(lang for lang in LANGS if lang)


def _rewrite_doc_links(base: str, lang: str, text: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        target = m.group("target")
        # Absolute links (the GitHub blob URLs in llm-setup) are already valid
        # off-site addresses and are left exactly as written.
        if "://" in target or target.startswith("/"):
            return m.group(0)

        stem = target[:-3]
        if stem.startswith("./"):
            stem = stem[2:]
        for suffix in _LOCALE_SUFFIXES:
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break

        if stem not in MIRRORED_PAGES:
            raise SystemExit(
                f"docs/{base}{lang}.md links to {target!r}, which is not a mirrored page. "
                f"Mirrored pages: {', '.join(sorted(MIRRORED_PAGES))}. Either point the link "
                "at one of those, or make it an absolute URL — a relative *.md link cannot "
                "survive the trip onto the site."
            )
        if stem == base and lang:
            return f"](../../{stem}/)"
        return f"](../{stem}/)"

    return _DOC_LINK_RE.sub(repl, text)


def _yaml_escape(s: str) -> str:
    return s.replace('"', '\\"')


def wrap_for_starlight(base: str, text: str, locale_dir: str = "") -> str:
    """Canonical docs/ Markdown -> Starlight page: frontmatter + H1 stripped.

    ``locale_dir`` is the Starlight locale directory ("" for the root/default
    locale, else "ko"/"ja"/etc) and MUST be folded into the explicit `slug`
    for every non-root locale. Starlight's docs collection is a flat id space
    across all locales — an unprefixed `slug: CLIENT_SETUP` on every
    translation collides on the same id, and whichever locale the loader
    processes last silently wins for ALL of them (e.g. the root/English URL
    served Chinese content, with no error).
    """
    lines = text.splitlines()
    if not lines[0].startswith("# "):
        raise SystemExit(f"{base}: expected a leading H1, found {lines[0]!r}")
    title = lines[0][2:].strip()
    rest = lines[1:]
    while rest and rest[0].strip() == "":
        rest.pop(0)
    body = "\n".join(rest) + "\n"
    if base == "TOOL_PACKAGES":
        body = _convert_admonitions(body)
    body = _rewrite_doc_links(base, _LANG_FOR_LOCALE_DIR.get(locale_dir, ""), body)
    description = MIRRORED_PAGES[base]
    slug = f"{locale_dir}/{base}" if locale_dir else base
    # Explicit slug pins the URL to the page's exact on-disk casing
    # (CLIENT_SETUP, not client_setup) -- Starlight lowercases slugs by
    # default, which would silently change every URL the old mkdocs site
    # published.
    frontmatter = (
        "---\n"
        f'title: "{_yaml_escape(title)}"\n'
        f'description: "{_yaml_escape(description)}"\n'
        f"slug: {slug}\n"
        "---\n\n"
    )
    return frontmatter + body


def sync_mirrors(check: bool) -> list[str]:
    """Resync every Starlight mirror from its (possibly just-rewritten) canonical
    docs/ source. Runs unconditionally over the full page x locale matrix, not
    just the subset DOC_FILES count-rewrites, so a page whose canonical body
    changed for any other reason (translation edit, TOOL_INVENTORY
    regeneration) still gets caught.
    """
    stale: list[str] = []
    for base in MIRRORED_PAGES:
        for lang in LANGS:
            canonical = DOCS_DIR / f"{base}{lang}.md"
            if not canonical.is_file():
                continue
            wrapped = wrap_for_starlight(
                base, canonical.read_text(encoding="utf-8"), LOCALE_DIR[lang]
            )
            mirror = SITE_CONTENT_DIR / LOCALE_DIR[lang] / f"{base}.md"
            current = mirror.read_text(encoding="utf-8") if mirror.is_file() else None
            if current != wrapped:
                stale.append(f"website mirror: {mirror.relative_to(ROOT)}")
                if not check:
                    mirror.parent.mkdir(parents=True, exist_ok=True)
                    mirror.write_text(wrapped, encoding="utf-8")
    return stale


# Packages that appear in the doc tables with a live-computed count. `none` is a
# static 0 and is intentionally not recomputed.
PACKAGES = [
    "core",
    "standard",
    "service_desk",
    "portal_developer",
    "platform_developer",
    "full",
]


# Prose counts, matched by a language-specific anchor rather than by position.
# Each rule is (regex, count_key); the number must be the ONLY capture group's
# neighbour, written as ``(?P<n>\d+)``. A rule that matches nothing in a given
# file is fine — it just is not phrased that way there. A rule that matches
# MORE than once is a bug and raises, because a doc with two different totals
# is exactly the failure this script exists to prevent.
#
# `registry` = tools in the live registry (the convention TOOL_INVENTORY.md's
# own headline uses); `full` = tools packaged in `full`; `unpackaged` = the rest.
PROSE_RULES: list[tuple[str, str]] = [
    # --- totals, one phrasing per language --------------------------------
    (r"\*\*(?P<n>\d+) registered tools\*\*", "registry"),
    (r"\*\*등록 도구 (?P<n>\d+)개\*\*", "registry"),
    (r"\*\*(?P<n>\d+) 個の登録済みツール\*\*", "registry"),
    (r"\*\*(?P<n>\d+) 个已注册工具\*\*", "registry"),
    (r"\*\*(?P<n>\d+) herramientas registradas\*\*", "registry"),
    (r"\*\*(?P<n>\d+) पंजीकृत टूल\*\*", "registry"),
    # --- generated-inventory headlines, translated ------------------------
    (r"(?<=Registered tools in the live registry: \*\*)(?P<n>\d+)(?=\*\*)", "registry"),
    (r"(?<=ライブレジストリに登録されているツール: \*\*)(?P<n>\d+)(?=\*\*)", "registry"),
    (r"(?<=实时注册表中已注册的工具数：\*\*)(?P<n>\d+)(?=\*\*)", "registry"),
    (r"(?<=Herramientas registradas en el registro activo: \*\*)(?P<n>\d+)(?=\*\*)", "registry"),
    (r"(?<=लाइव रजिस्ट्री में पंजीकृत टूल: \*\*)(?P<n>\d+)(?=\*\*)", "registry"),
    (r"(?<=전체 등록 도구: \*\*)(?P<n>\d+)(?=\*\*)", "registry"),
    (r"(?<=Packaged tool count in `full`: \*\*)(?P<n>\d+)(?=\*\*)", "full"),
    (r"(?<=`full` にパッケージ化されたツール数: \*\*)(?P<n>\d+)(?=\*\*)", "full"),
    (r"(?<=`full` 中打包的工具数：\*\*)(?P<n>\d+)(?=\*\*)", "full"),
    (r"(?<=Recuento de herramientas empaquetadas en `full`: \*\*)(?P<n>\d+)(?=\*\*)", "full"),
    (r"(?<=`full` में पैकेज किए गए टूल की संख्या: \*\*)(?P<n>\d+)(?=\*\*)", "full"),
    (r"(?<=가장 넓은 개발 패키지 `full`: \*\*)(?P<n>\d+)(?=\*\*)", "full"),
    (r"(?<=기본 패키지 `standard`: \*\*)(?P<n>\d+)(?=\*\*)", "standard"),
    (r"(?<=Registered but currently unpackaged tools: \*\*)(?P<n>\d+)(?=\*\*)", "unpackaged"),
    (r"(?<=登録済みだが現在パッケージ化されていないツール: \*\*)(?P<n>\d+)(?=\*\*)", "unpackaged"),
    (r"(?<=已注册但当前未打包的工具数：\*\*)(?P<n>\d+)(?=\*\*)", "unpackaged"),
    (
        r"(?<=Herramientas registradas pero actualmente sin empaquetar: \*\*)(?P<n>\d+)(?=\*\*)",
        "unpackaged",
    ),
    (r"(?<=पंजीकृत परंतु वर्तमान में अनपैकेज्ड टूल: \*\*)(?P<n>\d+)(?=\*\*)", "unpackaged"),
    (r"(?<=현재 어떤 패키지에도 묶이지 않은 등록 도구: \*\*)(?P<n>\d+)(?=\*\*)", "unpackaged"),
    # --- cross-references and the website hero ----------------------------
    (r"(?<=complete list of all )(?P<n>\d+)(?= tools)", "registry"),
    (r"(?<=전체 )(?P<n>\d+)(?=개 도구)", "registry"),
    # The hero block holds FOUR stats — tools, MFA, skill categories, secrets
    # shared. Anchoring on the value alone rewrote all of them to the tool count
    # (caught in review, not by a test, which is why the multi-match guard below
    # is now absolute). Match the value only when its LABEL says it is the tool
    # count, in whichever language that page is written.
    (
        r'(?<=<span class="hero-stat-value">)(?P<n>\d+)'
        r'(?=</span>\s*\n\s*<span class="hero-stat-label">'
        r"(?:Registered Tools|Herramientas registradas|पंजीकृत टूल्स|登録済みツール|등록 도구|已注册工具))",
        "registry",
    ),
    # The landing subtitle, mid-sentence in every language — anchored on the
    # noun that follows (or precedes, in ko) rather than on line position.
    (r"(?P<n>\d+)(?= registered tools load through)", "registry"),
    (r"(?P<n>\d+)(?= herramientas registradas se cargan)", "registry"),
    (r"(?P<n>\d+)(?= पंजीकृत टूल्स लोड)", "registry"),
    (r"(?P<n>\d+)(?= 個の登録済みツールがアクティブ)", "registry"),
    (r"(?<=등록 도구 )(?P<n>\d+)(?=개가 활성)", "registry"),
    (r"(?P<n>\d+)(?= 个已注册工具通过活动包配置)", "registry"),
    (r"(?<=bundled workflows \()(?P<n>\d+)(?= tools\))", "full"),
]


def live_registry_counts() -> dict[str, int]:
    """Registry-wide totals, using the same convention TOOL_INVENTORY.md prints."""
    import yaml

    from servicenow_mcp.utils.tool_utils import get_tool_definitions

    definitions = get_tool_definitions()
    packages = yaml.safe_load((ROOT / "config" / "tool_packages.yaml").read_text("utf-8"))

    packaged: set[str] = set()
    for name, entry in packages.items():
        if name == "none":
            continue
        entries = entry.get("_tools", []) if isinstance(entry, dict) else entry
        base = packages.get("standard", []) if isinstance(entry, dict) else []
        for item in list(entries) + list(base):
            packaged.add(next(iter(item)) if isinstance(item, dict) else item)

    return {
        "registry": len(definitions),
        "unpackaged": len([n for n in definitions if n not in packaged]),
    }


def live_package_counts() -> dict[str, int]:
    """Return {package: exposed tool count} from the real server, per package."""
    from servicenow_mcp.server import ServiceNowMCP
    from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

    config = ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )
    counts: dict[str, int] = {}
    prev_pkg = os.environ.get("MCP_TOOL_PACKAGE")
    prev_path = os.environ.get("TOOL_PACKAGE_CONFIG_PATH")
    os.environ.pop("TOOL_PACKAGE_CONFIG_PATH", None)
    try:
        for pkg in PACKAGES:
            os.environ["MCP_TOOL_PACKAGE"] = pkg
            counts[pkg] = len(ServiceNowMCP(config).enabled_tool_names)
    finally:
        for key, prev in (("MCP_TOOL_PACKAGE", prev_pkg), ("TOOL_PACKAGE_CONFIG_PATH", prev_path)):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
    return counts


def _only_the_number(count: int) -> "Callable[[re.Match[str]], str]":
    """Replace ONLY the ``n`` group, keeping every other character of the match.

    ``re.sub`` replaces the whole match, not the group — so a rule that carries
    its anchor inside the pattern (``\\*\\*(?P<n>\\d+) registered tools\\*\\*``)
    silently ATE the sentence and left a bare number behind. Caught by reading
    the diff. Splicing on the group's span makes both rule styles — anchored
    inside, or anchored by lookaround — safe by construction.
    """

    def _splice(match: "re.Match[str]") -> str:
        whole = match.group(0)
        start = match.start("n") - match.start(0)
        end = match.end("n") - match.start(0)
        return f"{whole[:start]}{count}{whole[end:]}"

    return _splice


def _rewrite(text: str, counts: dict[str, int]) -> str:
    """Rewrite every count this file states, table rows and prose alike.

    A package row is rewritten only where that package HAS a row: the docs
    disagree about which packages they tabulate (WINDOWS_INSTALL omits `none`,
    the READMEs split read-only and write-capable into two tables). Absent is
    fine; present-twice is not, and raises.
    """
    for pkg, count in counts.items():
        if pkg in ("registry", "unpackaged"):
            continue
        # | `pkg` | <count> | ...   — anchor on the unique package-name cell so
        # portal_developer/platform_developer (same count) never collide.
        pattern = re.compile(rf"(^\| `{re.escape(pkg)}` \| )\d+( \|)", re.MULTILINE)
        new, n = pattern.subn(rf"\g<1>{count}\g<2>", text)
        if n > 1:
            raise SystemExit(f"expected at most 1 row for `{pkg}`, found {n}")
        text = new

    for pattern_text, key in PROSE_RULES:
        prose_count = counts.get(key)
        if prose_count is None:
            continue
        pattern = re.compile(pattern_text, re.MULTILINE)
        matches = pattern.findall(text)
        if not matches:
            continue
        if len(matches) > 1:
            # ALWAYS fatal. The first version of this exempted the registry
            # count "because a page might state it twice" — and that exemption
            # let one loose pattern rewrite the website's MFA/skills/secrets
            # hero stats to the tool count. A rule that matches twice is a rule
            # that does not know what it is editing; make it prove otherwise.
            raise SystemExit(
                f"'{pattern_text}' matched {len(matches)}x — ambiguous; tighten the anchor"
            )
        text = pattern.sub(_only_the_number(prose_count), text)
    return text


def apply(check: bool) -> int:
    counts = {**live_package_counts(), **live_registry_counts()}
    stale: list[str] = []

    for name in DOC_FILES:
        canonical = DOCS_DIR / name
        if not canonical.is_file():
            continue
        original = canonical.read_text(encoding="utf-8")
        updated = _rewrite(original, counts)
        if updated != original:
            stale.append(name)
            if not check:
                canonical.write_text(updated, encoding="utf-8")

    # Starlight mirrors: resync from canonical docs/ (which may have just been
    # rewritten above) regardless of whether THIS run touched counts — catches
    # drift from any other canonical edit too.
    stale.extend(sync_mirrors(check))

    # READMEs and the website landing pages (.mdx): same counts, no mirror to
    # keep in step — the landing page IS the canonical copy.
    for directory, name in UNMIRRORED_FILES:
        path = directory / name
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        updated = _rewrite(original, counts)
        if updated != original:
            stale.append(name)
            if not check:
                path.write_text(updated, encoding="utf-8")

    counts_str = ", ".join(f"{k}={v}" for k, v in counts.items())
    if check:
        if stale:
            print(f"STALE doc counts ({counts_str}): {', '.join(stale)}", file=sys.stderr)
            print("Fix: python scripts/regenerate_doc_counts.py", file=sys.stderr)
            return 1
        print(f"doc counts up to date ({counts_str})")
        return 0
    print(f"Live counts: {counts_str}")
    print(f"Updated {len(stale)} file(s): {', '.join(stale) or '(none — already current)'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if any file is stale")
    args = parser.parse_args()
    return apply(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
