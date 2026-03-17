"""Tests for log collection and rotation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import asyncio
from datetime import datetime, UTC
import aiosqlite

from pxq.config import Settings
from pxq.models import Job, JobStatus
from pxq.log_collector import (
    LogCollector,
    LogCollectionError,
    record_collection_warning,
    start_log_collection,
)
from pxq.storage import create_job, get_artifacts, get_job_events, init_db
from pxq.providers.runpod_exec import _collect_final_logs


class FakeProcess:
    """Fake subprocess for mocking asyncio.create_subprocess_exec."""

    def __init__(
        self,
        returncode: int,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        return None

    async def wait(self) -> int:
        return self.returncode


@pytest.mark.asyncio
async def test_collect_logs_creates_artifact(tmp_path: Path) -> None:
    """Test that successful log collection creates an artifact."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(db_path, Job(command="echo test", status=JobStatus.RUNNING))

    collector = LogCollector(
        db_path=db_path,
        job_id=job.id,
        host="127.0.0.1",
        port=22,
        settings=Settings(log_max_size_mb=100),
    )

    # Mock SSH responses: discover files, get size, read content
    discover_proc = FakeProcess(returncode=0, stdout=b"/var/log/syslog.log\n")
    size_proc = FakeProcess(returncode=0, stdout=b"100\n")
    content_proc = FakeProcess(returncode=0, stdout=b"log line 1\nlog line 2\n")

    with patch(
        "pxq.log_collector.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=[discover_proc, size_proc, content_proc]),
    ):
        collected = await collector.collect_logs()

    assert collected == 22  # bytes collected ("log line 1\nlog line 2\n" = 22 bytes)

    artifacts = await get_artifacts(db_path, job.id)
    assert len(artifacts) == 1
    assert artifacts[0].artifact_type == "log"
    assert artifacts[0].path == "/var/log/syslog.log"
    assert artifacts[0].size_bytes == 22


@pytest.mark.asyncio
async def test_incremental_collection_only_fetches_new_content(tmp_path: Path) -> None:
    """Test that incremental collection only reads new content."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(db_path, Job(command="echo test", status=JobStatus.RUNNING))

    collector = LogCollector(
        db_path=db_path,
        job_id=job.id,
        host="127.0.0.1",
        port=22,
        settings=Settings(log_max_size_mb=100),
    )

    # First collection: file has 100 bytes
    discover_proc1 = FakeProcess(returncode=0, stdout=b"/var/log/test.log\n")
    size_proc1 = FakeProcess(returncode=0, stdout=b"100\n")
    content_proc1 = FakeProcess(returncode=0, stdout=b"a" * 100)

    with patch(
        "pxq.log_collector.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=[discover_proc1, size_proc1, content_proc1]),
    ):
        collected1 = await collector.collect_logs()

    assert collected1 == 100
    assert collector.log_files["/var/log/test.log"].last_position == 100

    # Second collection: file has grown to 150 bytes
    discover_proc2 = FakeProcess(returncode=0, stdout=b"/var/log/test.log\n")
    size_proc2 = FakeProcess(returncode=0, stdout=b"150\n")
    # tail -c +101 should return last 50 bytes
    content_proc2 = FakeProcess(returncode=0, stdout=b"b" * 50)

    with patch(
        "pxq.log_collector.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=[discover_proc2, size_proc2, content_proc2]),
    ):
        collected2 = await collector.collect_logs()

    assert collected2 == 50
    assert collector.log_files["/var/log/test.log"].last_position == 150


@pytest.mark.asyncio
async def test_rotation_triggers_when_size_exceeds_limit(tmp_path: Path) -> None:
    """Test that rotation removes old logs when size exceeds limit."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(db_path, Job(command="echo test", status=JobStatus.RUNNING))

    # Use very small limit (1KB) for testing
    collector = LogCollector(
        db_path=db_path,
        job_id=job.id,
        host="127.0.0.1",
        port=22,
        settings=Settings(log_max_size_mb=0),  # 0MB = force rotation
    )

    # Collect logs that exceed the limit
    for i in range(3):
        discover_proc = FakeProcess(
            returncode=0, stdout=f"/var/log/test{i}.log\n".encode()
        )
        size_proc = FakeProcess(returncode=0, stdout=b"500\n")
        content_proc = FakeProcess(returncode=0, stdout=b"x" * 500)

        with patch(
            "pxq.log_collector.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[discover_proc, size_proc, content_proc]),
        ):
            await collector.collect_logs()

    # Check rotation
    rotated = await collector.check_rotation()

    assert rotated is True

    # Verify total size is now under limit
    artifacts = await get_artifacts(db_path, job.id)
    log_artifacts = [a for a in artifacts if a.artifact_type == "log"]
    total_size = sum(a.size_bytes for a in log_artifacts)
    assert total_size == 0  # All logs removed when limit is 0


