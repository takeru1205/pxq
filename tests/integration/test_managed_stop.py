from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pxq.models import Job, JobStatus
from pxq.providers.runpod_client import PodMachine, PodResponse, PodStatus, RunPodClient
from pxq.providers.runpod_exec import run_job_on_pod
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
    """Create mock processes for successful job execution."""
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


def _mock_subprocesses_for_failure(exit_code: int = 7) -> list[FakeProcess]:
    """Create mock processes for failed job execution."""
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


def _pod_response() -> PodResponse:
    return PodResponse(
        id="pod-123",
        status=PodStatus.RUNNING,
        machine=PodMachine(public_ip="127.0.0.1", port=22022),
    )


@pytest.mark.asyncio
async def test_managed_job_success_stop_mode_contract_transitions_to_stopped(
    tmp_path: Path,
) -> None:
    """Test managed job auto-cleanup preserves SUCCEEDED status."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'print(\"ok\")'",
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

    # Auto-cleanup preserves SUCCEEDED status
    assert result.status == JobStatus.SUCCEEDED
    assert result.exit_code == 0

    assert job.id is not None
    saved_job = await get_job(db_path, job.id)
    assert saved_job is not None
    assert saved_job.status == JobStatus.SUCCEEDED

    events = await get_job_events(db_path, job.id)
    status_sequence = [event.to_status for event in events]

    assert JobStatus.SUCCEEDED in status_sequence
    assert JobStatus.STOPPING in status_sequence
    assert status_sequence[-1] == JobStatus.SUCCEEDED

    runpod_client.delete_pod.assert_awaited_once_with("pod-123")


@pytest.mark.asyncio
async def test_managed_job_failed_command_stop_mode_contract_also_stops_pod(
    tmp_path: Path,
) -> None:
    """Test managed job auto-cleanup preserves FAILED status after command failure."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'import sys; sys.exit(7)'",
            status=JobStatus.PROVISIONING,
            managed=True,
            pod_id="pod-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.delete_pod.return_value = None  # 204 response

    upload_proc = FakeProcess(returncode=0)
    exec_proc = FakeProcess(returncode=7, stderr=b"command failed")
    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=_mock_subprocesses_for_failure(7)),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    # Auto-cleanup preserves FAILED status
    assert result.status == JobStatus.FAILED

    assert job.id is not None
    saved_job = await get_job(db_path, job.id)
    assert saved_job is not None
    assert saved_job.status == JobStatus.FAILED
    assert saved_job.exit_code == 7
    assert saved_job.error_message == "Remote command exited with code 7"

    events = await get_job_events(db_path, job.id)
    status_sequence = [event.to_status for event in events]

    assert JobStatus.UPLOADING in status_sequence
    assert JobStatus.RUNNING in status_sequence
    assert JobStatus.FAILED in status_sequence
    assert JobStatus.STOPPING in status_sequence
    assert status_sequence[-1] == JobStatus.FAILED

    runpod_client.delete_pod.assert_awaited_once_with("pod-123")


@pytest.mark.asyncio
async def test_managed_job_ssh_failure_stop_mode_contract_still_stops_pod(
    tmp_path: Path,
) -> None:
    """Test managed job auto-cleanup preserves FAILED status after SSH failure."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'print(\"x\")'",
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
        new=AsyncMock(
            side_effect=_mock_subprocesses_for_success()[:3]
            + [OSError("ssh unavailable")]
        ),
    ):
        result = await run_job_on_pod(db_path, job, _pod_response(), runpod_client)

    # Auto-cleanup preserves FAILED status
    assert result.status == JobStatus.FAILED

    assert job.id is not None
    saved_job = await get_job(db_path, job.id)
    assert saved_job is not None
    assert saved_job.status == JobStatus.FAILED
    assert "SSH" in (saved_job.error_message or "") or "ssh" in (
        saved_job.error_message or ""
    )

    events = await get_job_events(db_path, job.id)
    status_sequence = [event.to_status for event in events]

    assert JobStatus.UPLOADING in status_sequence
    assert JobStatus.RUNNING in status_sequence
    assert JobStatus.FAILED in status_sequence
    assert JobStatus.STOPPING in status_sequence
    assert status_sequence[-1] == JobStatus.FAILED

    runpod_client.delete_pod.assert_awaited_once_with("pod-123")


@pytest.mark.asyncio
async def test_unmanaged_cleanup_contract_skips_stop_and_terminate(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'print(\"ok\")'",
            status=JobStatus.PROVISIONING,
            managed=False,
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

    assert job.id is not None
    saved_job = await get_job(db_path, job.id)
    assert saved_job is not None
    assert saved_job.status == JobStatus.RUNNING

    events = await get_job_events(db_path, job.id)

    status_sequence = [event.to_status for event in events]
    assert JobStatus.UPLOADING in status_sequence
    assert JobStatus.RUNNING in status_sequence
    assert status_sequence[-1] == JobStatus.RUNNING

    runpod_client.stop_pod.assert_not_awaited()
    runpod_client.terminate_pod.assert_not_awaited()

    event_messages = [event.message for event in events if event.message]
    assert "Remote command completed; awaiting pxq stop" in event_messages


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="Policy contract frozen first: terminate mode behavior not implemented yet"
)
async def test_managed_job_success_terminate_mode_contract_transitions_to_stopped(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'print(\"ok\")'",
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


@pytest.mark.asyncio
async def test_managed_job_explicit_stop_calls_delete_pod(
    tmp_path: Path,
) -> None:
    """Test that explicit pxq stop for managed job calls delete_pod.

    This is a regression guard: managed jobs must continue to call delete_pod
    on explicit stop to prevent resource leaks. The stop path should transition
    the job to STOPPED status and delete the pod.
    """
    from pxq.api.jobs import managed_stop

    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(
        db_path,
        Job(
            command="uv run python -c 'print(\"ok\")'",
            status=JobStatus.RUNNING,
            managed=True,
            pod_id="pod-managed-stop-123",
            workdir=str(tmp_path),
        ),
    )

    runpod_client = AsyncMock(spec=RunPodClient)
    runpod_client.delete_pod.return_value = None

    assert job.id is not None, "Job must have ID"

    with patch(
        "pxq.api.jobs.RunPodClient",
        return_value=runpod_client,
    ):
        result = await managed_stop(
            db_path,
            job.id,
            "pod-managed-stop-123",
            runpod_client,
            final_status=JobStatus.STOPPED,
            final_message="Stop API: Pod deleted",
            final_exit_code=0,
            final_error_message=None,
        )

    assert result.status == JobStatus.STOPPED
    runpod_client.delete_pod.assert_awaited_once_with("pod-managed-stop-123")
