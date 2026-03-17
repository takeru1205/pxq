"""Integration tests for managed job lifecycle from queued to stopped state.

This module tests the complete lifecycle flow of managed jobs:
- queued -> provisioning -> uploading -> running -> succeeded/failed -> stopping -> stopped

Key verification points:
- Managed jobs ALWAYS call stop_pod in both success and failure cases
- Non-managed jobs do NOT call stop_pod
- Provisioning timeout with managed job still attempts stop
- Scheduler integration: scheduler picks up queued job and transitions to provisioning
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pxq.config import Settings
from pxq.models import Job, JobStatus
from pxq.providers.runpod_client import PodMachine, PodResponse, PodStatus, RunPodClient
from pxq.providers.runpod_exec import run_job_on_pod
from pxq.providers.runpod_provider import (
    ProvisioningTimeoutError,
    handle_provisioning_timeout,
    wait_for_pod_ready,
)
from pxq.scheduler import Scheduler
from pxq.storage import create_job, get_job, get_job_events, init_db


class FakeProcess:
    """Mock subprocess for SSH/rsync operations."""

    def __init__(
        self,
        returncode: int,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        # Accept input argument for stdin piping (ignored in mock)
        return self._stdout, self._stderr

    def kill(self) -> None:
        return None

    async def wait(self) -> int:
        return self.returncode


def _mock_subprocesses_for_success() -> list[FakeProcess]:
    """Create mock processes for successful job execution.

    Returns mocks in call order:
    1. mkdir (upload_directory)
    2. local tar (upload_directory)
    3. remote tar (upload_directory)
    4. SSH wrapped command (execute_remote_command)
    5-10. Exit code polling (6 calls: 5 not-found, 1 found with exit code)
    11-12. Log collection (2 calls: stdout, stderr)
    """
    return [
        FakeProcess(returncode=0),  # mkdir
        FakeProcess(returncode=0),  # local tar
        FakeProcess(returncode=0),  # remote tar
        FakeProcess(returncode=0),  # SSH wrapped command
        FakeProcess(returncode=1),  # polling - not done
        FakeProcess(returncode=1),  # polling - not done
        FakeProcess(returncode=1),  # polling - not done
        FakeProcess(returncode=1),  # polling - not done
        FakeProcess(returncode=1),  # polling - not done
        FakeProcess(returncode=0, stdout=b"0"),  # polling - done, exit code 0
        FakeProcess(returncode=1),  # log collection stdout
        FakeProcess(returncode=1),  # log collection stderr
    ]


def _mock_subprocesses_for_failure(
    failure_stage: str = "exec",
    exit_code: int = 42,
) -> list[FakeProcess]:
    """Create mock processes for failed job execution.

    Args:
        failure_stage: "upload" or "exec"
        exit_code: Exit code for command failure
    """
    if failure_stage == "upload":
        return [
            FakeProcess(returncode=0),  # mkdir
            FakeProcess(returncode=0),  # local tar
            FakeProcess(returncode=1, stderr=b"upload failed"),  # remote tar fails
        ]
    else:  # exec failure
        return [
            FakeProcess(returncode=0),  # mkdir
            FakeProcess(returncode=0),  # local tar
            FakeProcess(returncode=0),  # remote tar
            FakeProcess(returncode=0),  # SSH wrapped command
            FakeProcess(returncode=1),  # polling - not done
            FakeProcess(returncode=1),  # polling - not done
            FakeProcess(returncode=1),  # polling - not done
            FakeProcess(returncode=1),  # polling - not done
            FakeProcess(returncode=1),  # polling - not done
            FakeProcess(returncode=0, stdout=str(exit_code).encode()),  # polling - done
            FakeProcess(returncode=1),  # log collection stdout
            FakeProcess(returncode=1),  # log collection stderr
        ]


def _pod_response(
    pod_id: str = "pod-123",
    status: PodStatus = PodStatus.RUNNING,
    public_ip: str = "127.0.0.1",
    port: int = 22022,
) -> PodResponse:
    """Create a mock PodResponse for testing."""
    return PodResponse(
        id=pod_id,
        status=status,
        machine=PodMachine(public_ip=public_ip, port=port),
        runtime={
            "ports": [
                {
                    "isIpPublic": True,
                    "privatePort": 22,
                    "publicPort": port,
                    "ip": public_ip,
                }
            ]
        },
    )


# =============================================================================
# Scheduler Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_scheduler_picks_up_queued_job(tmp_path: Path) -> None:
    """Verify scheduler picks up queued job and transitions to provisioning."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    # Create a queued job
    job = await create_job(
        db_path,
        Job(
            command="echo test",
            status=JobStatus.QUEUED,
            managed=True,
        ),
    )

    scheduler = Scheduler(db_path, Settings(max_parallelism=1))
    started_job = await scheduler.start_next_job()

    assert started_job is not None
    assert started_job.id == job.id
    assert started_job.status == JobStatus.PROVISIONING

    # Verify the job was updated in the database
    assert job.id is not None
    saved_job = await get_job(db_path, job.id)
    assert saved_job is not None
    assert saved_job.status == JobStatus.PROVISIONING


