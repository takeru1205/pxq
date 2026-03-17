from __future__ import annotations

from pathlib import Path

import pytest

from pxq.models import Job, JobStatus
from pxq.recovery import RESTART_INTERRUPTION_ERROR, reconcile_jobs
from pxq.storage import create_job, get_job, init_db


@pytest.mark.asyncio
async def test_reconcile_jobs_finds_intermediate_states(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    provisioning = await create_job(
        db_path, Job(command="p", status=JobStatus.PROVISIONING)
    )
    uploading = await create_job(db_path, Job(command="u", status=JobStatus.UPLOADING))
    running = await create_job(db_path, Job(command="r", status=JobStatus.RUNNING))
    await create_job(db_path, Job(command="q", status=JobStatus.QUEUED))

    result = await reconcile_jobs(db_path)
    reconciled_ids = {job.id for job in result.reconciled_jobs if job.id is not None}

    assert result.total_reconciled == 3
    assert provisioning.id is not None
    assert uploading.id is not None
    assert running.id is not None
    assert reconciled_ids == {provisioning.id, uploading.id, running.id}


@pytest.mark.asyncio
async def test_reconcile_jobs_without_pod_are_marked_failed(tmp_path: Path) -> None:
    """Managed jobs without pod_id are orphaned and should be FAILED.

    Non-managed jobs without pod_id stay in their current state (no pod to clean up).
    """
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    # Create managed jobs (should be marked FAILED)
    provisioning_managed = await create_job(
        db_path, Job(command="p", status=JobStatus.PROVISIONING, managed=True)
    )
    uploading_managed = await create_job(
        db_path, Job(command="u", status=JobStatus.UPLOADING, managed=True)
    )
    running_managed = await create_job(
        db_path, Job(command="r", status=JobStatus.RUNNING, managed=True)
    )

    # Create non-managed jobs (should stay in current state)
    provisioning_nonmanaged = await create_job(
        db_path, Job(command="p-nm", status=JobStatus.PROVISIONING, managed=False)
    )
    uploading_nonmanaged = await create_job(
        db_path, Job(command="u-nm", status=JobStatus.UPLOADING, managed=False)
    )
    running_nonmanaged = await create_job(
        db_path, Job(command="r-nm", status=JobStatus.RUNNING, managed=False)
    )

    result = await reconcile_jobs(db_path)

    # Only managed jobs should be marked as failed
    assert result.failed_without_pod == 3
    for job_id in (provisioning_managed.id, uploading_managed.id, running_managed.id):
        assert job_id is not None
        job = await get_job(db_path, job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert job.error_message == RESTART_INTERRUPTION_ERROR

    # Non-managed jobs should stay in their current state
    for job_id in (
        provisioning_nonmanaged.id,
        uploading_nonmanaged.id,
        running_nonmanaged.id,
    ):
        assert job_id is not None
        job = await get_job(db_path, job_id)
        assert job is not None
        # Status should remain unchanged (not FAILED)
        assert job.status != JobStatus.FAILED
        assert job.error_message is None


@pytest.mark.asyncio
async def test_reconcile_jobs_with_pod_are_marked_for_cleanup(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    provisioning = await create_job(
        db_path,
        Job(command="p", status=JobStatus.PROVISIONING, pod_id="pod-1"),
    )
    running = await create_job(
        db_path,
        Job(command="r", status=JobStatus.RUNNING, pod_id="pod-2"),
    )

    result = await reconcile_jobs(db_path)

    assert result.marked_for_cleanup == 2
    assert set(result.cleanup_job_ids) == {provisioning.id, running.id}

    assert provisioning.id is not None
    assert running.id is not None
    provisioning_after = await get_job(db_path, provisioning.id)
    running_after = await get_job(db_path, running.id)
    assert provisioning_after is not None
    assert running_after is not None
    assert provisioning_after.status == JobStatus.PROVISIONING
    assert running_after.status == JobStatus.RUNNING


@pytest.mark.asyncio
async def test_reconcile_jobs_does_not_touch_terminal_states(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    succeeded = await create_job(db_path, Job(command="s", status=JobStatus.SUCCEEDED))
    failed = await create_job(db_path, Job(command="f", status=JobStatus.FAILED))
    stopped = await create_job(db_path, Job(command="x", status=JobStatus.STOPPED))
    cancelled = await create_job(db_path, Job(command="c", status=JobStatus.CANCELLED))

    result = await reconcile_jobs(db_path)

    assert result.total_reconciled == 0

    assert succeeded.id is not None
    assert failed.id is not None
    assert stopped.id is not None
    assert cancelled.id is not None
    succeeded_after = await get_job(db_path, succeeded.id)
    failed_after = await get_job(db_path, failed.id)
    stopped_after = await get_job(db_path, stopped.id)
    cancelled_after = await get_job(db_path, cancelled.id)

    assert succeeded_after is not None
    assert failed_after is not None
    assert stopped_after is not None
    assert cancelled_after is not None

    assert succeeded_after.status == JobStatus.SUCCEEDED
    assert failed_after.status == JobStatus.FAILED
    assert stopped_after.status == JobStatus.STOPPED
    assert cancelled_after.status == JobStatus.CANCELLED


@pytest.mark.asyncio
async def test_reconcile_jobs_skips_running_with_exit_code(tmp_path: Path) -> None:
    """RUNNING jobs with exit_code set are completion-pending and should be skipped."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    completion_pending = await create_job(
        db_path,
        Job(
            command="cp",
            status=JobStatus.RUNNING,
            pod_id="pod-cp",
            exit_code=0,
        ),
    )
    interrupted = await create_job(
        db_path,
        Job(command="int", status=JobStatus.RUNNING, pod_id="pod-int"),
    )

    assert completion_pending.id is not None
    assert interrupted.id is not None
    completion_pending_id = completion_pending.id
    interrupted_id = interrupted.id

    result = await reconcile_jobs(db_path)

    assert result.skipped_completion_pending == 1
    assert result.marked_for_cleanup == 1
    assert set(result.cleanup_job_ids) == {interrupted_id}

    cp_after = await get_job(db_path, completion_pending_id)
    assert cp_after is not None
    assert cp_after.status == JobStatus.RUNNING
    assert cp_after.exit_code == 0
    assert cp_after.pod_id == "pod-cp"

    int_after = await get_job(db_path, interrupted_id)
    assert int_after is not None
    assert int_after.status == JobStatus.RUNNING


@pytest.mark.asyncio
async def test_reconcile_jobs_skips_failed_completion_pending(tmp_path: Path) -> None:
    """RUNNING jobs with non-zero exit_code are also skipped (failed but awaiting stop)."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    failed_pending = await create_job(
        db_path,
        Job(
            command="fp",
            status=JobStatus.RUNNING,
            pod_id="pod-fp",
            exit_code=1,
            error_message="Command failed",
        ),
    )

    assert failed_pending.id is not None
    failed_pending_id = failed_pending.id

    result = await reconcile_jobs(db_path)

    assert result.skipped_completion_pending == 1
    assert result.marked_for_cleanup == 0
    assert len(result.cleanup_job_ids) == 0

    fp_after = await get_job(db_path, failed_pending_id)
    assert fp_after is not None
    assert fp_after.status == JobStatus.RUNNING
    assert fp_after.exit_code == 1
    assert fp_after.error_message == "Command failed"
