"""Short-lived MCP resources backed by files downloaded by this server.

The resource URI is an opaque capability.  It never contains the local path,
ServiceNow sys_id, instance URL, or credentials.  Entries live only for the
current server process and point at the exact file written by
``download_attachment``; reading a resource never re-fetches ServiceNow.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

ATTACHMENT_RESOURCE_SCHEME = "servicenow-attachment"
ATTACHMENT_RESOURCE_AUTHORITY = "resource"
ATTACHMENT_RESOURCE_MAX_MB_ENV = "SERVICENOW_ATTACHMENT_RESOURCE_MAX_MB"
DEFAULT_ATTACHMENT_RESOURCE_MAX_MB = 10
HARD_MAX_ATTACHMENT_RESOURCE_MAX_MB = 25
_MIB = 1024 * 1024
DEFAULT_ATTACHMENT_RESOURCE_MAX_BYTES = DEFAULT_ATTACHMENT_RESOURCE_MAX_MB * _MIB
DEFAULT_ATTACHMENT_RESOURCE_TTL_SECONDS = 15 * 60
DEFAULT_ATTACHMENT_RESOURCE_MAX_ENTRIES = 256

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


class AttachmentResourceError(ValueError):
    """A downloaded file cannot be registered or read safely."""


class AttachmentResourceTooLarge(AttachmentResourceError):
    """A file is too large for the explicit MCP resource transfer path."""


def get_attachment_resource_max_bytes() -> int:
    """Return the operator-configured resource limit, bounded by a hard cap."""
    configured = os.getenv(ATTACHMENT_RESOURCE_MAX_MB_ENV)
    if configured is None:
        max_mb = DEFAULT_ATTACHMENT_RESOURCE_MAX_MB
    else:
        try:
            max_mb = int(configured)
        except ValueError:
            max_mb = DEFAULT_ATTACHMENT_RESOURCE_MAX_MB
        if max_mb < 1:
            max_mb = DEFAULT_ATTACHMENT_RESOURCE_MAX_MB
    return min(max_mb, HARD_MAX_ATTACHMENT_RESOURCE_MAX_MB) * _MIB


@dataclass(frozen=True)
class AttachmentResourceEntry:
    token: str
    uri: str
    path: Path
    file_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: float
    expires_at: float
    source_instance: str = ""


def is_attachment_resource_uri(uri: str) -> bool:
    """Return whether *uri* belongs to the attachment resource scheme."""
    return urlparse(uri).scheme.lower() == ATTACHMENT_RESOURCE_SCHEME


def _token_from_uri(uri: str) -> str:
    parsed = urlparse(uri)
    token = parsed.path.lstrip("/")
    if (
        parsed.scheme.lower() != ATTACHMENT_RESOURCE_SCHEME
        or parsed.netloc != ATTACHMENT_RESOURCE_AUTHORITY
        or not _TOKEN_RE.fullmatch(token)
        or "/" in token
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise AttachmentResourceError("Invalid attachment resource URI.")
    return token


def _read_regular_file(path: Path, *, max_bytes: int) -> bytes:
    """Read a bounded regular file without following a final symlink."""
    try:
        before = path.lstat()
    except OSError as exc:
        raise AttachmentResourceError("Downloaded attachment is no longer available.") from exc
    if not stat.S_ISREG(before.st_mode):
        raise AttachmentResourceError("Downloaded attachment is not a regular file.")
    if before.st_size > max_bytes:
        raise AttachmentResourceTooLarge(
            f"Attachment is {before.st_size} bytes; resource limit is {max_bytes} bytes."
        )

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AttachmentResourceError("Downloaded attachment could not be opened safely.") from exc

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise AttachmentResourceError("Downloaded attachment is not a regular file.")
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise AttachmentResourceError("Downloaded attachment changed before it was read.")
        if opened.st_size > max_bytes:
            raise AttachmentResourceTooLarge(
                f"Attachment is {opened.st_size} bytes; resource limit is {max_bytes} bytes."
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read(max_bytes + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    if len(content) > max_bytes:
        raise AttachmentResourceTooLarge(
            f"Attachment exceeds the resource limit of {max_bytes} bytes."
        )
    if (after.st_dev, after.st_ino, after.st_size) != (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
    ):
        raise AttachmentResourceError("Downloaded attachment changed while it was read.")
    return content


class AttachmentResourceStore:
    """Bounded, in-memory registry of opaque links to downloaded files."""

    def __init__(
        self,
        *,
        max_bytes: int | None = None,
        ttl_seconds: int = DEFAULT_ATTACHMENT_RESOURCE_TTL_SECONDS,
        max_entries: int = DEFAULT_ATTACHMENT_RESOURCE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_bytes is None:
            max_bytes = get_attachment_resource_max_bytes()
        if max_bytes < 1 or ttl_seconds < 1 or max_entries < 1:
            raise ValueError("Attachment resource limits must be positive.")
        self.max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, AttachmentResourceEntry] = OrderedDict()

    def _purge_expired(self, now: float) -> None:
        expired = [token for token, entry in self._entries.items() if now >= entry.expires_at]
        for token in expired:
            self._entries.pop(token, None)

    def register(
        self,
        path: str | Path,
        *,
        file_name: str,
        mime_type: str | None,
        source_instance: str = "",
    ) -> AttachmentResourceEntry:
        """Register the exact downloaded file and return its capability entry."""
        raw_path = Path(path).expanduser()
        if raw_path.is_symlink():
            raise AttachmentResourceError("Downloaded attachment path is a symlink.")
        try:
            resolved = raw_path.resolve(strict=True)
        except OSError as exc:
            raise AttachmentResourceError("Downloaded attachment is no longer available.") from exc

        content = _read_regular_file(resolved, max_bytes=self.max_bytes)
        now = self._clock()
        self._purge_expired(now)
        while len(self._entries) >= self.max_entries:
            self._entries.popitem(last=False)

        token = secrets.token_urlsafe(32)
        while token in self._entries:  # pragma: no cover - cryptographically improbable
            token = secrets.token_urlsafe(32)
        uri = f"{ATTACHMENT_RESOURCE_SCHEME}://{ATTACHMENT_RESOURCE_AUTHORITY}/{token}"
        entry = AttachmentResourceEntry(
            token=token,
            uri=uri,
            path=resolved,
            file_name=file_name or resolved.name,
            mime_type=mime_type or "application/octet-stream",
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            created_at=now,
            expires_at=now + self.ttl_seconds,
            source_instance=source_instance,
        )
        self._entries[token] = entry
        return entry

    def read(self, uri: str) -> tuple[AttachmentResourceEntry, bytes]:
        """Resolve, validate, and read an attachment capability URI."""
        token = _token_from_uri(uri)
        entry = self._entries.get(token)
        if entry is None:
            raise AttachmentResourceError("Attachment resource not found or expired.")

        now = self._clock()
        if now >= entry.expires_at:
            self._entries.pop(token, None)
            raise AttachmentResourceError("Attachment resource expired.")

        try:
            content = _read_regular_file(entry.path, max_bytes=self.max_bytes)
        except AttachmentResourceError:
            self._entries.pop(token, None)
            raise
        if len(content) != entry.size_bytes or hashlib.sha256(content).hexdigest() != entry.sha256:
            self._entries.pop(token, None)
            raise AttachmentResourceError(
                "Downloaded attachment changed after the link was issued."
            )
        return entry, content

    def __len__(self) -> int:
        self._purge_expired(self._clock())
        return len(self._entries)