@pytest.mark.asyncio
async def test_scheduler_respects_max_parallelism(tmp_path: Path) -> None:
    """Verify scheduler respects max_parallelism setting."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    # Create multiple queued jobs
    for i in range(5):
        await create_job(
            db_path,
            Job(
                command=f"echo test{i}",
                status=JobStatus.QUEUED,
            ),
        )

    # Create jobs in running states to fill capacity
    await create_job(
        db_path,
        Job(
            command="running job 1",
            status=JobStatus.RUNNING,
        ),
    )

    scheduler = Scheduler(db_path, Settings(max_parallelism=1))

    # Should not start any job since capacity is full
    started_job = await scheduler.start_next_job()
    assert started_job is None


@pytest.mark.asyncio
async def test_scheduler_tick_starts_multiple_jobs(tmp_path: Path) -> None:
    """Verify scheduler.tick() starts multiple jobs when capacity allows."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    # Create multiple queued jobs
    for i in range(3):
        await create_job(
            db_path,
            Job(
                command=f"echo test{i}",
                status=JobStatus.QUEUED,
            ),
        )

    scheduler = Scheduler(db_path, Settings(max_parallelism=3))
    started_jobs = await scheduler.tick()

    assert len(started_jobs) == 3
    for job in started_jobs:
        assert job.status == JobStatus.PROVISIONING


# =============================================================================
# Full Lifecycle Tests - Success Path
# =============================================================================


@pytest.mark.asyncio
async def test_managed_lifecycle_success_full_flow_stop_mode_contract(
    tmp_path: Path,
) -> None:
    """Test complete managed lifecycle: queued -> provisioning -> uploading -> running -> succeeded -> stopping -> succeeded."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    # Start with a job in PROVISIONING state (simulating scheduler picked it up)
    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'print(\"success\")'",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id="pod-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.delete_pod.return_value = None  # 204 response

    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=_mock_subprocesses_for_success()),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    # Verify final state - auto-cleanup preserves SUCCEEDED status
    assert result.status == JobStatus.SUCCEEDED
    assert result.exit_code == 0

    # Verify database state
    assert job.id is not None
    saved_job = await get_job(db_path, job.id)
    assert saved_job is not None
    assert saved_job.status == JobStatus.SUCCEEDED
    assert saved_job.exit_code == 0

    # Verify complete lifecycle sequence
    events = await get_job_events(db_path, job.id)
    status_sequence = [event.to_status for event in events]

    assert JobStatus.PROVISIONING in status_sequence
    assert JobStatus.UPLOADING in status_sequence
    assert JobStatus.RUNNING in status_sequence
    assert status_sequence.count(JobStatus.SUCCEEDED) >= 2
    assert JobStatus.STOPPING in status_sequence
    assert status_sequence[-1] == JobStatus.SUCCEEDED

    # Verify delete_pod was called for managed job auto-cleanup
    runpod_client.delete_pod.assert_awaited_once_with("pod-123")


@pytest.mark.asyncio
async def test_managed_lifecycle_with_scheduler_integration(tmp_path: Path) -> None:
    """Test lifecycle starting from QUEUED state with scheduler integration."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    # Create job in QUEUED state
    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'print(\"test\")'",
            status=JobStatus.QUEUED,
            managed=True,
            workdir=str(tmp_path),
        ),
    )

    # Scheduler picks up the job
    scheduler = Scheduler(db_path, Settings(max_parallelism=1))
    started_job = await scheduler.start_next_job()
    assert started_job is not None
    assert started_job.status == JobStatus.PROVISIONING

    # Simulate pod provisioning
    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.create_pod.return_value = _pod_response(pod_id="pod-456")
    runpod_client.get_pod.return_value = _pod_response(pod_id="pod-456")
    runpod_client.delete_pod.return_value = None  # 204 response

    # The job is already in PROVISIONING state after scheduler picked it up
    started_job.pod_id = "pod-456"

    # Mock SSH subprocess
    upload_proc = FakeProcess(returncode=0)
    exec_proc = FakeProcess(returncode=0)
    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=_mock_subprocesses_for_success()),
    ):
        result = await run_job_on_pod(
            db_path, started_job, _pod_response(pod_id="pod-456"), runpod_client
        )

    # Auto-cleanup preserves SUCCEEDED status
    assert result.status == JobStatus.SUCCEEDED
    runpod_client.delete_pod.assert_awaited_once_with("pod-456")