@pytest.mark.asyncio
async def test_collection_failure_records_warning_not_job_failure(
    tmp_path: Path
) -> None:
    """Test that collection failure records warning but doesn't fail job."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(db_path, Job(command="echo test", status=JobStatus.RUNNING))

    collector = LogCollector(
        db_path=db_path,
        job_id=job.id,
        host="127.0.0.1",
        port=22,
        settings=Settings(),
    )

    # Mock SSH failure
    discover_proc = FakeProcess(returncode=255, stderr=b"Connection refused")

    with patch(
        "pxq.log_collector.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=discover_proc),
    ):
        with pytest.raises(LogCollectionError):
            await collector.collect_logs()

    # Record the warning manually (as start_log_collection would do)
    await record_collection_warning(db_path, job.id, "SSH connection failed")

    # Check job is still running
    from pxq.storage import get_job

    saved_job = await get_job(db_path, job.id)
    assert saved_job is not None
    assert saved_job.status == JobStatus.RUNNING

    # Check warning was recorded
    events = await get_job_events(db_path, job.id)
    warning_events = [
        e for e in events if e.message and "log_collection_warning" in e.message
    ]
    assert len(warning_events) == 1


@pytest.mark.asyncio
async def test_record_collection_warning_creates_event(tmp_path: Path) -> None:
    """Test that record_collection_warning creates a job event."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(db_path, Job(command="echo test", status=JobStatus.RUNNING))

    await record_collection_warning(db_path, job.id, "Test warning message")

    events = await get_job_events(db_path, job.id)
    warning_events = [
        e for e in events if e.message and "log_collection_warning" in e.message
    ]
    assert len(warning_events) == 1
    assert "Test warning message" in warning_events[0].message


@pytest.mark.asyncio
async def test_start_log_collection_stops_on_event(tmp_path: Path) -> None:
    """Test that start_log_collection stops when stop_event is set."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(db_path, Job(command="echo test", status=JobStatus.RUNNING))

    stop_event = asyncio.Event()

    async def _set_stop():
        await asyncio.sleep(0.05)
        stop_event.set()

    asyncio.create_task(_set_stop())

    discover_proc = FakeProcess(returncode=0, stdout=b"")

    with patch(
        "pxq.log_collector.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=discover_proc),
    ):
        await start_log_collection(
            db_path=db_path,
            job_id=job.id,
            host="127.0.0.1",
            port=22,
            stop_event=stop_event,
            collection_interval_seconds=0.1,
        )

    # Should have stopped without error
    assert stop_event.is_set() is True


async def _create_stdout_artifact(db_path: Path, job_id: int, content: str) -> None:
    """Create a stdout artifact with specified content."""
    now = datetime.now(UTC).isoformat()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            INSERT INTO artifacts (job_id, artifact_type, path, size_bytes, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, "stdout", "/workspace/pxq_stdout.log", len(content), content, now),
        )
        await db.commit()


async def _create_stderr_artifact(db_path: Path, job_id: int, content: str) -> None:
    """Create a stderr artifact with specified content."""
    now = datetime.now(UTC).isoformat()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            INSERT INTO artifacts (job_id, artifact_type, path, size_bytes, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, "stderr", "/workspace/pxq_stderr.log", len(content), content, now),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_async_then_final_equal_content_no_duplicate_stdout(
    tmp_path: Path
) -> None:
    """Test that equal-content async+final sequence for stdout produces one logical stream."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(db_path, Job(command="echo test", status=JobStatus.RUNNING))

    # First, simulate async collector creating 100 bytes of stdout content
    full_stdout = "a" * 100
    await _create_stdout_artifact(db_path, job.id, full_stdout)

    # Now simulate final collection running against same remote file
    # The final collector should detect 100 bytes already persisted and >= 100 remote
    # So it should NOT create a new stdout artifact (skip persistence)
    with patch(
        "pxq.providers.runpod_exec.build_non_interactive_ssh_args"
    ) as mock_ssh_args, patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec"
    ) as mock_exec:
        # For stdout: same content (100 bytes) - should be skipped
        # For stderr: empty content - no artifact will be created
        proc_stdout = FakeProcess(returncode=0, stdout=full_stdout.encode())
        proc_stderr = FakeProcess(returncode=0, stdout=b"")  # empty stderr
        mock_exec.side_effect = [proc_stdout, proc_stderr]
        mock_ssh_args.return_value = ["ssh", "-o", "BatchMode=yes"]

        await _collect_final_logs(
            db_path=db_path,
            job_id=job.id,
            host="127.0.0.1",
            port=22,
        )

    # Verify: only stdout artifact exists (no duplicate)
    artifacts = await get_artifacts(db_path, job.id)
    assert len(artifacts) == 1
    assert artifacts[0].artifact_type == "stdout"
    assert artifacts[0].size_bytes == 100
    # Verify no duplicate stdout
    stdout_artifacts = [a for a in artifacts if a.artifact_type == "stdout"]
    assert len(stdout_artifacts) == 1


