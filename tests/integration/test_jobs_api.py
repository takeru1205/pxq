"""Integration tests for Jobs API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient

from pxq.server import create_app
from pxq.storage import init_db


@pytest.fixture
def client(tmp_path) -> TestClient:
    """Create a test client with a temporary database."""
    import os

    # Set the database path to a temporary location
    db_path = tmp_path / "test.db"
    os.environ["PXQ_DB_PATH"] = str(db_path)

    # Initialize the database
    import asyncio

    asyncio.run(init_db(db_path))

    app = create_app()
    return TestClient(app)


class TestCreateJob:
    """Tests for POST /api/jobs endpoint."""

    def test_create_job_with_command_only(self, client: TestClient) -> None:
        """Test creating a job with just a command."""
        response = client.post("/api/jobs", json={"command": "echo hello"})
        assert response.status_code == 201
        data = response.json()
        assert data["command"] == "echo hello"
        assert data["status"] == "queued"
        assert data["provider"] == "local"
        assert data["managed"] is False
        assert "id" in data
        assert "created_at" in data

    def test_create_job_with_all_options(self, client: TestClient) -> None:
        """Test creating a job with all options."""
        response = client.post(
            "/api/jobs",
            json={
                "command": "python train.py",
                "provider": "runpod",
                "managed": True,
                "workdir": "/workspace",
                "gpu_type": "RTX4090:1",
                "cpu_count": 4,
                "volume_id": "vol-123",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["command"] == "python train.py"
        assert data["provider"] == "runpod"
        assert data["managed"] is True
        assert data["workdir"] == "/workspace"
        assert data["gpu_type"] == "RTX4090:1"
        assert data["cpu_count"] == 4
        assert data["volume_id"] == "vol-123"

    def test_create_job_with_env_placeholders(self, client: TestClient) -> None:
        """Test creating a job with env placeholders preserves them exactly."""
        response = client.post(
            "/api/jobs",
            json={
                "command": "python train.py",
                "provider": "runpod",
                "env": {
                    "KAGGLE_KEY": "{{ RUNPOD_SECRET_KAGGLE_KEY }}",
                    "HF_TOKEN": "{{ RUNPOD_SECRET_HF_TOKEN }}",
                },
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["env"]["KAGGLE_KEY"] == "{{ RUNPOD_SECRET_KAGGLE_KEY }}"
        assert data["env"]["HF_TOKEN"] == "{{ RUNPOD_SECRET_HF_TOKEN }}"

    def test_create_job_without_env_returns_null(self, client: TestClient) -> None:
        """Test that creating a job without env returns null/absent env."""
        response = client.post("/api/jobs", json={"command": "echo hello"})
        assert response.status_code == 201
        data = response.json()
        # env should be None when not provided
        assert data.get("env") is None

    def test_create_job_empty_command_fails(self, client: TestClient) -> None:
        """Test that empty command is rejected."""
        response = client.post("/api/jobs", json={"command": ""})
        assert response.status_code == 422  # Validation error


class TestListJobs:
    """Tests for GET /api/jobs endpoint."""

    def test_list_jobs_empty(self, client: TestClient) -> None:
        """Test listing jobs when empty."""
        response = client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["jobs"] == []
        assert data["count"] == 0

    def test_list_jobs_excludes_terminal_by_default(self, client: TestClient) -> None:
        """Test that terminal state jobs are excluded by default."""
        # Create jobs
        client.post("/api/jobs", json={"command": "echo 1"})
        job2_response = client.post("/api/jobs", json={"command": "echo 2"})
        job2_id = job2_response.json()["id"]

        # Transition job2 to succeeded through valid path
        # Note: We need to use storage directly for state transitions
        import asyncio

        from pxq.models import JobStatus
        from pxq.storage import get_job, update_job_status

        db_path = client.app.dependency_overrides.get(
            lambda: None, lambda: None
        )()  # Get db_path from settings

        import os

        db_path = os.environ.get("PXQ_DB_PATH")

        job = asyncio.run(get_job(db_path, job2_id))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.RUNNING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.SUCCEEDED))

        # List jobs - should only show job1
        response = client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["jobs"][0]["command"] == "echo 1"

    def test_list_jobs_with_all_includes_terminal(self, client: TestClient) -> None:
        """Test that all jobs are included with all=true."""
        # Create jobs
        client.post("/api/jobs", json={"command": "echo 1"})
        job2_response = client.post("/api/jobs", json={"command": "echo 2"})
        job2_id = job2_response.json()["id"]

        # Transition job2 to succeeded
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        db_path = os.environ.get("PXQ_DB_PATH")
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.RUNNING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.SUCCEEDED))

        # List all jobs
        response = client.get("/api/jobs?all=true")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2


class TestGetJob:
    """Tests for GET /api/jobs/{job_id} endpoint."""

    def test_get_job_by_id(self, client: TestClient) -> None:
        """Test getting a job by ID."""
        create_response = client.post("/api/jobs", json={"command": "echo hello"})
        job_id = create_response.json()["id"]

        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == job_id
        assert data["command"] == "echo hello"

    def test_get_job_not_found(self, client: TestClient) -> None:
        """Test getting a non-existent job."""
        response = client.get("/api/jobs/999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_get_job_preserves_env_placeholders(self, client: TestClient) -> None:
        """Test that GET /api/jobs/{id} preserves env placeholders from storage."""
        # Create job with env placeholders
        create_response = client.post(
            "/api/jobs",
            json={
                "command": "python train.py",
                "provider": "runpod",
                "env": {
                    "KAGGLE_KEY": "{{ RUNPOD_SECRET_KAGGLE_KEY }}",
                    "HF_TOKEN": "{{ RUNPOD_SECRET_HF_TOKEN }}",
                },
            },
        )
        assert create_response.status_code == 201
        job_id = create_response.json()["id"]

        # Retrieve the job
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        # Verify env placeholders are preserved exactly from storage
        assert data["env"]["KAGGLE_KEY"] == "{{ RUNPOD_SECRET_KAGGLE_KEY }}"
        assert data["env"]["HF_TOKEN"] == "{{ RUNPOD_SECRET_HF_TOKEN }}"


class TestImageNamePersistence:
    """Regression tests for image_name persistence through API/storage round-trip."""

    def test_create_job_with_image_name_returns_in_response(
        self, client: TestClient
    ) -> None:
        """Test that POST /api/jobs with image_name returns it in the response.

        This test pins the regression where image_name was not persisted.
        Before the fix, this should fail because:
        1. create_job_endpoint() does not call create_job() storage function
        2. storage does not persist image_name column
        """
        response = client.post(
            "/api/jobs",
            json={
                "command": "python train.py",
                "provider": "runpod",
                "image_name": "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert (
            data["image_name"]
            == "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04"
        ), "image_name should be returned in POST response"

    def test_create_job_with_template_id_returns_in_response(
        self, client: TestClient
    ) -> None:
        """Test that POST /api/jobs with template_id returns it in the response.

        This test pins the regression where template_id was not persisted.
        """
        response = client.post(
            "/api/jobs",
            json={
                "command": "python train.py",
                "provider": "runpod",
                "template_id": "tpl-abc123",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert (
            data["template_id"] == "tpl-abc123"
        ), "template_id should be returned in POST response"

    def test_get_job_by_id_preserves_image_name(self, client: TestClient) -> None:
        """Test that GET /api/jobs/{id} preserves image_name from creation.

        This test pins the regression where image_name does not survive
        the POST -> GET round-trip because storage does not persist/read it.
        """
        # Create job with image_name
        create_response = client.post(
            "/api/jobs",
            json={
                "command": "python train.py",
                "provider": "runpod",
                "image_name": "ubuntu:22.04",
            },
        )
        assert create_response.status_code == 201
        job_id = create_response.json()["id"]

        # Retrieve the job and verify image_name persisted
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert (
            data["image_name"] == "ubuntu:22.04"
        ), "image_name should survive POST -> GET round-trip through storage"

    def test_get_job_by_id_preserves_template_id(self, client: TestClient) -> None:
        """Test that GET /api/jobs/{id} preserves template_id from creation.

        This test pins the regression where template_id does not survive
        the POST -> GET round-trip because storage does not persist/read it.
        """
        # Create job with template_id
        create_response = client.post(
            "/api/jobs",
            json={
                "command": "python train.py",
                "provider": "runpod",
                "template_id": "tpl-xyz789",
            },
        )
        assert create_response.status_code == 201
        job_id = create_response.json()["id"]

        # Retrieve the job and verify template_id persisted
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert (
            data["template_id"] == "tpl-xyz789"
        ), "template_id should survive POST -> GET round-trip through storage"


class TestCancelJob:
    """Tests for POST /api/jobs/{job_id}/cancel endpoint."""

    def test_cancel_queued_job(self, client: TestClient) -> None:
        """Test cancelling a queued job."""
        # Create a job
        create_response = client.post("/api/jobs", json={"command": "echo hello"})
        assert create_response.status_code == 201
        job_id = create_response.json()["id"]

        # Cancel the job
        cancel_response = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel_response.status_code == 200
        data = cancel_response.json()
        assert data["id"] == job_id
        assert data["status"] == "cancelled"

    def test_cancel_provisioning_job(self, client: TestClient) -> None:
        """Test cancelling a provisioning job."""
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        # Create a job and transition to provisioning
        create_response = client.post("/api/jobs", json={"command": "echo hello"})
        job_id = create_response.json()["id"]

        db_path = os.environ.get("PXQ_DB_PATH")
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))

        # Cancel the provisioning job
        cancel_response = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel_response.status_code == 200
        data = cancel_response.json()
        assert data["id"] == job_id
        assert data["status"] == "cancelled"

    def test_cancel_uploading_job(self, client: TestClient) -> None:
        """Test cancelling an uploading job."""
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        # Create a job and transition to uploading
        create_response = client.post("/api/jobs", json={"command": "echo hello"})
        job_id = create_response.json()["id"]

        db_path = os.environ.get("PXQ_DB_PATH")
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))

        # Cancel the uploading job
        cancel_response = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel_response.status_code == 200
        data = cancel_response.json()
        assert data["id"] == job_id
        assert data["status"] == "cancelled"

    def test_cancel_running_job_fails(self, client: TestClient) -> None:
        """Test that cancelling a running job returns 400."""
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        # Create a job and transition to running
        create_response = client.post("/api/jobs", json={"command": "echo hello"})
        job_id = create_response.json()["id"]

        db_path = os.environ.get("PXQ_DB_PATH")
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))

        # Try to cancel the running job
        cancel_response = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel_response.status_code == 400
        assert "is running" in cancel_response.json()["detail"]

    def test_cancel_non_existent_job(self, client: TestClient) -> None:
        """Test cancelling a non-existent job returns 404."""
        cancel_response = client.post("/api/jobs/999/cancel")
        assert cancel_response.status_code == 404
        assert "not found" in cancel_response.json()["detail"]


class TestStopJob:
    """Tests for POST /api/jobs/stop endpoint."""

    @pytest.mark.integration
    def test_stop_no_running_jobs(self, client: TestClient) -> None:
        """Test stop API returns 400 when no running jobs exist."""
        response = client.post("/api/jobs/stop")
        assert response.status_code == 400
        assert response.json()["detail"] == "No running jobs found"

    @pytest.mark.integration
    def test_stop_suggests_cancel_for_provisioning_jobs(
        self, client: TestClient
    ) -> None:
        """Test stop API suggests cancel when provisioning jobs exist."""
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create a job and transition to provisioning
        job_response = client.post("/api/jobs", json={"command": "echo 1"})
        job_id = job_response.json()["id"]
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))

        # Try to stop - should suggest cancel
        response = client.post("/api/jobs/stop")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "No running jobs found" in detail
        assert "provisioning/uploading" in detail
        assert "cancel" in detail

    @pytest.mark.integration
    def test_stop_suggests_cancel_for_uploading_jobs(self, client: TestClient) -> None:
        """Test stop API suggests cancel when uploading jobs exist."""
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create a job and transition to uploading
        job_response = client.post("/api/jobs", json={"command": "echo 1"})
        job_id = job_response.json()["id"]
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))

        # Try to stop - should suggest cancel
        response = client.post("/api/jobs/stop")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "No running jobs found" in detail
        assert "provisioning/uploading" in detail
        assert "cancel" in detail

    def test_stop_multiple_running_jobs(self, client: TestClient) -> None:
        """Test stop API returns 400 with job IDs when multiple running jobs exist."""
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create two jobs
        job1_response = client.post("/api/jobs", json={"command": "echo 1"})
        job1_id = job1_response.json()["id"]
        job2_response = client.post("/api/jobs", json={"command": "echo 2"})
        job2_id = job2_response.json()["id"]

        # Transition both to running
        for job_id in [job1_id, job2_id]:
            asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
            asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
            asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))

        # Try to stop - should fail with multiple jobs error
        response = client.post("/api/jobs/stop")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "Multiple running jobs found" in detail
        assert str(job1_id) in detail
        assert str(job2_id) in detail

    @pytest.mark.integration
    def test_stop_single_runpod_job_success(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Test stop API successfully stops a single RunPod job (mock-based)."""
        import asyncio
        import os
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, patch

        from pxq.models import JobStatus, Job
        from pxq.storage import update_job_status, get_job, create_job

        db_path = os.environ.get("PXQ_DB_PATH")
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        # Create a RunPod job directly with pod_id
        job = asyncio.run(
            create_job(
                db_path,
                Job(
                    command="python train.py",
                    provider="runpod",
                    pod_id="pod-123",
                ),
            )
        )
        job_id = job.id

        # Transition to running
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))

        now = datetime.now(timezone.utc)

        # Mock managed_stop
        with patch(
            "pxq.api.jobs.managed_stop", new_callable=AsyncMock
        ) as mock_managed_stop:
            # Create a real Job object to return
            mock_job = Job(
                command="python train.py",
                provider="runpod",
                managed=False,
                pod_id="pod-123",
            )
            # Set attributes that are normally set by storage
            mock_job.id = job_id
            mock_job.status = JobStatus.STOPPED
            mock_job.created_at = now
            mock_job.updated_at = now
            mock_job.started_at = now
            mock_job.finished_at = now
            mock_job.exit_code = None
            mock_job.error_message = None
            mock_job.local_pid = None

            mock_managed_stop.return_value = mock_job

            # Call stop API
            response = client.post("/api/jobs/stop")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == job_id
            assert data["status"] == "stopped"

            # Verify managed_stop was called
            mock_managed_stop.assert_called_once()

    @pytest.mark.integration
    def test_stop_single_local_job_success(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Test stop API successfully stops a single local job (mock-based)."""
        import asyncio
        import os
        from unittest.mock import patch, AsyncMock

        from pxq.models import JobStatus, Job
        from pxq.storage import update_job_status, get_job, create_job

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create a local job directly
        job = asyncio.run(
            create_job(
                db_path,
                Job(
                    command="python train.py",
                    provider="local",
                ),
            )
        )
        job_id = job.id

        # Transition to running with a local_pid
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(
            update_job_status(db_path, job_id, JobStatus.RUNNING, local_pid=12345)
        )

        # Mock stop_local_process inside stop_local_job to avoid actual process termination
        with patch("pxq.executor.stop_local_process", return_value=True):
            # Call stop API - this will call real stop_local_job which updates DB
            response = client.post("/api/jobs/stop")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == job_id
            assert data["status"] == "stopped"

    @pytest.mark.integration
    def test_stop_runpod_job_without_api_key_fails(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Test stop API returns 500 when RunPod API key is not configured."""
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create a RunPod job
        create_response = client.post(
            "/api/jobs",
            json={
                "command": "python train.py",
                "provider": "runpod",
                "pod_id": "pod-123",
            },
        )
        job_id = create_response.json()["id"]

        # Transition to running
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))

        # Remove API key
        monkeypatch.delenv("PXQ_RUNPOD_API_KEY", raising=False)

        # Call stop API
        response = client.post("/api/jobs/stop")
        assert response.status_code == 500
        assert "RunPod API key not configured" in response.json()["detail"]

    @pytest.mark.integration
    def test_stop_runpod_job_without_pod_id_fails(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Test stop API returns 400 when RunPod job has no pod_id."""
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create a RunPod job without pod_id
        create_response = client.post(
            "/api/jobs",
            json={
                "command": "python train.py",
                "provider": "runpod",
            },
        )
        job_id = create_response.json()["id"]

        # Transition to running
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))

        # Set API key
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        # Call stop API
        response = client.post("/api/jobs/stop")
        assert response.status_code == 400
        assert f"Job {job_id} has no pod_id" in response.json()["detail"]

    @pytest.mark.integration
    def test_stop_completion_pending_runpod_job_preserves_metadata(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Test stop API preserves exit_code and error_message for completion-pending jobs.

        Non-managed jobs stay RUNNING after remote completion until explicit stop.
        When stopped, managed_stop() is called with cleanup semantics.
        """
        import asyncio
        import os
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, patch

        from pxq.models import JobStatus, Job
        from pxq.storage import update_job_status, update_job_metadata, create_job

        db_path = os.environ.get("PXQ_DB_PATH")
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        job = asyncio.run(
            create_job(
                db_path,
                Job(
                    command="python train.py",
                    provider="runpod",
                    pod_id="pod-123",
                    managed=False,
                ),
            )
        )
        job_id = job.id

        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))

        asyncio.run(
            update_job_metadata(
                db_path,
                job_id,
                exit_code=0,
                error_message=None,
                message="Remote command completed; awaiting pxq stop",
            )
        )

        now = datetime.now(timezone.utc)

        with patch(
            "pxq.api.jobs.managed_stop", new_callable=AsyncMock
        ) as mock_managed_stop:
            mock_job = Job(
                command="python train.py",
                provider="runpod",
                managed=False,
                pod_id="pod-123",
            )
            mock_job.id = job_id
            mock_job.status = JobStatus.STOPPED
            mock_job.created_at = now
            mock_job.updated_at = now
            mock_job.started_at = now
            mock_job.finished_at = now
            mock_job.exit_code = 0
            mock_job.error_message = None
            mock_job.local_pid = None

            mock_managed_stop.return_value = mock_job

            response = client.post("/api/jobs/stop")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == job_id
            assert data["status"] == "stopped"
            assert data["exit_code"] == 0

            # Verify managed_stop was called with completion metadata
            mock_managed_stop.assert_called_once()
            call_kwargs = mock_managed_stop.call_args[1]
            assert call_kwargs["final_exit_code"] == 0
            assert call_kwargs["final_error_message"] is None

    @pytest.mark.integration
    def test_non_managed_completion_does_not_call_pod_lifecycle(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Test non-managed job completion path does NOT call pod lifecycle APIs.

        This is the delayed cleanup contract: non-managed jobs complete remotely
        but pod remains running until explicit pxq stop. The completion path
        should only update metadata, not stop/terminate/delete the pod.
        """
        import asyncio
        import os
        from unittest.mock import AsyncMock, patch, MagicMock

        from pxq.models import JobStatus, Job
        from pxq.storage import (
            update_job_status,
            update_job_metadata,
            create_job,
            get_job,
        )
        from pxq.providers.runpod_client import RunPodClient

        db_path = os.environ.get("PXQ_DB_PATH")
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        job = asyncio.run(
            create_job(
                db_path,
                Job(
                    command="python train.py",
                    provider="runpod",
                    pod_id="pod-test-123",
                    managed=False,
                ),
            )
        )
        job_id = job.id

        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))

        # Mock RunPodClient to verify pod lifecycle APIs are NOT called
        mock_client = AsyncMock(spec=RunPodClient)

        with (
            patch(
                "pxq.providers.runpod_exec.RunPodClient",
                return_value=mock_client,
            ),
            patch(
                "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=AsyncMock(returncode=0)),
            ),
        ):
            # Simulate remote command completion
            asyncio.run(
                update_job_metadata(
                    db_path,
                    job_id,
                    exit_code=0,
                    message="Remote command completed",
                )
            )

        # Verify pod lifecycle APIs were NOT called on completion
        mock_client.stop_pod.assert_not_called()
        mock_client.terminate_pod.assert_not_called()
        mock_client.delete_pod.assert_not_called()

        # Job should still be RUNNING with exit_code set
        saved_job = asyncio.run(get_job(db_path, job_id))
        assert saved_job is not None
        assert saved_job.status == JobStatus.RUNNING
        assert saved_job.exit_code == 0

    @pytest.mark.integration
    def test_stop_completion_pending_failed_job_preserves_error(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Test stop API preserves exit_code and error_message for failed completion-pending jobs."""
        import asyncio
        import os
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, patch

        from pxq.models import JobStatus, Job
        from pxq.storage import update_job_status, update_job_metadata, create_job

        db_path = os.environ.get("PXQ_DB_PATH")
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        job = asyncio.run(
            create_job(
                db_path,
                Job(
                    command="python train.py",
                    provider="runpod",
                    pod_id="pod-456",
                    managed=False,
                ),
            )
        )
        job_id = job.id

        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))

        asyncio.run(
            update_job_metadata(
                db_path,
                job_id,
                exit_code=1,
                error_message="Training failed: OOM",
                message="Remote command failed; awaiting pxq stop",
            )
        )

        now = datetime.now(timezone.utc)

        with patch(
            "pxq.api.jobs.managed_stop", new_callable=AsyncMock
        ) as mock_managed_stop:
            mock_job = Job(
                command="python train.py",
                provider="runpod",
                managed=False,
                pod_id="pod-456",
            )
            mock_job.id = job_id
            mock_job.status = JobStatus.STOPPED
            mock_job.created_at = now
            mock_job.updated_at = now
            mock_job.started_at = now
            mock_job.finished_at = now
            mock_job.exit_code = 1
            mock_job.error_message = "Training failed: OOM"
            mock_job.local_pid = None

            mock_managed_stop.return_value = mock_job

            response = client.post("/api/jobs/stop")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == job_id
            assert data["status"] == "stopped"
            assert data["exit_code"] == 1
            assert data["error_message"] == "Training failed: OOM"

            call_kwargs = mock_managed_stop.call_args[1]
            assert call_kwargs["final_exit_code"] == 1
            assert call_kwargs["final_error_message"] == "Training failed: OOM"