# =============================================================================
# Full Lifecycle Tests - Failure Paths
# =============================================================================


@pytest.mark.asyncio
async def test_managed_lifecycle_command_failure_stops_pod(tmp_path: Path) -> None:
    """Test managed job with command failure still transitions cleanup with FAILED status preserved."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'import sys; sys.exit(42)'",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id="pod-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.delete_pod.return_value = None  # 204 response

    upload_proc = FakeProcess(returncode=0)
    exec_proc = FakeProcess(returncode=42, stderr=b"command failed with exit code 42")
    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=_mock_subprocesses_for_failure("exec", 42)),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    # Auto-cleanup preserves FAILED status
    assert result.status == JobStatus.FAILED
    assert result.exit_code == 42
    assert "Remote command exited with code 42" in (result.error_message or "")

    assert job.id is not None
    events = await get_job_events(db_path, job.id)
    status_sequence = [event.to_status for event in events]

    assert JobStatus.UPLOADING in status_sequence
    assert JobStatus.RUNNING in status_sequence
    assert JobStatus.FAILED in status_sequence
    assert JobStatus.STOPPING in status_sequence
    assert status_sequence[-1] == JobStatus.FAILED

    runpod_client.delete_pod.assert_awaited_once_with("pod-123")


@pytest.mark.asyncio
async def test_managed_lifecycle_upload_failure_stops_pod(tmp_path: Path) -> None:
    """Test managed job with upload failure still attempts cleanup with FAILED status preserved."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="echo test",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id="pod-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.delete_pod.return_value = None  # 204 response

    upload_proc = FakeProcess(returncode=0)
    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        # SSH failure during command execution (after upload succeeds)
        # Returns: mkdir, local tar, remote tar (upload succeeds), then SSH error
        new=AsyncMock(
            side_effect=_mock_subprocesses_for_success()[:3]
            + [OSError("SSH connection refused")]
        ),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    # Auto-cleanup preserves FAILED status
    assert result.status == JobStatus.FAILED
    assert "SSH" in (result.error_message or "") or "ssh" in (
        result.error_message or ""
    )

    assert job.id is not None
    events = await get_job_events(db_path, job.id)
    status_sequence = [event.to_status for event in events]

    assert JobStatus.UPLOADING in status_sequence
    assert JobStatus.RUNNING in status_sequence
    assert JobStatus.FAILED in status_sequence
    assert JobStatus.STOPPING in status_sequence
    assert status_sequence[-1] == JobStatus.FAILED

    runpod_client.delete_pod.assert_awaited_once_with("pod-123")


