"""Receiving one large archive as a sequence of small requests.

An export archive is tens or hundreds of megabytes, and the path from a browser to
an importer is not one hop. Every hop has an opinion about how large a request body
may be, and the smallest one wins: Cloudflare refuses a body over 100 MB on every
plan below Enterprise, and it refuses it *at the edge* after roughly three megabytes
have been pushed — so a 200 MB Apple Health export failed at "2 %" without any
service in this repository ever seeing a byte of it. Coolify's ingress, a stock nginx
and a hardened Traefik all have limits of their own. None of them can be raised from
here, and an operator should not have to.

A part small enough to pass all of them can be sent, and reassembling parts is what
this module does: a session names one spool file, each part appends to it at an
explicit offset, and completing the session hands the finished file to the caller.

The offset is what makes it correct rather than merely small:

* A part that arrives twice — the retry of a request whose response was lost — names
  the offset it belongs at, so it is refused instead of appended a second time.
  Appending it would corrupt the archive silently, which is the failure mode this
  design exists to rule out.
* A part that arrives out of order is refused with the offset the server actually
  wants, which is also everything a client needs to *resume*: an upload interrupted
  at 80 % continues from 80 %, rather than starting again from nothing.
* A part whose transfer dies half-written leaves the spool truncated back to the last
  complete offset, so the session stays usable rather than becoming quietly wrong.

The spool holds somebody's medical history. It is therefore per-tenant and invisible
to any other tenant (AGENTS.md rule 2), it lives in a private directory that is
emptied when the service starts, and a session that stops being written to is swept
away rather than kept for the day its owner might come back to it.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from asyncio import Lock
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: What one part may weigh. Chosen against the smallest limit on the way in rather
#: than against what a disk likes: 8 MB passes every proxy this platform is deployed
#: behind, and a small part also bounds what one dropped connection costs — a part,
#: retried, instead of the whole archive.
DEFAULT_CHUNK_BYTES = 8 * 1024 * 1024

#: How long an unfinished upload may sit on disk before it is deleted unread.
DEFAULT_TTL_SECONDS = 60 * 60

#: Suffix of every spool file, so a sweep can recognise its own leftovers and never
#: deletes anything else that happens to share the directory.
_SPOOL_SUFFIX = ".part"


class UploadSpoolError(Exception):
    """Base class for everything this module refuses to do."""


class UnknownUpload(UploadSpoolError):
    """No such session for this tenant — wrong id, wrong workspace, or swept away."""


class OffsetMismatch(UploadSpoolError):
    """A part arrived at the wrong place.

    Carries the offset the spool does want, which is what lets a client resume
    rather than restart.
    """

    def __init__(self, expected: int) -> None:
        super().__init__(f"The next part must start at byte {expected}.")
        self.expected = expected


class SpoolTooLarge(UploadSpoolError):
    """The upload exceeds what this importer accepts in total."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"The upload is larger than {limit // (1024 * 1024)} MB.")
        self.limit = limit


@dataclass
class UploadSession:
    """One archive being assembled, and where it has got to."""

    id: str
    tenant_id: str
    source_id: str
    path: Path
    #: What the client said it would send, if it said. Used to reject an upload that
    #: cannot fit before any of it is sent, and to notice a truncated one at the end.
    total_bytes: int | None
    received: int = 0
    touched: float = field(default_factory=time.monotonic)
    #: Serialises parts. A client sends them one at a time; the lock is what makes
    #: the offset rule hold even when it does not.
    lock: Lock = field(default_factory=Lock, repr=False)

    @property
    def complete(self) -> bool:
        """Has as much arrived as was announced? True when nothing was announced."""
        return self.total_bytes is None or self.received >= self.total_bytes


class UploadSpool:
    """Assembles chunked uploads under one directory, one file per session.

    Local to the process that received the parts, deliberately: the parts of one
    upload must reach one instance, and nothing is shared between services
    (AGENTS.md rule 6). An importer therefore runs as a single replica for the
    upload path, which is also true of the single-request path it replaces — that
    one spooled to this instance's disk as well.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_bytes: int,
        chunk_bytes: int = DEFAULT_CHUNK_BYTES,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._root = root
        self._max_bytes = max_bytes
        self._chunk_bytes = chunk_bytes
        self._ttl = ttl_seconds
        self._sessions: dict[str, UploadSession] = {}

        # A fresh process holds no sessions, so anything already here is a leftover
        # of the one before it — health data that nothing will ever read. Removed
        # now rather than left for a sweep that only runs while the service is busy.
        self._root.mkdir(parents=True, exist_ok=True)
        os.chmod(self._root, 0o700)
        for orphan in self._root.glob(f"*{_SPOOL_SUFFIX}"):
            orphan.unlink(missing_ok=True)

    @property
    def chunk_bytes(self) -> int:
        """The part size a client should use. The server decides, so the limit lives
        in one place instead of in every client that ever uploads."""
        return self._chunk_bytes

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def begin(
        self,
        tenant_id: str,
        source_id: str,
        *,
        total_bytes: int | None = None,
    ) -> UploadSession:
        """Open a session for one archive.

        A declared size larger than this importer accepts is refused here, before the
        first byte is sent, rather than after a quarter of an hour of uploading.

        Any earlier session this tenant still had open for the same connector is
        dropped: a user who picks a second file has abandoned the first, and its spool
        file would otherwise sit on disk until the sweep noticed.
        """
        if total_bytes is not None and total_bytes > self._max_bytes:
            raise SpoolTooLarge(self._max_bytes)

        self.sweep()
        for stale in [
            s
            for s in self._sessions.values()
            if s.tenant_id == tenant_id and s.source_id == source_id
        ]:
            self._discard(stale)

        upload_id = secrets.token_urlsafe(24)
        session = UploadSession(
            id=upload_id,
            tenant_id=tenant_id,
            source_id=source_id,
            path=self._root / f"{upload_id}{_SPOOL_SUFFIX}",
            total_bytes=total_bytes,
        )
        session.path.touch(mode=0o600)
        self._sessions[upload_id] = session
        return session

    def session(self, upload_id: str, tenant_id: str) -> UploadSession:
        """The session, if it belongs to this workspace.

        A session belonging to another tenant is reported as unknown rather than as
        forbidden: whether an id exists is not this tenant's business (rule 2).
        """
        session = self._sessions.get(upload_id)
        if session is None or session.tenant_id != tenant_id:
            raise UnknownUpload("No such upload. Start the upload again.")
        return session

    async def append(
        self,
        upload_id: str,
        tenant_id: str,
        *,
        offset: int,
        chunks: AsyncIterator[bytes],
    ) -> UploadSession:
        """Write one part at ``offset``.

        Takes a stream rather than bytes so a part is never held in memory here
        either — it goes from the socket to the spool file as it arrives.

        A transfer that dies mid-part leaves the file truncated back to where it
        began, so the session remains exactly as resumable as it was before.
        """
        session = self.session(upload_id, tenant_id)
        async with session.lock:
            if offset != session.received:
                raise OffsetMismatch(session.received)

            written = 0
            try:
                with session.path.open("ab") as handle:
                    async for chunk in chunks:
                        if session.received + written + len(chunk) > self._max_bytes:
                            raise SpoolTooLarge(self._max_bytes)
                        handle.write(chunk)
                        written += len(chunk)
            except BaseException:
                os.truncate(session.path, session.received)
                raise

            session.received += written
            session.touched = time.monotonic()
            return session

    def finish(self, upload_id: str, tenant_id: str) -> UploadSession:
        """Hand the assembled file over.

        The session leaves the registry and the caller owns the file from here,
        including deleting it — which the import already does, whatever its outcome.
        """
        session = self.session(upload_id, tenant_id)
        del self._sessions[upload_id]
        return session

    def abort(self, upload_id: str, tenant_id: str) -> None:
        """Give up on a session and delete what arrived."""
        self._discard(self.session(upload_id, tenant_id))

    def sweep(self, *, now: float | None = None) -> int:
        """Delete every session that has not been written to within the TTL.

        Returns:
            How many were deleted.
        """
        moment = time.monotonic() if now is None else now
        expired = [s for s in self._sessions.values() if moment - s.touched > self._ttl]
        for session in expired:
            logger.info(
                "Discarding an unfinished upload for tenant %s after %d second(s) of silence (%d byte(s) received).",
                session.tenant_id,
                int(moment - session.touched),
                session.received,
            )
            self._discard(session)
        return len(expired)

    def _discard(self, session: UploadSession) -> None:
        self._sessions.pop(session.id, None)
        session.path.unlink(missing_ok=True)

    def __len__(self) -> int:
        return len(self._sessions)

    def sessions(self) -> Iterable[UploadSession]:
        return tuple(self._sessions.values())
