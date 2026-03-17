"""Regression tests for non-managed RunPod job runtime lifecycle.

This module tests the complete runtime flow of non-managed jobs:
- Create non-managed job via API
- Simulate runtime completion (remote command finishes)
- Verify job stays visible in GET /api/jobs (RUNNING is not terminal)
- Call explicit stop via POST /api/jobs/{id}/stop
- Verify job becomes STOPPED with metadata preserved

These tests use real TestClient + real DB state to avoid false positives
from over-mocked helper tests.

See: .sisyphus/plans/nonmanaged-runtime-regression.md - Task 1
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pxq.models import Job, JobStatus
from pxq.server import create_app
from pxq.storage import (
    create_job,
    get_job,
    init_db,
    update_job_metadata,
    update_job_status,
)
from pxq.providers.runpod_client import RunPodClient


@pytest.fixture
def client_with_db(tmp_path):
    """Create a TestClient with a fresh temporary database.

    This fixture sets up a real database and API client for integration testing.
    """
    db_path = tmp_path / "test.db"
    os.environ["PXQ_DB_PATH"] = str(db_path)
    os.environ["PXQ_RUNPOD_API_KEY"] = "test-api-key"

    # Initialize database
    import asyncio

    asyncio.run(init_db(db_path))

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client, str(db_path)


class TestNonManagedRuntimeRegression:
    """Regression tests for non-managed job runtime visibility and stop semantics."""

    @pytest.mark.asyncio
    async def test_non_managed_job_stays_visible_after_completion(
        self, tmp_path, monkeypatch
    ) -> None:
        """Regression: non-managed job must stay visible in GET /api/jobs after completion.

        Bug: non-managed jobs were disappearing from pxq ls default view after
        remote command completion, even though Pod was still running.

        Expected behavior:
        - Non-managed job completes remotely -> stays in RUNNING status
        - GET /api/jobs (default, all=false) shows the job
        - pxq ls --all also shows the job
        """
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        db_path = str(tmp_path / "test.db")
        monkeypatch.setenv("PXQ_DB_PATH", db_path)
        await init_db(db_path)

        # Create a non-managed RunPod job via storage (simulating API create)
        job = await create_job(
            db_path,
            Job(
                command="python train.py",
                provider="runpod",
                managed=False,
                pod_id="pod-non-managed-123",
            ),
        )
        job_id = job.id
        assert job_id is not None, "Job ID must be set after creation"

        # Transition through lifecycle to RUNNING
        await update_job_status(db_path, job_id, JobStatus.PROVISIONING)
        await update_job_status(db_path, job_id, JobStatus.UPLOADING)
        await update_job_status(db_path, job_id, JobStatus.RUNNING)

        # Simulate remote command completion (non-managed stays RUNNING)
        await update_job_metadata(
            db_path,
            job_id,
            exit_code=0,
            message="Remote command completed; awaiting pxq stop",
        )

        # Create API client and verify job is visible in default list
        app = create_app()
        with TestClient(app) as client:
            # Default list (all=false) should show RUNNING jobs
            response = client.get("/api/jobs")
            assert response.status_code == 200
            data = response.json()

            # CRITICAL: Job must be visible (count >= 1)
            assert data["count"] >= 1, (
                "Non-managed completion-pending job disappeared from default list. "
                f"Expected count >= 1, got {data['count']}"
            )

            # Find our job in the list
            job_found = False
            for listed_job in data["jobs"]:
                if listed_job["id"] == job_id:
                    job_found = True
                    assert (
                        listed_job["status"] == "running"
                    ), f"Non-managed job should be RUNNING, got {listed_job['status']}"
                    assert (
                        listed_job["exit_code"] == 0
                    ), "Exit code should be preserved after completion"
                    break

            assert job_found, f"Job {job_id} not found in API response"

            # With all=true, job should also be visible
            response_all = client.get("/api/jobs?all=true")
            assert response_all.status_code == 200
            data_all = response_all.json()
            assert data_all["count"] >= 1

    @pytest.mark.asyncio
    async def test_non_managed_explicit_stop_results_in_stopped(
        self, tmp_path, monkeypatch
    ) -> None:
        """Regression: non-managed explicit stop must result in STOPPED status.

        Bug: non-managed jobs that were explicitly stopped via pxq stop were
        observed as SUCCEEDED instead of STOPPED.

        Expected behavior:
        - Non-managed job in completion-pending state (RUNNING with exit_code)
        - POST /api/jobs/{id}/stop -> STOPPED status
        - Metadata (exit_code, error_message) preserved through stop
        """
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        db_path = str(tmp_path / "test.db")
        monkeypatch.setenv("PXQ_DB_PATH", db_path)
        await init_db(db_path)

        # Create a non-managed RunPod job
        job = await create_job(
            db_path,
            Job(
                command="python train.py",
                provider="runpod",
                managed=False,
                pod_id="pod-non-managed-456",
            ),
        )
        job_id = job.id
        assert job_id is not None, "Job ID must be set after creation"
        # Transition to RUNNING
        await update_job_status(db_path, job_id, JobStatus.PROVISIONING)
        await update_job_status(db_path, job_id, JobStatus.UPLOADING)
        await update_job_status(db_path, job_id, JobStatus.RUNNING)

        # Simulate completion-pending state
        await update_job_metadata(
            db_path,
            job_id,
            exit_code=0,
            error_message=None,
            message="Remote command completed; awaiting pxq stop",
        )

        # Mock RunPod client for stop operation
        mock_runpod_client = AsyncMock(spec=RunPodClient)
        mock_runpod_client.stop_pod = AsyncMock(return_value=None)
        mock_runpod_client.delete_pod = AsyncMock(return_value=None)

        # Patch RunPodClient to return our mock
        with patch("pxq.api.jobs.RunPodClient", return_value=mock_runpod_client):
            app = create_app()
            with TestClient(app) as client:
                # Call stop endpoint
                response = client.post(f"/api/jobs/{job_id}/stop")
                assert (
                    response.status_code == 200
                ), f"Stop endpoint failed: {response.json()}"

                data = response.json()

                # CRITICAL: Status must be STOPPED, not SUCCEEDED
                assert data["status"] == "stopped", (
                    f"Non-managed explicit stop should result in STOPPED, "
                    f"got {data['status']}"
                )

                # Metadata must be preserved
                assert (
                    data["exit_code"] == 0
                ), "Exit code should be preserved through stop"
                assert (
                    data["error_message"] is None
                ), "Error message should be preserved through stop"

        # Verify DB state is also STOPPED
        saved_job = await get_job(Path(db_path), job_id)
        assert saved_job is not None, "Job must exist after stop"
        assert (
            saved_job.status == JobStatus.STOPPED
        ), f"DB state should be STOPPED, got {saved_job.status}"
        assert saved_job.exit_code == 0

    @pytest.mark.asyncio
    async def test_non_managed_stop_preserves_failure_metadata(
        self, tmp_path, monkeypatch
    ) -> None:
        """Regression: stop must preserve failure metadata (exit_code, error_message).

        Expected behavior:
        - Non-managed job fails remotely (exit_code=1, error_message set)
        - Explicit stop -> STOPPED status with failure metadata preserved
        """
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        db_path = str(tmp_path / "test.db")
        monkeypatch.setenv("PXQ_DB_PATH", db_path)
        await init_db(db_path)

        # Create a non-managed RunPod job
        job = await create_job(
            db_path,
            Job(
                command="python fail.py",
                provider="runpod",
                managed=False,
                pod_id="pod-fail-789",
            ),
        )
        job_id = job.id
        assert job_id is not None, "Job ID must be set after creation"
        # Transition to RUNNING
        await update_job_status(db_path, job_id, JobStatus.PROVISIONING)
        await update_job_status(db_path, job_id, JobStatus.UPLOADING)
        await update_job_status(db_path, job_id, JobStatus.RUNNING)

        # Simulate failure completion-pending state
        error_msg = "CUDA out of memory"
        await update_job_metadata(
            db_path,
            job_id,
            exit_code=1,
            error_message=error_msg,
            message="Remote command failed; awaiting pxq stop",
        )

        # Mock RunPod client
        mock_runpod_client = AsyncMock(spec=RunPodClient)
        mock_runpod_client.stop_pod = AsyncMock(return_value=None)
        mock_runpod_client.delete_pod = AsyncMock(return_value=None)

        with patch("pxq.api.jobs.RunPodClient", return_value=mock_runpod_client):
            app = create_app()
            with TestClient(app) as client:
                # Call stop endpoint
                response = client.post(f"/api/jobs/{job_id}/stop")
                assert response.status_code == 200

                data = response.json()

                # Status must be STOPPED
                assert data["status"] == "stopped"

                # Failure metadata must be preserved
                assert (
                    data["exit_code"] == 1
                ), f"Failure exit_code should be preserved, got {data['exit_code']}"
                assert (
                    data["error_message"] == error_msg
                ), f"Error message should be preserved, got {data['error_message']}"

        # Verify DB state
        saved_job = await get_job(Path(db_path), job_id)
        assert saved_job is not None, "Job must exist"
        assert saved_job.status == JobStatus.STOPPED
        assert saved_job.exit_code == 1
        assert saved_job.error_message == error_msg

    @pytest.mark.asyncio
    async def test_full_non_managed_lifecycle_api_flow(
        self, tmp_path, monkeypatch
    ) -> None:
        """Full lifecycle test: create -> complete -> visible -> stop -> stopped.

        This test reproduces the exact user-reported flow:
        1. Create non-managed job via storage (bypass scheduler)
        2. Simulate runtime completion
        3. Verify GET /api/jobs shows job (reproduce visibility bug)
        4. Call POST /api/jobs/{id}/stop
        5. Verify job is STOPPED with metadata

        Note: We use storage directly for job creation to avoid scheduler
        interference during test execution.
        """
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        db_path = str(tmp_path / "test.db")
        monkeypatch.setenv("PXQ_DB_PATH", db_path)
        await init_db(db_path)

        # Step 1: Create non-managed job via storage (bypass scheduler)
        job = await create_job(
            db_path,
            Job(
                command="python train.py",
                provider="runpod",
                managed=False,
                gpu_type="RTX4090:1",
            ),
        )
        job_id = job.id
        assert job_id is not None

        # Manually transition to RUNNING (executor would do this in real flow)
        await update_job_status(db_path, job_id, JobStatus.PROVISIONING)
        await update_job_status(db_path, job_id, JobStatus.UPLOADING)
        await update_job_status(db_path, job_id, JobStatus.RUNNING)
        # Simulate pod_id being set
        from pxq.storage import update_job_field

        await update_job_field(db_path, job_id, "pod_id", "pod-lifecycle-001")

        # Step 2: Simulate runtime completion
        await update_job_metadata(
            db_path,
            job_id,
            exit_code=0,
            message="Remote command completed; awaiting pxq stop",
        )

        # Step 3: Verify job is visible in default list (BUG REPRODUCTION POINT)
        app = create_app()
        with TestClient(app) as client:
            list_response = client.get("/api/jobs")
            assert list_response.status_code == 200
            list_data = list_response.json()

            # This is the key assertion - job MUST be visible
            assert (
                list_data["count"] >= 1
            ), "BUG REPRODUCED: Non-managed job disappeared from default list"

            job_in_list = next(
                (j for j in list_data["jobs"] if j["id"] == job_id), None
            )
            assert job_in_list is not None, f"Job {job_id} not found in list response"
            assert job_in_list["status"] == "running"
            assert job_in_list["exit_code"] == 0

            # Step 4: Call explicit stop
            mock_runpod_client = AsyncMock(spec=RunPodClient)
            mock_runpod_client.stop_pod = AsyncMock(return_value=None)
            mock_runpod_client.delete_pod = AsyncMock(return_value=None)

            with patch("pxq.api.jobs.RunPodClient", return_value=mock_runpod_client):
                stop_response = client.post(f"/api/jobs/{job_id}/stop")
                assert stop_response.status_code == 200
                stop_data = stop_response.json()

                # Step 5: Verify STOPPED with metadata
                assert (
                    stop_data["status"] == "stopped"
                ), f"Expected STOPPED, got {stop_data['status']}"
                assert stop_data["exit_code"] == 0

        # Final DB verification
        final_job = await get_job(Path(db_path), job_id)
        assert final_job is not None, "Job must exist"
        assert final_job.status == JobStatus.STOPPED
        assert final_job.exit_code == 0
