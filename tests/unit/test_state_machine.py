"""Tests for state machine and storage operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from pxq.models import (
    InvalidStateTransitionError,
    Job,
    JobStatus,
    validate_transition,
)
from pxq.storage import (
    create_job,
    get_job,
    get_job_events,
    init_db,
    list_jobs,
    update_job_metadata,
    update_job_status,
)


class TestStateTransitions:
    """Test state transition validation."""

    def test_queued_can_transition_to_provisioning(self) -> None:
        validate_transition(JobStatus.QUEUED, JobStatus.PROVISIONING)

    def test_queued_can_transition_to_cancelled(self) -> None:
        validate_transition(JobStatus.QUEUED, JobStatus.CANCELLED)

    def test_provisioning_can_transition_to_uploading(self) -> None:
        validate_transition(JobStatus.PROVISIONING, JobStatus.UPLOADING)

    def test_provisioning_can_transition_to_failed(self) -> None:
        validate_transition(JobStatus.PROVISIONING, JobStatus.FAILED)

    def test_provisioning_can_transition_to_cancelled(self) -> None:
        validate_transition(JobStatus.PROVISIONING, JobStatus.CANCELLED)

    def test_uploading_can_transition_to_running(self) -> None:
        validate_transition(JobStatus.UPLOADING, JobStatus.RUNNING)

    def test_uploading_can_transition_to_failed(self) -> None:
        validate_transition(JobStatus.UPLOADING, JobStatus.FAILED)

    def test_uploading_can_transition_to_cancelled(self) -> None:
        validate_transition(JobStatus.UPLOADING, JobStatus.CANCELLED)

    def test_running_can_transition_to_succeeded(self) -> None:
        validate_transition(JobStatus.RUNNING, JobStatus.SUCCEEDED)

    def test_running_can_transition_to_failed(self) -> None:
        validate_transition(JobStatus.RUNNING, JobStatus.FAILED)

    def test_running_can_transition_to_stopping(self) -> None:
        validate_transition(JobStatus.RUNNING, JobStatus.STOPPING)

    def test_running_can_transition_to_cancelled(self) -> None:
        validate_transition(JobStatus.RUNNING, JobStatus.CANCELLED)

    def test_succeeded_can_transition_to_stopping(self) -> None:
        validate_transition(JobStatus.SUCCEEDED, JobStatus.STOPPING)

    def test_failed_can_transition_to_stopping(self) -> None:
        validate_transition(JobStatus.FAILED, JobStatus.STOPPING)

    def test_stopping_can_transition_to_stopped(self) -> None:
        validate_transition(JobStatus.STOPPING, JobStatus.STOPPED)

    def test_stopping_can_transition_to_failed(self) -> None:
        validate_transition(JobStatus.STOPPING, JobStatus.FAILED)

    def test_queued_cannot_transition_to_running(self) -> None:
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            validate_transition(JobStatus.QUEUED, JobStatus.RUNNING)
        assert "queued -> running" in str(exc_info.value)

    def test_queued_cannot_transition_to_succeeded(self) -> None:
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(JobStatus.QUEUED, JobStatus.SUCCEEDED)

    def test_stopped_is_terminal(self) -> None:
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(JobStatus.STOPPED, JobStatus.QUEUED)

    def test_cancelled_is_terminal(self) -> None:
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(JobStatus.CANCELLED, JobStatus.QUEUED)

    def test_succeeded_cannot_transition_to_running(self) -> None:
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(JobStatus.SUCCEEDED, JobStatus.RUNNING)

    def test_failed_cannot_transition_to_running(self) -> None:
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(JobStatus.FAILED, JobStatus.RUNNING)


class TestStorage:
    """Test storage operations."""

    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)
        assert db_path.exists()

    @pytest.mark.asyncio
    async def test_init_db_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)
        await init_db(db_path)
        assert db_path.exists()

    @pytest.mark.asyncio
    async def test_create_job(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = Job(command="echo hello")
        created = await create_job(db_path, job)

        assert created.id is not None
        assert created.command == "echo hello"
        assert created.status == JobStatus.QUEUED

    @pytest.mark.asyncio
    async def test_get_job(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = Job(command="echo hello")
        created = await create_job(db_path, job)

        retrieved = await get_job(db_path, created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.command == "echo hello"

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        retrieved = await get_job(db_path, 999)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_list_jobs_excludes_terminal_by_default(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job1 = await create_job(db_path, Job(command="echo 1"))
        job2 = await create_job(db_path, Job(command="echo 2"))
        job3 = await create_job(db_path, Job(command="echo 3"))

        # Transition job2 to succeeded through valid path
        await update_job_status(db_path, job2.id, JobStatus.PROVISIONING)
        await update_job_status(db_path, job2.id, JobStatus.UPLOADING)
        await update_job_status(db_path, job2.id, JobStatus.RUNNING)
        await update_job_status(db_path, job2.id, JobStatus.SUCCEEDED)

        # Transition job3 to failed through valid path
        await update_job_status(db_path, job3.id, JobStatus.PROVISIONING)
        await update_job_status(db_path, job3.id, JobStatus.FAILED)

        jobs = await list_jobs(db_path)
        assert len(jobs) == 1
        assert jobs[0].id == job1.id

    @pytest.mark.asyncio
    async def test_list_jobs_include_all(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        await create_job(db_path, Job(command="echo 1"))
        job2 = await create_job(db_path, Job(command="echo 2"))

        # Transition job2 to succeeded through valid path
        await update_job_status(db_path, job2.id, JobStatus.PROVISIONING)
        await update_job_status(db_path, job2.id, JobStatus.UPLOADING)
        await update_job_status(db_path, job2.id, JobStatus.RUNNING)
        await update_job_status(db_path, job2.id, JobStatus.SUCCEEDED)

        jobs = await list_jobs(db_path, include_all=True)
        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_list_jobs_filter_by_status(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job1 = await create_job(db_path, Job(command="echo 1"))
        job2 = await create_job(db_path, Job(command="echo 2"))
        await update_job_status(db_path, job1.id, JobStatus.PROVISIONING)

        jobs = await list_jobs(db_path, status=JobStatus.QUEUED)
        assert len(jobs) == 1
        assert jobs[0].id == job2.id


class TestStorageStateTransitions:
    """Test state transitions through storage operations."""

    @pytest.mark.asyncio
    async def test_valid_transition_succeeds(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(db_path, Job(command="echo hello"))
        updated = await update_job_status(db_path, job.id, JobStatus.PROVISIONING)

        assert updated.status == JobStatus.PROVISIONING

    @pytest.mark.asyncio
    async def test_invalid_transition_raises_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(db_path, Job(command="echo hello"))

        with pytest.raises(InvalidStateTransitionError):
            await update_job_status(db_path, job.id, JobStatus.RUNNING)

    @pytest.mark.asyncio
    async def test_transition_creates_event(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(db_path, Job(command="echo hello"))
        await update_job_status(db_path, job.id, JobStatus.PROVISIONING)

        events = await get_job_events(db_path, job.id)
        assert len(events) == 2

        assert events[0].from_status is None
        assert events[0].to_status == JobStatus.QUEUED

        assert events[1].from_status == JobStatus.QUEUED
        assert events[1].to_status == JobStatus.PROVISIONING

    @pytest.mark.asyncio
    async def test_full_lifecycle_local_job(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(db_path, Job(command="echo hello", provider="local"))

        job = await update_job_status(db_path, job.id, JobStatus.PROVISIONING)
        assert job.status == JobStatus.PROVISIONING

        job = await update_job_status(db_path, job.id, JobStatus.UPLOADING)
        assert job.status == JobStatus.UPLOADING

        job = await update_job_status(db_path, job.id, JobStatus.RUNNING)
        assert job.status == JobStatus.RUNNING
        assert job.started_at is not None

        job = await update_job_status(db_path, job.id, JobStatus.SUCCEEDED, exit_code=0)
        assert job.status == JobStatus.SUCCEEDED
        assert job.exit_code == 0
        assert job.finished_at is not None

    @pytest.mark.asyncio
    async def test_full_lifecycle_managed_runpod_job(self, tmp_path: Path) -> None:
        """Test managed job auto-cleanup: RUNNING -> SUCCEEDED -> STOPPING -> SUCCEEDED."""
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(
            db_path, Job(command="python train.py", provider="runpod", managed=True)
        )

        job = await update_job_status(db_path, job.id, JobStatus.PROVISIONING)
        job = await update_job_status(db_path, job.id, JobStatus.UPLOADING)
        job = await update_job_status(db_path, job.id, JobStatus.RUNNING)
        job = await update_job_status(db_path, job.id, JobStatus.SUCCEEDED, exit_code=0)
        job = await update_job_status(db_path, job.id, JobStatus.STOPPING)
        job = await update_job_status(db_path, job.id, JobStatus.SUCCEEDED)

        assert job.status == JobStatus.SUCCEEDED
        assert job.exit_code == 0

    @pytest.mark.asyncio
    async def test_failed_job_with_managed_stop(self, tmp_path: Path) -> None:
        """Test managed job auto-cleanup: RUNNING -> FAILED -> STOPPING -> FAILED."""
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(
            db_path, Job(command="python train.py", provider="runpod", managed=True)
        )

        job = await update_job_status(db_path, job.id, JobStatus.PROVISIONING)
        job = await update_job_status(db_path, job.id, JobStatus.UPLOADING)
        job = await update_job_status(db_path, job.id, JobStatus.RUNNING)
        job = await update_job_status(
            db_path,
            job.id,
            JobStatus.FAILED,
            exit_code=1,
            error_message="Training failed",
        )
        job = await update_job_status(db_path, job.id, JobStatus.STOPPING)
        job = await update_job_status(db_path, job.id, JobStatus.FAILED)

        assert job.status == JobStatus.FAILED
        assert job.exit_code == 1
        assert job.error_message == "Training failed"

    @pytest.mark.asyncio
    async def test_cancel_from_queued(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(db_path, Job(command="echo hello"))
        job = await update_job_status(db_path, job.id, JobStatus.CANCELLED)

        assert job.status == JobStatus.CANCELLED
        assert job.finished_at is not None

    @pytest.mark.asyncio
    async def test_cancel_from_running(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(db_path, Job(command="echo hello"))
        job = await update_job_status(db_path, job.id, JobStatus.PROVISIONING)
        job = await update_job_status(db_path, job.id, JobStatus.UPLOADING)
        job = await update_job_status(db_path, job.id, JobStatus.RUNNING)
        job = await update_job_status(db_path, job.id, JobStatus.CANCELLED)

        assert job.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_update_nonexistent_job_raises_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        with pytest.raises(ValueError, match="Job 999 not found"):
            await update_job_status(db_path, 999, JobStatus.PROVISIONING)


class TestLocalPidMigration:
    """Test local_pid column migration and roundtrip."""

    @pytest.mark.asyncio
    async def test_local_pid_migration_happy_path(self, tmp_path: Path) -> None:
        """Test that local_pid column is added via ALTER TABLE migration."""
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = Job(command="echo hello", local_pid=12345)
        created = await create_job(db_path, job)

        assert created.id is not None
        assert created.local_pid == 12345

    @pytest.mark.asyncio
    async def test_local_pid_roundtrip(self, tmp_path: Path) -> None:
        """Test that local_pid is preserved through create/get cycle."""
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = Job(command="python train.py", local_pid=98765)
        created = await create_job(db_path, job)

        retrieved = await get_job(db_path, created.id)
        assert retrieved is not None
        assert retrieved.local_pid == 98765

    @pytest.mark.asyncio
    async def test_local_pid_none_by_default(self, tmp_path: Path) -> None:
        """Test that local_pid is None when not specified."""
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = Job(command="echo hello")
        created = await create_job(db_path, job)

        assert created.local_pid is None

    @pytest.mark.asyncio
    async def test_local_pid_update(self, tmp_path: Path) -> None:
        """Test that local_pid can be updated via update_job_status."""
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(db_path, Job(command="echo hello"))
        assert job.local_pid is None

        # Update with local_pid when transitioning to RUNNING
        job = await update_job_status(
            db_path, job.id, JobStatus.PROVISIONING, local_pid=54321
        )
        assert job.local_pid == 54321

        # Verify persistence
        retrieved = await get_job(db_path, job.id)
        assert retrieved is not None
        assert retrieved.local_pid == 54321

    @pytest.mark.asyncio
    async def test_local_pid_migration_existing_db(self, tmp_path: Path) -> None:
        """Test that init_db adds local_pid column to existing DB without error."""
        import aiosqlite

        db_path = tmp_path / "test.db"

        # Create a DB with most columns but without local_pid (simulate old schema)
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    provider TEXT NOT NULL DEFAULT 'local',
                    managed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    exit_code INTEGER,
                    pod_id TEXT,
                    workdir TEXT,
                    gpu_type TEXT,
                    cpu_count INTEGER,
                    volume_id TEXT,
                    region TEXT,
                    error_message TEXT,
                    secure_cloud INTEGER,
                    cpu_flavor_ids TEXT,
                    env TEXT,
                    volume_mount_path TEXT,
                    image_name TEXT,
                    template_id TEXT
                )
                """
            )
            await db.commit()

        # Run init_db - should add local_pid column via ALTER TABLE
        await init_db(db_path)

        # Verify we can now create a job with local_pid
        job = Job(command="echo migrated", local_pid=11111)
        created = await create_job(db_path, job)
        assert created.local_pid == 11111