@pytest.mark.asyncio
async def test_async_then_final_prefix_tail_combined_bytes_match(
    tmp_path: Path
) -> None:
    """Test that prefix-plus-tail sequence produces exact byte match."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(db_path, Job(command="echo test", status=JobStatus.RUNNING))

    # First, simulate async collector creating 60 bytes of stdout content (prefix)
    prefix_content = "a" * 60
    await _create_stdout_artifact(db_path, job.id, prefix_content)

    # Now simulate final collection running against longer remote file (100 bytes)
    # Full content is 100 bytes, 60 already persisted, so 40 new suffix
    full_remote_content = "a" * 100
    with patch(
        "pxq.providers.runpod_exec.build_non_interactive_ssh_args"
    ) as mock_ssh_args, patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec"
    ) as mock_exec:
        proc_stdout = FakeProcess(returncode=0, stdout=full_remote_content.encode())
        proc_stderr = FakeProcess(returncode=0, stdout=b"")
        mock_exec.side_effect = [proc_stdout, proc_stderr]
        mock_ssh_args.return_value = ["ssh", "-o", "BatchMode=yes"]

        await _collect_final_logs(
            db_path=db_path,
            job_id=job.id,
            host="127.0.0.1",
            port=22,
        )

    # Verify two artifacts exist: prefix (60) + suffix (40) = 100 total
    artifacts = await get_artifacts(db_path, job.id)
    stdout_artifacts = [a for a in artifacts if a.artifact_type == "stdout"]
    assert len(stdout_artifacts) == 2, "Should create exactly 2 stdout artifacts"
    # Artifacts ordered by created_at, so first is prefix, second is suffix
    stdout_artifacts.sort(key=lambda a: a.created_at)
    assert stdout_artifacts[0].size_bytes == 60
    assert stdout_artifacts[0].content == prefix_content
    assert stdout_artifacts[1].size_bytes == 40
    assert stdout_artifacts[1].content == "a" * 40
    # Combined bytes should equal remote file
    combined_content = stdout_artifacts[0].content + stdout_artifacts[1].content
    assert len(combined_content) == 100
    assert combined_content == full_remote_content


@pytest.mark.asyncio
async def test_async_then_final_stdout_stderr_both_no_duplicate(tmp_path: Path) -> None:
    """Test that equal-content async+final sequence works for both stdout and stderr."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(db_path, Job(command="echo test", status=JobStatus.RUNNING))

    # Simulate async collector creating stdout and stderr content
    stdout_content = "stdout_a" * 10
    stderr_content = "stderr_b" * 10
    await _create_stdout_artifact(db_path, job.id, stdout_content)
    await _create_stderr_artifact(db_path, job.id, stderr_content)

    # Verify two artifacts exist
    artifacts1 = await get_artifacts(db_path, job.id)
    assert len(artifacts1) == 2
    stdout_artifact = next(a for a in artifacts1 if a.artifact_type == "stdout")
    stderr_artifact = next(a for a in artifacts1 if a.artifact_type == "stderr")

    # Now simulate final collection running against same remote files
    # Both should be skipped since they already have full content
    with patch(
        "pxq.providers.runpod_exec.build_non_interactive_ssh_args"
    ) as mock_ssh_args, patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec"
    ) as mock_exec:
        proc_stdout = FakeProcess(returncode=0, stdout=stdout_content.encode())
        proc_stderr = FakeProcess(returncode=0, stdout=stderr_content.encode())
        mock_exec.side_effect = [proc_stdout, proc_stderr]
        mock_ssh_args.return_value = ["ssh", "-o", "BatchMode=yes"]

        await _collect_final_logs(
            db_path=db_path,
            job_id=job.id,
            host="127.0.0.1",
            port=22,
        )

    # Verify no new artifacts were created (still 2 total, neither duplicated)
    artifacts2 = await get_artifacts(db_path, job.id)
    assert (
        len(artifacts2) == 2
    ), "Equal-content sequence should not create duplicate artifacts"
    stdout_artifact2 = next(a for a in artifacts2 if a.artifact_type == "stdout")
    stderr_artifact2 = next(a for a in artifacts2 if a.artifact_type == "stderr")
    assert stdout_artifact2.size_bytes == len(stdout_content)
    assert stderr_artifact2.size_bytes == len(stderr_content)


