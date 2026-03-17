from __future__ import annotations

from pathlib import Path

import pytest

from pxq.config import Settings
from pxq.models import Job, JobStatus
from pxq.scheduler import Scheduler
from pxq.storage import create_job, init_db, list_jobs, update_job_status


@pytest.mark.asyncio
async def test_running_count_tracks_non_terminal_statuses(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    job1 = await create_job(db_path, Job(command="job-1"))
    job2 = await create_job(db_path, Job(command="job-2"))
    job3 = await create_job(db_path, Job(command="job-3"))
    await create_job(db_path, Job(command="job-4"))

    await update_job_status(db_path, job1.id, JobStatus.PROVISIONING)
    await update_job_status(db_path, job2.id, JobStatus.PROVISIONING)
    await update_job_status(db_path, job2.id, JobStatus.UPLOADING)
    await update_job_status(db_path, job3.id, JobStatus.PROVISIONING)
    await update_job_status(db_path, job3.id, JobStatus.UPLOADING)
    await update_job_status(db_path, job3.id, JobStatus.RUNNING)

    scheduler = Scheduler(db_path, settings=Settings(max_parallelism=2))
    assert await scheduler.get_running_count() == 3


@pytest.mark.asyncio
async def test_jobs_remain_queued_when_limit_reached(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    created = []
    for index in range(4):
        job = await create_job(db_path, Job(command=f"job-{index}"))
        created.append(job)

    scheduler = Scheduler(db_path, settings=Settings(max_parallelism=2))
    started = await scheduler.tick()

    assert len(started) == 2
    assert [job.id for job in started] == [created[0].id, created[1].id]
    assert await scheduler.get_running_count() == 2

    queued_jobs = await list_jobs(db_path, status=JobStatus.QUEUED)
    assert len(queued_jobs) == 2
    assert {job.id for job in queued_jobs} == {created[2].id, created[3].id}


@pytest.mark.asyncio
async def test_jobs_start_when_capacity_becomes_available(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    created = []
    for index in range(4):
        job = await create_job(db_path, Job(command=f"job-{index}"))
        created.append(job)

    scheduler = Scheduler(db_path, settings=Settings(max_parallelism=2))

    first_tick_started = await scheduler.tick()
    assert [job.id for job in first_tick_started] == [created[0].id, created[1].id]

    await update_job_status(db_path, created[0].id, JobStatus.FAILED)

    second_tick_started = await scheduler.tick()
    assert len(second_tick_started) == 1
    assert second_tick_started[0].id == created[2].id
    assert await scheduler.get_running_count() == 2

    queued_jobs = await list_jobs(db_path, status=JobStatus.QUEUED)
    assert len(queued_jobs) == 1
    assert queued_jobs[0].id == created[3].id


@pytest.mark.asyncio
async def test_completion_pending_jobs_consume_capacity(tmp_path: Path) -> None:
    """RUNNING jobs with exit_code set should still count toward running capacity."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    queued = await create_job(db_path, Job(command="queued"))
    completion_pending = await create_job(
        db_path,
        Job(
            command="cp",
            status=JobStatus.RUNNING,
            pod_id="pod-cp",
            exit_code=0,
        ),
    )

    assert completion_pending.id is not None

    scheduler = Scheduler(db_path, settings=Settings(max_parallelism=2))

    assert await scheduler.get_running_count() == 1

    started = await scheduler.tick()
    assert len(started) == 1
    assert started[0].id == queued.id
    assert await scheduler.get_running_count() == 2


@pytest.mark.asyncio
async def test_completion_pending_jobs_block_when_capacity_full(tmp_path: Path) -> None:
    """When capacity is full with completion-pending jobs, new jobs stay queued."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    queued = await create_job(db_path, Job(command="queued"))
    cp1 = await create_job(
        db_path,
        Job(command="cp1", status=JobStatus.RUNNING, pod_id="pod-1", exit_code=0),
    )
    cp2 = await create_job(
        db_path,
        Job(command="cp2", status=JobStatus.RUNNING, pod_id="pod-2", exit_code=1),
    )

    scheduler = Scheduler(db_path, settings=Settings(max_parallelism=2))

    assert await scheduler.get_running_count() == 2

    started = await scheduler.tick()
    assert len(started) == 0

    queued_jobs = await list_jobs(db_path, status=JobStatus.QUEUED)
    assert len(queued_jobs) == 1
    assert queued_jobs[0].id == queued.id