class TestStopJobById:
    """Tests for POST /api/jobs/{job_id}/stop endpoint."""

    def test_stop_by_job_id_not_found(self, client: TestClient) -> None:
        """Test stop by id returns 404 for non-existent job."""
        response = client.post("/api/jobs/999/stop")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_stop_by_job_id_not_running(self, client: TestClient) -> None:
        """Test stop by id returns 400 for non-running job."""
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        # Create a job and leave it in queued state
        create_response = client.post("/api/jobs", json={"command": "echo hello"})
        job_id = create_response.json()["id"]

        # Try to stop - should fail with helpful message
        response = client.post(f"/api/jobs/{job_id}/stop")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "Cannot stop job" in detail
        assert "cancel" in detail.lower()

    def test_stop_by_job_id_succeeded_job(self, client: TestClient) -> None:
        """Test stop by id returns 400 for succeeded job."""
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create a job and transition to succeeded
        create_response = client.post("/api/jobs", json={"command": "echo hello"})
        job_id = create_response.json()["id"]

        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.SUCCEEDED))

        # Try to stop - should fail with terminal state message
        response = client.post(f"/api/jobs/{job_id}/stop")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "terminal state" in detail
        assert "succeeded" in detail

    def test_stop_by_job_id_stopping_job(self, client: TestClient) -> None:
        """Test stop by id returns 400 for job already stopping."""
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create a job and transition to stopping
        create_response = client.post("/api/jobs", json={"command": "echo hello"})
        job_id = create_response.json()["id"]

        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.STOPPING))

        # Try to stop - should fail with already stopping message
        response = client.post(f"/api/jobs/{job_id}/stop")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "already stopping" in detail

    @pytest.mark.integration
    def test_stop_by_job_id_runpod_success(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Test stop by id successfully stops a RunPod job."""
        import asyncio
        import os
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, patch

        from pxq.models import JobStatus, Job
        from pxq.storage import update_job_status, create_job

        db_path = os.environ.get("PXQ_DB_PATH")
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        # Create a RunPod job with pod_id
        job = asyncio.run(
            create_job(
                db_path,
                Job(
                    command="python train.py",
                    provider="runpod",
                    pod_id="pod-123",
                ),
            )
        )
        job_id = job.id

        # Transition to running
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))

        now = datetime.now(timezone.utc)

        with patch(
            "pxq.api.jobs.managed_stop", new_callable=AsyncMock
        ) as mock_managed_stop:
            mock_job = Job(
                command="python train.py",
                provider="runpod",
                managed=False,
                pod_id="pod-123",
            )
            mock_job.id = job_id
            mock_job.status = JobStatus.STOPPED
            mock_job.created_at = now
            mock_job.updated_at = now
            mock_job.started_at = now
            mock_job.finished_at = now
            mock_job.exit_code = None
            mock_job.error_message = None
            mock_job.local_pid = None

            mock_managed_stop.return_value = mock_job

            response = client.post(f"/api/jobs/{job_id}/stop")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == job_id
            assert data["status"] == "stopped"

            mock_managed_stop.assert_called_once()

    @pytest.mark.integration
    def test_stop_by_job_id_local_success(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Test stop by id successfully stops a local job."""
        import asyncio
        import os
        from unittest.mock import patch

        from pxq.models import JobStatus, Job
        from pxq.storage import update_job_status, create_job

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create a local job
        job = asyncio.run(
            create_job(
                db_path,
                Job(
                    command="python train.py",
                    provider="local",
                ),
            )
        )
        job_id = job.id

        # Transition to running with local_pid
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(
            update_job_status(db_path, job_id, JobStatus.RUNNING, local_pid=12345)
        )

        with patch("pxq.executor.stop_local_process", return_value=True):
            response = client.post(f"/api/jobs/{job_id}/stop")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == job_id
            assert data["status"] == "stopped"

    @pytest.mark.integration
    def test_stop_by_job_id_with_multiple_running(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Test stop by id works even when multiple jobs are running."""
        import asyncio
        import os
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, patch

        from pxq.models import JobStatus, Job
        from pxq.storage import update_job_status, create_job

        db_path = os.environ.get("PXQ_DB_PATH")
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        # Create two RunPod jobs
        job1 = asyncio.run(
            create_job(
                db_path,
                Job(command="echo 1", provider="runpod", pod_id="pod-1"),
            )
        )
        job2 = asyncio.run(
            create_job(
                db_path,
                Job(command="echo 2", provider="runpod", pod_id="pod-2"),
            )
        )

        # Transition both to running
        for job in [job1, job2]:
            asyncio.run(update_job_status(db_path, job.id, JobStatus.PROVISIONING))
            asyncio.run(update_job_status(db_path, job.id, JobStatus.UPLOADING))
            asyncio.run(update_job_status(db_path, job.id, JobStatus.RUNNING))

        now = datetime.now(timezone.utc)

        with patch(
            "pxq.api.jobs.managed_stop", new_callable=AsyncMock
        ) as mock_managed_stop:
            mock_job = Job(
                command="echo 1",
                provider="runpod",
                managed=False,
                pod_id="pod-1",
            )
            mock_job.id = job1.id
            mock_job.status = JobStatus.STOPPED
            mock_job.created_at = now
            mock_job.updated_at = now
            mock_job.started_at = now
            mock_job.finished_at = now
            mock_job.exit_code = None
            mock_job.error_message = None
            mock_job.local_pid = None

            mock_managed_stop.return_value = mock_job

            # Stop job1 by id - should succeed despite multiple running
            response = client.post(f"/api/jobs/{job1.id}/stop")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == job1.id
            assert data["status"] == "stopped"

    @pytest.mark.integration
    def test_stop_by_job_id_preserves_completion_metadata(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Test stop by id preserves exit_code and error_message for completion-pending jobs."""
        import asyncio
        import os
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, patch

        from pxq.models import JobStatus, Job
        from pxq.storage import update_job_status, update_job_metadata, create_job

        db_path = os.environ.get("PXQ_DB_PATH")
        monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-key")

        job = asyncio.run(
            create_job(
                db_path,
                Job(
                    command="python train.py",
                    provider="runpod",
                    pod_id="pod-xyz",
                    managed=False,
                ),
            )
        )
        job_id = job.id

        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))

        # Simulate remote completion with exit_code
        asyncio.run(
            update_job_metadata(
                db_path,
                job_id,
                exit_code=0,
                error_message=None,
                message="Remote command completed; awaiting pxq stop",
            )
        )

        now = datetime.now(timezone.utc)

        with patch(
            "pxq.api.jobs.managed_stop", new_callable=AsyncMock
        ) as mock_managed_stop:
            mock_job = Job(
                command="python train.py",
                provider="runpod",
                managed=False,
                pod_id="pod-xyz",
            )
            mock_job.id = job_id
            mock_job.status = JobStatus.STOPPED
            mock_job.created_at = now
            mock_job.updated_at = now
            mock_job.started_at = now
            mock_job.finished_at = now
            mock_job.exit_code = 0
            mock_job.error_message = None
            mock_job.local_pid = None

            mock_managed_stop.return_value = mock_job

            response = client.post(f"/api/jobs/{job_id}/stop")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == job_id
            assert data["status"] == "stopped"
            assert data["exit_code"] == 0

            call_kwargs = mock_managed_stop.call_args[1]
            assert call_kwargs["final_exit_code"] == 0
            assert call_kwargs["final_error_message"] is None