class TestStoppingToSucceededTransition:
    """Test STOPPING -> SUCCEEDED transition for managed job cleanup."""

    @pytest.mark.asyncio
    async def test_stopping_can_transition_to_succeeded(self, tmp_path: Path) -> None:
        validate_transition(JobStatus.STOPPING, JobStatus.SUCCEEDED)

    @pytest.mark.asyncio
    async def test_stopping_to_succeeded_via_storage(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(
            db_path, Job(command="python train.py", provider="runpod", managed=True)
        )

        job = await update_job_status(db_path, job.id, JobStatus.PROVISIONING)
        job = await update_job_status(db_path, job.id, JobStatus.UPLOADING)
        job = await update_job_status(db_path, job.id, JobStatus.RUNNING)
        job = await update_job_status(db_path, job.id, JobStatus.SUCCEEDED, exit_code=0)
        job = await update_job_status(db_path, job.id, JobStatus.STOPPING)
        job = await update_job_status(db_path, job.id, JobStatus.SUCCEEDED)

        assert job.status == JobStatus.SUCCEEDED
        assert job.exit_code == 0

    @pytest.mark.asyncio
    async def test_stopping_to_succeeded_creates_event(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(
            db_path, Job(command="python train.py", provider="runpod", managed=True)
        )

        job = await update_job_status(db_path, job.id, JobStatus.PROVISIONING)
        job = await update_job_status(db_path, job.id, JobStatus.UPLOADING)
        job = await update_job_status(db_path, job.id, JobStatus.RUNNING)
        job = await update_job_status(db_path, job.id, JobStatus.SUCCEEDED, exit_code=0)
        job = await update_job_status(db_path, job.id, JobStatus.STOPPING)
        job = await update_job_status(db_path, job.id, JobStatus.SUCCEEDED)

        events = await get_job_events(db_path, job.id)
        stopping_to_succeeded = [
            e
            for e in events
            if e.from_status == JobStatus.STOPPING
            and e.to_status == JobStatus.SUCCEEDED
        ]
        assert len(stopping_to_succeeded) == 1


class TestUpdateJobMetadata:
    """Test update_job_metadata helper for non-managed jobs."""

    @pytest.mark.asyncio
    async def test_update_metadata_exit_code(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(db_path, Job(command="echo hello"))
        job = await update_job_status(db_path, job.id, JobStatus.PROVISIONING)
        job = await update_job_status(db_path, job.id, JobStatus.UPLOADING)
        job = await update_job_status(db_path, job.id, JobStatus.RUNNING)

        job = await update_job_metadata(db_path, job.id, exit_code=0)

        assert job.status == JobStatus.RUNNING
        assert job.exit_code == 0
        assert job.error_message is None

    @pytest.mark.asyncio
    async def test_update_metadata_error_message(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(db_path, Job(command="echo hello"))
        job = await update_job_status(db_path, job.id, JobStatus.PROVISIONING)
        job = await update_job_status(db_path, job.id, JobStatus.UPLOADING)
        job = await update_job_status(db_path, job.id, JobStatus.RUNNING)

        job = await update_job_metadata(
            db_path, job.id, exit_code=1, error_message="Test error"
        )

        assert job.status == JobStatus.RUNNING
        assert job.exit_code == 1
        assert job.error_message == "Test error"

    @pytest.mark.asyncio
    async def test_update_metadata_creates_event(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(db_path, Job(command="echo hello"))
        job = await update_job_status(db_path, job.id, JobStatus.PROVISIONING)
        job = await update_job_status(db_path, job.id, JobStatus.UPLOADING)
        job = await update_job_status(db_path, job.id, JobStatus.RUNNING)

        await update_job_metadata(db_path, job.id, exit_code=0, message="Job completed")

        events = await get_job_events(db_path, job.id)
        metadata_events = [
            e
            for e in events
            if e.from_status == JobStatus.RUNNING and e.to_status == JobStatus.RUNNING
        ]
        assert len(metadata_events) == 1
        assert metadata_events[0].message == "Job completed"

    @pytest.mark.asyncio
    async def test_update_metadata_updates_timestamp(self, tmp_path: Path) -> None:
        import asyncio

        db_path = tmp_path / "test.db"
        await init_db(db_path)

        job = await create_job(db_path, Job(command="echo hello"))
        job = await update_job_status(db_path, job.id, JobStatus.PROVISIONING)
        job = await update_job_status(db_path, job.id, JobStatus.UPLOADING)
        job = await update_job_status(db_path, job.id, JobStatus.RUNNING)

        original_updated_at = job.updated_at

        await asyncio.sleep(0.01)

        job = await update_job_metadata(db_path, job.id, exit_code=0)

        assert job.updated_at > original_updated_at

    @pytest.mark.asyncio
    async def test_update_metadata_nonexistent_job(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        await init_db(db_path)

        with pytest.raises(ValueError, match="Job 999 not found"):
            await update_job_metadata(db_path, 999, exit_code=0)