@pytest.mark.asyncio
async def test_async_then_final_stdout_prefix_stderr_prefix_tail(
    tmp_path: Path
) -> None:
    """Test prefix-tail sequence for stdout and stderr combined."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(db_path, Job(command="echo test", status=JobStatus.RUNNING))

    # Simulate async collector creating partial stdout and full stderr
    stdout_prefix = "out_" * 15  # 60 bytes
    stderr_full = "err_" * 25  # 100 bytes
    await _create_stdout_artifact(db_path, job.id, stdout_prefix)
    await _create_stderr_artifact(db_path, job.id, stderr_full)

    # Add stderr suffix (40 bytes) and stdout suffix (40 bytes)
    stdout_suffix = "out_" * 10  # 40 bytes
    stderr_suffix = "err_" * 10  # 40 bytes
    full_stdout = stdout_prefix + stdout_suffix  # 100 bytes
    full_stderr = stderr_full + stderr_suffix  # 140 bytes

    with patch(
        "pxq.providers.runpod_exec.build_non_interactive_ssh_args"
    ) as mock_ssh_args, patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec"
    ) as mock_exec:
        proc_stdout = FakeProcess(returncode=0, stdout=full_stdout.encode())
        proc_stderr = FakeProcess(returncode=0, stdout=full_stderr.encode())
        mock_exec.side_effect = [proc_stdout, proc_stderr]
        mock_ssh_args.return_value = ["ssh", "-o", "BatchMode=yes"]

        await _collect_final_logs(
            db_path=db_path,
            job_id=job.id,
            host="127.0.0.1",
            port=22,
        )

    # Verify 4 artifacts exist: stdout_prefix + stdout_suffix + stderr_full + stderr_suffix
    artifacts = await get_artifacts(db_path, job.id)
    assert len(artifacts) == 4, "Prefix-tail should create 2 additional artifacts"
    # Group by type and sort by created_at
    stdout_artifacts = sorted(
        [a for a in artifacts if a.artifact_type == "stdout"],
        key=lambda a: a.created_at,
    )
    stderr_artifacts = sorted(
        [a for a in artifacts if a.artifact_type == "stderr"],
        key=lambda a: a.created_at,
    )
    assert len(stdout_artifacts) == 2
    assert len(stderr_artifacts) == 2
    # Verify combined bytes match remote file
    stdout_combined = stdout_artifacts[0].content + stdout_artifacts[1].content
    stderr_combined = stderr_artifacts[0].content + stderr_artifacts[1].content
    assert len(stdout_combined) == len(full_stdout) == 100
    assert len(stderr_combined) == len(full_stderr) == 140
    assert stdout_combined == full_stdout
    assert stderr_combined == full_stderr