@pytest.mark.asyncio
async def test_managed_lifecycle_ssh_exception_stops_pod(tmp_path: Path) -> None:
    """Test managed job with SSH exception still attempts cleanup with FAILED status preserved."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="echo test",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id="pod-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.delete_pod.return_value = None  # 204 response

    upload_proc = FakeProcess(returncode=0)
    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        # SSH failure during command execution (after upload succeeds)
        new=AsyncMock(
            side_effect=_mock_subprocesses_for_success()[:3]
            + [OSError("SSH connection refused")]
        ),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    # Auto-cleanup preserves FAILED status
    assert result.status == JobStatus.FAILED
    assert "SSH" in (result.error_message or "") or "ssh" in (
        result.error_message or ""
    )

    assert job.id is not None
    events = await get_job_events(db_path, job.id)
    status_sequence = [event.to_status for event in events]
    # SSH failure during command execution results in RUNNING -> STOPPING -> FAILED
    assert status_sequence[-3:] == [
        JobStatus.RUNNING,
        JobStatus.STOPPING,
        JobStatus.FAILED,
    ]

    runpod_client.delete_pod.assert_awaited_once_with("pod-123")


# =============================================================================
# Provisioning Timeout Tests
# =============================================================================


@pytest.mark.asyncio
async def test_provisioning_timeout_managed_job_attempts_stop(tmp_path: Path) -> None:
    """Test that provisioning timeout with managed job attempts to stop the pod."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="echo test",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id="pod-timeout",
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.get_pod.return_value = PodResponse(
        id="pod-timeout", status=PodStatus.LAUNCHING
    )
    runpod_client.stop_pod.return_value = PodResponse(
        id="pod-timeout", status=PodStatus.STOPPED
    )

    settings = Settings(provisioning_timeout_minutes=0)  # Immediate timeout

    # Verify wait_for_pod_ready raises timeout
    with pytest.raises(ProvisioningTimeoutError):
        await wait_for_pod_ready(
            runpod_client, "pod-timeout", settings, poll_interval_seconds=10
        )

    # Handle the timeout
    assert job.id is not None
    result = await handle_provisioning_timeout(
        db_path, job.id, "pod-timeout", runpod_client, settings
    )

    assert result.status == JobStatus.FAILED
    assert "did not become ready" in (result.error_message or "")

    # Verify stop was attempted
    runpod_client.stop_pod.assert_awaited_once_with("pod-timeout")

    # Verify event log
    events = await get_job_events(db_path, job.id)
    event_messages = [event.message for event in events if event.message]
    assert "Provisioning timeout" in event_messages


@pytest.mark.asyncio
async def test_provisioning_timeout_stop_failure_is_handled(tmp_path: Path) -> None:
    """Test that stop failure during provisioning timeout is handled gracefully."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="echo test",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id="pod-fail-stop",
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.stop_pod.side_effect = Exception("API error during stop")

    settings = Settings(provisioning_timeout_minutes=15)

    assert job.id is not None
    result = await handle_provisioning_timeout(
        db_path, job.id, "pod-fail-stop", runpod_client, settings
    )

    # Job should still be marked as failed even if stop fails
    assert result.status == JobStatus.FAILED

    # Verify stop was attempted
    runpod_client.stop_pod.assert_awaited_once_with("pod-fail-stop")

    # Verify error was logged
    events = await get_job_events(db_path, job.id)
    event_messages = [event.message for event in events if event.message]
    assert any("Failed to stop pod" in msg for msg in event_messages)


# =============================================================================
# Non-Managed Job Tests
# =============================================================================


@pytest.mark.asyncio
async def test_unmanaged_lifecycle_success_contract_no_cleanup_call(
    tmp_path: Path,
) -> None:
    """Test non-managed job does NOT call stop_pod on success."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'print(\"ok\")'",
            status=JobStatus.PROVISIONING,
            managed=False,  # Non-managed
            pod_id="pod-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)

    upload_proc = FakeProcess(returncode=0)
    exec_proc = FakeProcess(returncode=0)
    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=_mock_subprocesses_for_success()),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    assert result.status == JobStatus.RUNNING
    assert result.exit_code == 0

    # Verify stop_pod was NOT called
    runpod_client.stop_pod.assert_not_awaited()
    runpod_client.terminate_pod.assert_not_awaited()
    runpod_client.delete_pod.assert_not_awaited()

    assert job.id is not None
    events = await get_job_events(db_path, job.id)

    status_sequence = [event.to_status for event in events]
    assert JobStatus.UPLOADING in status_sequence
    assert JobStatus.RUNNING in status_sequence
    assert status_sequence[-1] == JobStatus.RUNNING

    event_messages = [event.message for event in events if event.message]
    assert "Remote command completed; awaiting pxq stop" in event_messages


