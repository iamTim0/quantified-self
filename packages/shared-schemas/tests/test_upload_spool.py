"""The reassembly rules a chunked upload depends on.

These are the properties that make sending an archive in parts as safe as sending it
in one request: a part lands where it says it does or not at all, a repeat is refused
rather than appended, an interrupted part leaves the session resumable, and no session
is visible to a workspace that does not own it (AGENTS.md rule 2).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from shared_schemas.upload_spool import (
    OffsetMismatch,
    SpoolTooLarge,
    UnknownUpload,
    UploadSpool,
)

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
SOURCE = "33333333-3333-3333-3333-333333333333"


async def stream(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


def spool(tmp_path, **kwargs) -> UploadSpool:
    return UploadSpool(tmp_path / "spool", max_bytes=kwargs.pop("max_bytes", 1024), **kwargs)


@pytest.mark.asyncio
async def test_parts_reassemble_into_the_original_file(tmp_path):
    s = spool(tmp_path)
    session = s.begin(TENANT, SOURCE, total_bytes=9)

    await s.append(session.id, TENANT, offset=0, chunks=stream(b"abc", b"def"))
    await s.append(session.id, TENANT, offset=6, chunks=stream(b"ghi"))

    finished = s.finish(session.id, TENANT)
    assert finished.path.read_bytes() == b"abcdefghi"
    assert finished.complete
    # Handed over: the spool no longer knows about it, the caller owns the file.
    assert len(s) == 0


@pytest.mark.asyncio
async def test_a_repeated_part_is_refused_instead_of_appended_twice(tmp_path):
    """The retry of a request whose response was lost must not corrupt the archive."""
    s = spool(tmp_path)
    session = s.begin(TENANT, SOURCE)
    await s.append(session.id, TENANT, offset=0, chunks=stream(b"abc"))

    with pytest.raises(OffsetMismatch) as refused:
        await s.append(session.id, TENANT, offset=0, chunks=stream(b"abc"))

    assert refused.value.expected == 3
    assert session.path.read_bytes() == b"abc"


@pytest.mark.asyncio
async def test_an_out_of_order_part_reports_the_offset_that_is_wanted(tmp_path):
    s = spool(tmp_path)
    session = s.begin(TENANT, SOURCE)

    with pytest.raises(OffsetMismatch) as refused:
        await s.append(session.id, TENANT, offset=64, chunks=stream(b"abc"))

    assert refused.value.expected == 0
    assert session.received == 0


@pytest.mark.asyncio
async def test_an_interrupted_part_leaves_the_session_resumable(tmp_path):
    """A dropped connection costs one part, not the upload."""
    s = spool(tmp_path)
    session = s.begin(TENANT, SOURCE)
    await s.append(session.id, TENANT, offset=0, chunks=stream(b"abc"))

    async def dies_halfway() -> AsyncIterator[bytes]:
        yield b"de"
        raise ConnectionError("the client went away")

    with pytest.raises(ConnectionError):
        await s.append(session.id, TENANT, offset=3, chunks=dies_halfway())

    # Truncated back to the last complete offset, so resuming from 3 is correct.
    assert session.received == 3
    assert session.path.read_bytes() == b"abc"

    await s.append(session.id, TENANT, offset=3, chunks=stream(b"de"))
    assert s.finish(session.id, TENANT).path.read_bytes() == b"abcde"


@pytest.mark.asyncio
async def test_the_total_limit_is_enforced_while_parts_arrive(tmp_path):
    s = spool(tmp_path, max_bytes=4)
    session = s.begin(TENANT, SOURCE)

    with pytest.raises(SpoolTooLarge):
        await s.append(session.id, TENANT, offset=0, chunks=stream(b"abcdef"))

    assert session.received == 0


def test_a_declared_size_over_the_limit_is_refused_before_anything_is_sent(tmp_path):
    s = spool(tmp_path, max_bytes=4)

    with pytest.raises(SpoolTooLarge):
        s.begin(TENANT, SOURCE, total_bytes=5)


@pytest.mark.asyncio
async def test_a_session_is_invisible_to_another_workspace(tmp_path):
    s = spool(tmp_path)
    session = s.begin(TENANT, SOURCE)

    with pytest.raises(UnknownUpload):
        s.session(session.id, OTHER_TENANT)
    with pytest.raises(UnknownUpload):
        await s.append(session.id, OTHER_TENANT, offset=0, chunks=stream(b"abc"))
    with pytest.raises(UnknownUpload):
        s.finish(session.id, OTHER_TENANT)


@pytest.mark.asyncio
async def test_a_second_file_for_the_same_connector_replaces_the_first(tmp_path):
    """A user who picks another file has abandoned the first; its spool goes with it."""
    s = spool(tmp_path)
    first = s.begin(TENANT, SOURCE)
    await s.append(first.id, TENANT, offset=0, chunks=stream(b"abc"))

    second = s.begin(TENANT, SOURCE)

    assert not first.path.exists()
    assert len(s) == 1
    with pytest.raises(UnknownUpload):
        s.session(first.id, TENANT)
    assert s.session(second.id, TENANT).received == 0


@pytest.mark.asyncio
async def test_a_silent_session_is_swept_off_the_disk(tmp_path):
    """Health data does not wait on disk for an upload nobody is going to finish."""
    s = spool(tmp_path, ttl_seconds=60)
    session = s.begin(TENANT, SOURCE)
    await s.append(session.id, TENANT, offset=0, chunks=stream(b"abc"))

    assert s.sweep(now=session.touched + 59) == 0
    assert session.path.exists()

    assert s.sweep(now=session.touched + 61) == 1
    assert not session.path.exists()
    with pytest.raises(UnknownUpload):
        s.session(session.id, TENANT)


@pytest.mark.asyncio
async def test_a_restart_does_not_leave_health_data_behind(tmp_path):
    s = spool(tmp_path)
    session = s.begin(TENANT, SOURCE)
    await s.append(session.id, TENANT, offset=0, chunks=stream(b"abc"))
    orphan = session.path
    assert orphan.exists()

    # A new process holds no sessions, so what is on disk can only be a leftover.
    spool(tmp_path)

    assert not orphan.exists()


def test_aborting_deletes_what_arrived(tmp_path):
    s = spool(tmp_path)
    session = s.begin(TENANT, SOURCE)

    s.abort(session.id, TENANT)

    assert not session.path.exists()
    with pytest.raises(UnknownUpload):
        s.session(session.id, TENANT)
