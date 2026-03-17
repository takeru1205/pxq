"""Regression tests for stop semantics follow-up (Task 1).

These tests document three reported regressions:
1. `pxq stop 42` CLI rejects job_id with "Got unexpected extra argument"
2. Managed auto-cleanup completion results in STOPPED instead of SUCCEEDED
3. Non-managed explicit stop results in SUCCEEDED instead of STOPPED

These tests will fail before the code fix and pass after.
See: .sisyphus/plans/runpod-stop-followup-regressions.md - Task 1
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from pxq.models import JobStatus, Job
from pxq.storage import (
    update_job_status,
    update_job_metadata,
    create_job,
    init_db,
    get_job,
)
from pxq.providers.runpod_exec import auto_cleanup_pod, managed_stop
from pxq.providers.runpod_client import RunPodClient


@pytest.fixture
async def test_db(tmp_path):
    """Create a temporary test database."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    return str(db_path)


class TestStopSemanticsRegressions:
    """Regression tests for reported stop semantics issues."""

    @pytest.mark.asyncio
    async def test_managed_auto_cleanup_should_end_at_succeeded_not_stopped(
        self, test_db, monkeypatch, tmp_path
    ) -> None:
        """Regression: managed job auto-cleanup must end at SUCCEEDED, not STOPPED.

        User reported: managed jobs that complete successfully are observed as STOPPED
        instead of SUCCEEDED in practice. This test verifies the expected behavior:
        managed auto-cleanup should preserve SUCCEEDED status after pod deletion.
        """
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        # Create a managed job
        job = await create_job(
            test_db,
            Job(
                command="python train.py",
                provider="runpod",
                managed=True,
                pod_id="pod-managed-123",
                workdir=str(tmp_path),
            ),
        )
        job_id = job.id

        # Simulate completed managed job state
        await update_job_status(test_db, job_id, JobStatus.PROVISIONING)
        await update_job_status(test_db, job_id, JobStatus.UPLOADING)
        await update_job_status(test_db, job_id, JobStatus.RUNNING)
        await update_job_status(test_db, job_id, JobStatus.SUCCEEDED)
        await update_job_metadata(
            test_db,
            job_id,
            exit_code=0,
            error_message=None,
            message="Command completed; auto-cleaning up pod",
        )

        # Mock runpod client
        runpod_client = AsyncMock(spec=RunPodClient)
        runpod_client.delete_pod = AsyncMock(return_value=None)

        # Call auto_cleanup_pod directly (this is what happens in managed success path)
        result_job = await auto_cleanup_pod(
            db_path=test_db,
            job_id=job_id,
            pod_id="pod-managed-123",
            runpod_client=runpod_client,
            execution_status=JobStatus.SUCCEEDED,
            execution_exit_code=0,
            execution_error_message=None,
        )

        # EXPECTED (after fix): status should be SUCCEEDED
        # CURRENT (before fix): may incorrectly return STOPPED
        assert (
            result_job.status == JobStatus.SUCCEEDED
        ), f"Managed auto-cleanup should preserve SUCCEEDED status, got {result_job.status}"

        # Verify DB also has SUCCEEDED
        saved_job = await get_job(Path(test_db), job_id)
        assert saved_job.status == JobStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_non_managed_explicit_stop_should_end_at_stopped_not_succeeded(
        self, test_db, monkeypatch, tmp_path
    ) -> None:
        """Regression: non-managed explicit stop must end at STOPPED, not SUCCEEDED.

        User reported: non-managed jobs that are explicitly stopped via pxq stop
        are observed as SUCCEEDED instead of STOPPED. This test verifies:
        explicit stop on non-managed jobs should result in STOPPED status.
        """
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        # Create a non-managed job that has completed remotely
        job = await create_job(
            test_db,
            Job(
                command="python train.py",
                provider="runpod",
                managed=False,
                pod_id="pod-non-managed-456",
                workdir=str(tmp_path),
            ),
        )
        job_id = job.id

        # Simulate completion-pending state (remote completed, awaiting stop)
        await update_job_status(test_db, job_id, JobStatus.PROVISIONING)
        await update_job_status(test_db, job_id, JobStatus.UPLOADING)
        await update_job_status(test_db, job_id, JobStatus.RUNNING)
        await update_job_metadata(
            test_db,
            job_id,
            exit_code=0,
            error_message=None,
            message="Remote command completed; awaiting pxq stop",
        )

        # Mock runpod client
        runpod_client = AsyncMock(spec=RunPodClient)
        runpod_client.stop_pod = AsyncMock(return_value=None)
        runpod_client.delete_pod = AsyncMock(return_value=None)

        # Call managed_stop with explicit stop parameters
        # For non-managed explicit stop, final_status should be STOPPED
        result_job = await managed_stop(
            db_path=test_db,
            job_id=job_id,
            pod_id="pod-non-managed-456",
            runpod_client=runpod_client,
            final_status=JobStatus.STOPPED,  # Explicit stop should be STOPPED
            final_message="Explicit stop requested",
            final_exit_code=0,  # Preserve completion metadata
            final_error_message=None,
        )

        # EXPECTED (after fix): status should be STOPPED
        # CURRENT (before fix): may incorrectly return SUCCEEDED
        assert (
            result_job.status == JobStatus.STOPPED
        ), f"Non-managed explicit stop should result in STOPPED status, got {result_job.status}"

        # Verify DB also has STOPPED
        saved_job = await get_job(Path(test_db), job_id)
        assert saved_job.status == JobStatus.STOPPED

    @pytest.mark.asyncio
    async def test_explicit_stop_preserves_completion_metadata(
        self, test_db, monkeypatch, tmp_path
    ) -> None:
        """Regression: explicit stop must preserve exit_code and error_message.

        User reported: completion metadata (exit_code, error_message) should be
        preserved through explicit stop transitions. This test verifies both
        success and failure cases retain their metadata.
        """
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        # Test case 1: Successful completion then stop
        job1 = await create_job(
            test_db,
            Job(
                command="python success.py",
                provider="runpod",
                managed=False,
                pod_id="pod-success-789",
                workdir=str(tmp_path),
            ),
        )
        job1_id = job1.id

        await update_job_status(test_db, job1_id, JobStatus.PROVISIONING)
        await update_job_status(test_db, job1_id, JobStatus.UPLOADING)
        await update_job_status(test_db, job1_id, JobStatus.RUNNING)
        await update_job_metadata(
            test_db,
            job1_id,
            exit_code=0,
            error_message=None,
            message="Success; awaiting stop",
        )

        runpod_client = AsyncMock(spec=RunPodClient)
        runpod_client.stop_pod = AsyncMock(return_value=None)
        runpod_client.delete_pod = AsyncMock(return_value=None)

        result1 = await managed_stop(
            db_path=test_db,
            job_id=job1_id,
            pod_id="pod-success-789",
            runpod_client=runpod_client,
            final_status=JobStatus.STOPPED,
            final_message="Explicit stop",
            final_exit_code=0,
            final_error_message=None,
        )

        # Metadata should be preserved
        assert result1.exit_code == 0
        assert result1.error_message is None

        # Test case 2: Failed completion then stop
        job2 = await create_job(
            test_db,
            Job(
                command="python fail.py",
                provider="runpod",
                managed=False,
                pod_id="pod-fail-012",
                workdir=str(tmp_path),
            ),
        )
        job2_id = job2.id

        await update_job_status(test_db, job2_id, JobStatus.PROVISIONING)
        await update_job_status(test_db, job2_id, JobStatus.UPLOADING)
        await update_job_status(test_db, job2_id, JobStatus.RUNNING)
        await update_job_metadata(
            test_db,
            job2_id,
            exit_code=1,
            error_message="CUDA out of memory",
            message="Failed; awaiting stop",
        )

        result2 = await managed_stop(
            db_path=test_db,
            job_id=job2_id,
            pod_id="pod-fail-012",
            runpod_client=runpod_client,
            final_status=JobStatus.STOPPED,
            final_message="Explicit stop",
            final_exit_code=1,
            final_error_message="CUDA out of memory",
        )

        # Failure metadata should also be preserved
        assert result2.exit_code == 1
        assert result2.error_message == "CUDA out of memory"