@pytest.mark.asyncio
async def test_unmanaged_lifecycle_failure_contract_no_cleanup_call(
    tmp_path: Path,
) -> None:
    """Test non-managed job does NOT call stop_pod on failure."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'import sys; sys.exit(1)'",
            status=JobStatus.PROVISIONING,
            managed=False,  # Non-managed
            pod_id="pod-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)

    upload_proc = FakeProcess(returncode=0)
    exec_proc = FakeProcess(returncode=1, stderr=b"error")
    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=_mock_subprocesses_for_failure("exec", 1)),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    assert result.status == JobStatus.RUNNING
    assert result.exit_code == 1

    # Verify stop_pod was NOT called
    runpod_client.stop_pod.assert_not_awaited()
    runpod_client.terminate_pod.assert_not_awaited()
    runpod_client.delete_pod.assert_not_awaited()

    assert job.id is not None
    events = await get_job_events(db_path, job.id)
    event_messages = [event.message for event in events if event.message]
    assert "Remote command failed; awaiting pxq stop" in event_messages


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="Policy contract frozen first: terminate mode behavior not implemented yet"
)
async def test_managed_lifecycle_success_full_flow_terminate_mode_contract(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'print(\"success\")'",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id="pod-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.terminate_pod.return_value = PodResponse(
        id="pod-123", status=PodStatus.TERMINATED
    )

    upload_proc = FakeProcess(returncode=0)
    exec_proc = FakeProcess(returncode=0)
    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=[upload_proc, exec_proc]),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    assert result.status == JobStatus.STOPPED
    runpod_client.terminate_pod.assert_awaited_once_with("pod-123")
    runpod_client.stop_pod.assert_not_awaited()


# =============================================================================
# Edge Cases
# =============================================================================


@pytest.mark.asyncio
async def test_managed_job_without_pod_id_skips_stop(tmp_path: Path) -> None:
    """Test managed job without pod_id skips stop_pod call."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="echo test",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id=None,  # No pod_id
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)

    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=_mock_subprocesses_for_success()),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    assert result.status == JobStatus.SUCCEEDED
    assert result.exit_code == 0
    runpod_client.stop_pod.assert_not_awaited()
    runpod_client.delete_pod.assert_not_awaited()


@pytest.mark.asyncio
async def test_managed_stop_failure_is_recorded(tmp_path: Path) -> None:
    """Test that managed auto-cleanup failure is properly recorded."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="echo test",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id="pod-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.delete_pod.side_effect = Exception("Delete failed")

    upload_proc = FakeProcess(returncode=0)
    exec_proc = FakeProcess(returncode=0)
    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=_mock_subprocesses_for_success()),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    # Cleanup failure results in FAILED status
    assert result.status == JobStatus.FAILED
    assert "Failed to delete pod" in (result.error_message or "")

    # Verify lifecycle includes SUCCEEDED -> STOPPING -> FAILED
    assert job.id is not None
    events = await get_job_events(db_path, job.id)
    status_sequence = [event.to_status for event in events]
    assert status_sequence[-3:] == [
        JobStatus.SUCCEEDED,
        JobStatus.STOPPING,
        JobStatus.FAILED,
    ]


@pytest.mark.asyncio
async def test_managed_job_missing_ssh_host_stops_pod(tmp_path: Path) -> None:
    """Test managed job with missing SSH host still attempts cleanup with FAILED status."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="echo test",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id="pod-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.delete_pod.return_value = None  # 204 response

    # Pod without SSH host
    pod_no_ssh = PodResponse(
        id="pod-123",
        status=PodStatus.RUNNING,
        machine=PodMachine(public_ip=None, port=None),  # No SSH access
    )

    result = await run_job_on_pod(db_path, job, pod_no_ssh, runpod_client)

    # Job fails due to missing SSH host, auto-cleanup succeeds with FAILED preserved
    assert result.status == JobStatus.FAILED
    assert "public SSH host" in (result.error_message or "")

    # Cleanup is still attempted for managed job
    runpod_client.delete_pod.assert_awaited_once_with("pod-123")


# =============================================================================
# State Machine Validation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_lifecycle_state_transitions_are_valid(tmp_path: Path) -> None:
    """Verify all state transitions in the lifecycle are valid per state machine."""
    from pxq.models import VALID_TRANSITIONS, validate_transition

    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job = await create_job(
        db_path,
        Job(
            command="echo test",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id="pod-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.delete_pod.return_value = None  # 204 response

    upload_proc = FakeProcess(returncode=0)
    exec_proc = FakeProcess(returncode=0)
    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=_mock_subprocesses_for_success()),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    # Get all state transitions from events
    assert job.id is not None
    events = await get_job_events(db_path, job.id)

    # Verify each transition is valid
    for event in events:
        if event.from_status is not None:
            # This should not raise if valid
            validate_transition(event.from_status, event.to_status)
            assert event.to_status in VALID_TRANSITIONS.get(event.from_status, set())

    # Auto-cleanup success ends at SUCCEEDED
    assert result.status == JobStatus.SUCCEEDED
