"""Cookie-header string manipulation helpers.

Extracted verbatim from auth_manager.py (v1.18.25). Pure string functions —
no state, no I/O. auth_manager re-imports every symbol so its namespace stays
byte-identical for callers and tests.
"""

from typing import Optional


def _extract_cookie_names(cookie_header: Optional[str]) -> list[str]:
    if not cookie_header:
        return []
    names: list[str] = []
    for part in cookie_header.split(";"):
        token = part.strip()
        if not token or "=" not in token:
            continue
        names.append(token.split("=", 1)[0].strip())
    return names


def _cookie_header_to_dict(cookie_header: Optional[str]) -> dict[str, str]:
    if not cookie_header:
        return {}
    cookie_map: dict[str, str] = {}
    for part in cookie_header.split(";"):
        token = part.strip()
        if not token or "=" not in token:
            continue
        name, value = token.split("=", 1)
        key = name.strip()
        if not key:
            continue
        cookie_map[key] = value.strip()
    return cookie_map


def _replace_cookie_value_in_header(cookie_header: str, name: str, new_value: str) -> str:
    """Swap the value of cookie ``name`` in a serialized ``Cookie:`` header.

    If ``name`` is not present, append it. Used by v1.12.18 BIG-IP
    routing absorption to overwrite ``BIGipServerpool_<host>`` with the
    backend value the server hinted at via Set-Cookie. Preserves order
    and other cookies untouched so the request looks otherwise identical
    to the rejected one.
    """
    pairs: list[str] = []
    found = False
    for piece in cookie_header.split(";"):
        piece = piece.strip()
        if not piece:
            continue
        if "=" in piece:
            cur_name, _, _ = piece.partition("=")
            if cur_name.strip() == name:
                pairs.append(f"{name}={new_value}")
                found = True
                continue
        pairs.append(piece)
    if not found:
        pairs.append(f"{name}={new_value}")
    return "; ".join(pairs)