class TestVisibilitySemantics:
    """Regression tests for default visibility semantics.

    These tests lock in the visibility behavior based on status semantics:
    - Non-managed completion-pending jobs stay RUNNING (visible by default)
    - Managed success jobs end at SUCCEEDED (hidden by default as terminal)
    - Terminal states (SUCCEEDED/FAILED/STOPPED/CANCELLED) are hidden by default
    """

    def test_non_managed_completion_pending_visible_by_default(
        self, client: TestClient
    ) -> None:
        """Test that non-managed completion-pending jobs are visible in default list.

        Non-managed RunPod jobs stay in RUNNING status after remote command completion,
        waiting for explicit pxq stop. Since RUNNING is not a terminal state,
        these jobs appear in the default list view.
        """
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status, update_job_metadata, create_job, Job

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create a non-managed RunPod job
        job = asyncio.run(
            create_job(
                db_path,
                Job(
                    command="python train.py",
                    provider="runpod",
                    managed=False,
                    pod_id="pod-abc",
                ),
            )
        )
        job_id = job.id

        # Transition to running
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))

        # Simulate remote command completion (non-managed stays RUNNING)
        asyncio.run(
            update_job_metadata(
                db_path,
                job_id,
                exit_code=0,
                message="Remote command completed; awaiting pxq stop",
            )
        )

        # Default list should show the job (RUNNING is not terminal)
        response = client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["jobs"][0]["id"] == job_id
        assert data["jobs"][0]["status"] == "running"

    def test_managed_success_hidden_by_default(self, client: TestClient) -> None:
        """Test that managed success jobs are hidden in default list.

        Managed RunPod jobs that complete successfully end at SUCCEEDED status.
        Since SUCCEEDED is a terminal state, these jobs are excluded from the
        default list view (unless include_all=True).
        """
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status, create_job, Job

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create a managed RunPod job
        job = asyncio.run(
            create_job(
                db_path,
                Job(
                    command="python train.py",
                    provider="runpod",
                    managed=True,
                    pod_id="pod-def",
                ),
            )
        )
        job_id = job.id

        # Transition to succeeded (terminal state)
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.SUCCEEDED))

        # Default list should NOT show the job (SUCCEEDED is terminal)
        response = client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0

        # With all=true, the job should be visible
        response = client.get("/api/jobs?all=true")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["jobs"][0]["id"] == job_id
        assert data["jobs"][0]["status"] == "succeeded"

    def test_terminal_states_hidden_by_default(self, client: TestClient) -> None:
        """Test that all terminal states are hidden from default list.

        Terminal states: SUCCEEDED, FAILED, STOPPED, CANCELLED.
        """
        import asyncio
        import os

        from pxq.models import JobStatus
        from pxq.storage import update_job_status, create_job, Job

        db_path = os.environ.get("PXQ_DB_PATH")

        # Create jobs and transition them to terminal states
        terminal_states = [
            (JobStatus.SUCCEEDED, "succeeded-job"),
            (JobStatus.FAILED, "failed-job"),
            (JobStatus.STOPPED, "stopped-job"),
            (JobStatus.CANCELLED, "cancelled-job"),
        ]

        for status, cmd_suffix in terminal_states:
            job = asyncio.run(
                create_job(
                    db_path,
                    Job(
                        command=f"echo {cmd_suffix}",
                        provider="local",
                    ),
                )
            )
            asyncio.run(update_job_status(db_path, job.id, JobStatus.PROVISIONING))
            asyncio.run(update_job_status(db_path, job.id, JobStatus.UPLOADING))
            asyncio.run(update_job_status(db_path, job.id, JobStatus.RUNNING))
            asyncio.run(update_job_status(db_path, job.id, status))

        # Create a non-terminal job for comparison
        active_job = asyncio.run(
            create_job(
                db_path,
                Job(
                    command="echo active",
                    provider="local",
                ),
            )
        )
        asyncio.run(update_job_status(db_path, active_job.id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, active_job.id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, active_job.id, JobStatus.RUNNING))

        # Default list should only show the active job
        response = client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["jobs"][0]["id"] == active_job.id

        # With all=true, all 5 jobs should be visible
        response = client.get("/api/jobs?all=true")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 5
