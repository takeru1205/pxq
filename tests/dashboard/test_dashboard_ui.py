from __future__ import annotations

# pyright: reportMissingImports=false

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from pxq.server import create_app


@pytest.fixture
def client(tmp_path, mock_settings: object) -> Iterator[TestClient]:
    """Create a test client with a temporary database."""
    import os
    import asyncio
    from pxq.storage import init_db

    # Set the database path to a temporary location
    db_path = tmp_path / "test.db"
    os.environ["PXQ_DB_PATH"] = str(db_path)

    # Initialize the database
    asyncio.run(init_db(db_path))

    app = create_app()
    with TestClient(app) as client:
        yield client


def _create_job(client: TestClient, command: str = "echo hello") -> int:
    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "provider": "local",
            "managed": False,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert "id" in payload
    return int(payload["id"])


class TestDashboardIndex:
    def test_get_root_renders_html(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "Dashboard" in response.text
        assert 'hx-trigger="every 10s"' in response.text

    def test_root_includes_created_job(self, client: TestClient) -> None:
        job_id = _create_job(client, command="uv run python -c 'print(1)'")

        response = client.get("/")
        assert response.status_code == 200
        assert f">{job_id}<" in response.text


class TestDashboardPartials:
    def test_partials_jobs_returns_partial_html(self, client: TestClient) -> None:
        job_id = _create_job(client, command="echo partial")

        response = client.get("/partials/jobs")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert f">{job_id}<" in response.text
        assert "<table" in response.text

    def test_job_detail_and_logs_partial_render(self, client: TestClient) -> None:
        job_id = _create_job(client, command="echo detail")

        detail = client.get(f"/jobs/{job_id}")
        assert detail.status_code == 200
        assert "Log fragment" in detail.text
        assert f"/partials/jobs/{job_id}/logs" in detail.text

        logs = client.get(f"/partials/jobs/{job_id}/logs")
        assert logs.status_code == 200
        assert "Recent events" in logs.text


class TestDashboardLogsPartialStdoutStderr:
    """Tests for stdout/stderr artifact rendering in logs partial."""

    def _create_job_with_artifact(
        self,
        client: TestClient,
        artifact_type: str,
        content: str,
        path: str = "/tmp/output",
    ) -> int:
        """Create a job and add an artifact directly to the database."""
        import asyncio
        import os
        from pxq.storage import create_artifact

        # Create the job first
        job_id = _create_job(client, command="echo test")

        # Get the database path from environment
        db_path = os.environ.get("PXQ_DB_PATH", ":memory:")

        # Create the artifact synchronously using asyncio
        asyncio.run(
            create_artifact(
                db_path,
                job_id,
                artifact_type=artifact_type,
                path=path,
                size_bytes=len(content),
                content=content,
            )
        )

        return job_id

    def test_logs_partial_renders_stdout_artifact(self, client: TestClient) -> None:
        """Stdout artifact should be rendered with green border in logs partial."""
        stdout_content = "Hello from stdout!\nLine 2 of stdout"
        job_id = self._create_job_with_artifact(
            client,
            artifact_type="stdout",
            content=stdout_content,
            path="/logs/stdout.txt",
        )

        response = client.get(f"/partials/jobs/{job_id}/logs")
        assert response.status_code == 200

        html = response.text

        # Verify stdout section heading is present
        assert (
            "Stdout content" in html
        ), "Expected 'Stdout content' heading to be rendered when stdout artifact exists"

        # Verify green border styling for stdout
        assert (
            "border-green-500" in html
        ), "Expected 'border-green-500' class for stdout artifact styling"

        # Verify actual content is rendered
        assert (
            stdout_content in html
        ), f"Expected stdout content '{stdout_content}' to be rendered in HTML"

    def test_logs_partial_renders_stderr_artifact(self, client: TestClient) -> None:
        """Stderr artifact should be rendered with red border in logs partial."""
        stderr_content = "Error from stderr!\nWarning line 2"
        job_id = self._create_job_with_artifact(
            client,
            artifact_type="stderr",
            content=stderr_content,
            path="/logs/stderr.txt",
        )

        response = client.get(f"/partials/jobs/{job_id}/logs")
        assert response.status_code == 200

        html = response.text

        # Verify stderr section heading is present
        assert (
            "Stderr content" in html
        ), "Expected 'Stderr content' heading to be rendered when stderr artifact exists"

        # Verify red border styling for stderr
        assert (
            "border-red-500" in html
        ), "Expected 'border-red-500' class for stderr artifact styling"

        # Verify actual content is rendered
        assert (
            stderr_content in html
        ), f"Expected stderr content '{stderr_content}' to be rendered in HTML"

    def test_logs_partial_renders_both_stdout_and_stderr(
        self, client: TestClient
    ) -> None:
        """Both stdout and stderr artifacts should be rendered together."""
        import asyncio
        import os
        from pxq.storage import create_artifact

        # Create job first
        job_id = _create_job(client, command="python script.py")
        db_path = os.environ.get("PXQ_DB_PATH", ":memory:")

        # Add stdout artifact
        asyncio.run(
            create_artifact(
                db_path,
                job_id,
                artifact_type="stdout",
                path="/logs/stdout.txt",
                size_bytes=12,
                content="stdout data",
            )
        )

        # Add stderr artifact
        asyncio.run(
            create_artifact(
                db_path,
                job_id,
                artifact_type="stderr",
                path="/logs/stderr.txt",
                size_bytes=12,
                content="stderr data",
            )
        )

        response = client.get(f"/partials/jobs/{job_id}/logs")
        assert response.status_code == 200

        html = response.text

        # Both headings should be present
        assert "Stdout content" in html
        assert "Stderr content" in html

        # Both border colors should be present
        assert "border-green-500" in html
        assert "border-red-500" in html

        # Both contents should be rendered
        assert "stdout data" in html
        assert "stderr data" in html

    def test_logs_partial_omits_stdout_section_when_no_stdout_artifact(
        self, client: TestClient
    ) -> None:
        """Stdout section should be omitted when no stdout artifact exists."""
        import asyncio
        import os
        from pxq.storage import create_artifact

        # Create job with only stderr (no stdout)
        job_id = _create_job(client, command="error script")
        db_path = os.environ.get("PXQ_DB_PATH", ":memory:")

        asyncio.run(
            create_artifact(
                db_path,
                job_id,
                artifact_type="stderr",
                path="/logs/stderr.txt",
                size_bytes=8,
                content="error!",
            )
        )

        response = client.get(f"/partials/jobs/{job_id}/logs")
        assert response.status_code == 200

        html = response.text

        # Stderr should be present
        assert "Stderr content" in html
        assert "border-red-500" in html

        # Stdout section should NOT be present
        assert (
            "Stdout content" not in html
        ), "Expected 'Stdout content' heading to be absent when no stdout artifact exists"
        assert (
            "border-green-500" not in html
        ), "Expected 'border-green-500' class to be absent when no stdout artifact exists"

    def test_logs_partial_omits_stderr_section_when_no_stderr_artifact(
        self, client: TestClient
    ) -> None:
        """Stderr section should be omitted when no stderr artifact exists."""
        import asyncio
        import os
        from pxq.storage import create_artifact

        # Create job with only stdout (no stderr)
        job_id = _create_job(client, command="output script")
        db_path = os.environ.get("PXQ_DB_PATH", ":memory:")

        asyncio.run(
            create_artifact(
                db_path,
                job_id,
                artifact_type="stdout",
                path="/logs/stdout.txt",
                size_bytes=8,
                content="output",
            )
        )

        response = client.get(f"/partials/jobs/{job_id}/logs")
        assert response.status_code == 200

        html = response.text

        # Stdout should be present
        assert "Stdout content" in html
        assert "border-green-500" in html

        # Stderr section should NOT be present
        assert (
            "Stderr content" not in html
        ), "Expected 'Stderr content' heading to be absent when no stderr artifact exists"
        assert (
            "border-red-500" not in html
        ), "Expected 'border-red-500' class to be absent when no stderr artifact exists"

    def test_logs_partial_omits_both_when_no_stdout_nor_stderr(
        self, client: TestClient
    ) -> None:
        """Neither stdout nor stderr sections should be present when no artifacts."""
        # Create job with no stdout/stderr artifacts
        job_id = _create_job(client, command="no output script")

        response = client.get(f"/partials/jobs/{job_id}/logs")
        assert response.status_code == 200

        html = response.text

        # Neither heading should be present
        assert (
            "Stdout content" not in html
        ), "Expected 'Stdout content' heading to be absent when no stdout artifact exists"
        assert (
            "Stderr content" not in html
        ), "Expected 'Stderr content' heading to be absent when no stderr artifact exists"

        # Neither border color should be present
        assert (
            "border-green-500" not in html
        ), "Expected 'border-green-500' class to be absent when no stdout artifact exists"
        assert (
            "border-red-500" not in html
        ), "Expected 'border-red-500' class to be absent when no stderr artifact exists"

        # But the page should still render with other content
        assert "Recent events" in html  # Should still show events section

    def test_logs_partial_renders_empty_content_placeholder(
        self, client: TestClient
    ) -> None:
        """Artifact with empty content should show placeholder."""
        job_id = self._create_job_with_artifact(
            client, artifact_type="stdout", content="", path="/logs/empty.txt"
        )

        response = client.get(f"/partials/jobs/{job_id}/logs")
        assert response.status_code == 200

        html = response.text

        # Section should be present
        assert "Stdout content" in html

        # Empty content placeholder should be shown
        assert (
            "(no content)" in html
        ), "Expected '(no content)' placeholder for artifact with empty content"


class TestDashboardLogsPartialTerminalJobs:
    """Tests for stdout/stderr artifact rendering for completed/terminal jobs.

    These tests verify that artifacts remain visible in the dashboard
    even after the job has reached a terminal state (SUCCEEDED/FAILED/STOPPED).
    """

    def _create_terminal_job_with_artifacts(
        self,
        client: TestClient,
        final_status: str,
        stdout_content: str | None = None,
        stderr_content: str | None = None,
    ) -> int:
        """Create a job, transition it to terminal state, and add artifacts.

        Creates job directly in database with provider="_test" to avoid
        interference from the executor loop which processes "local" and "runpod" jobs.
        """
        import asyncio
        import os
        from pxq.storage import create_artifact, update_job_status, create_job
        from pxq.models import Job, JobStatus

        # Get the database path from environment
        db_path = os.environ.get("PXQ_DB_PATH", ":memory:")

        # Create job directly in database with "_test" provider to avoid executor interference
        # The executor only processes "local" and "runpod" providers
        job = Job(command="echo test", provider="_test")
        job = asyncio.run(create_job(db_path, job))
        job_id = job.id if job.id else 0

        # Transition to terminal state through valid intermediate states
        # State machine: QUEUED -> PROVISIONING -> UPLOADING -> RUNNING -> SUCCEEDED/FAILED -> STOPPING -> STOPPED
        if final_status == "succeeded":
            # QUEUED -> PROVISIONING -> UPLOADING -> RUNNING -> SUCCEEDED
            for status, msg in [
                (JobStatus.PROVISIONING, "Provisioning"),
                (JobStatus.UPLOADING, "Uploading"),
                (JobStatus.RUNNING, "Running"),
                (JobStatus.SUCCEEDED, "Job succeeded"),
            ]:
                asyncio.run(
                    update_job_status(
                        db_path,
                        job_id,
                        status,
                        message=msg,
                        pod_id="test-pod-123",
                        exit_code=0 if status == JobStatus.SUCCEEDED else None,
                    )
                )
        elif final_status == "failed":
            # QUEUED -> PROVISIONING -> UPLOADING -> RUNNING -> FAILED
            for status, msg in [
                (JobStatus.PROVISIONING, "Provisioning"),
                (JobStatus.UPLOADING, "Uploading"),
                (JobStatus.RUNNING, "Running"),
                (JobStatus.FAILED, "Job failed"),
            ]:
                asyncio.run(
                    update_job_status(
                        db_path,
                        job_id,
                        status,
                        message=msg,
                        pod_id="test-pod-123",
                        exit_code=1 if status == JobStatus.FAILED else None,
                    )
                )
        elif final_status == "stopped":
            # QUEUED -> PROVISIONING -> UPLOADING -> RUNNING -> SUCCEEDED -> STOPPING -> STOPPED
            # Full managed job lifecycle to STOPPED state
            states_to_run = [
                (JobStatus.PROVISIONING, "Provisioning", "test-pod-123", None),
                (JobStatus.UPLOADING, "Uploading", "test-pod-123", None),
                (JobStatus.RUNNING, "Running", "test-pod-123", None),
                (JobStatus.SUCCEEDED, "Job succeeded", "test-pod-123", 0),
                (JobStatus.STOPPING, "Stopping managed pod", "test-pod-123", None),
                (JobStatus.STOPPED, "Job stopped", None, None),
            ]
            for status, msg, pod_id_val, exit_code_val in states_to_run:
                asyncio.run(
                    update_job_status(
                        db_path,
                        job_id,
                        status,
                        message=msg,
                        pod_id=pod_id_val,
                        exit_code=exit_code_val,
                    )
                )

        # Add stdout artifact if provided
        if stdout_content is not None:
            asyncio.run(
                create_artifact(
                    db_path,
                    job_id,
                    artifact_type="stdout",
                    path="/workspace/pxq_stdout.log",
                    size_bytes=len(stdout_content),
                    content=stdout_content,
                )
            )

        # Add stderr artifact if provided
        if stderr_content is not None:
            asyncio.run(
                create_artifact(
                    db_path,
                    job_id,
                    artifact_type="stderr",
                    path="/workspace/pxq_stderr.log",
                    size_bytes=len(stderr_content),
                    content=stderr_content,
                )
            )

        return job_id

    def test_terminal_job_succeeded_renders_stdout_and_stderr(
        self, client: TestClient
    ) -> None:
        """Completed (SUCCEEDED) job should still render stdout/stderr artifacts."""
        stdout_content = "Job completed successfully\nOutput line 2"
        stderr_content = "Warning: deprecated API\nWarning: slow query"

        job_id = self._create_terminal_job_with_artifacts(
            client,
            final_status="succeeded",
            stdout_content=stdout_content,
            stderr_content=stderr_content,
        )

        response = client.get(f"/partials/jobs/{job_id}/logs")
        assert response.status_code == 200

        html = response.text

        # Both headings should be present
        assert "Stdout content" in html
        assert "Stderr content" in html

        # Both border colors should be present
        assert "border-green-500" in html
        assert "border-red-500" in html

        # Both contents should be rendered
        assert stdout_content in html
        assert stderr_content in html

    def test_terminal_job_stopped_renders_stdout_and_stderr(
        self, client: TestClient
    ) -> None:
        """Stopped (STOPPED) managed job should still render stdout/stderr artifacts."""
        stdout_content = "Running...\nProcessing data"
        stderr_content = "STDERR line 001\nSTDERR line 002"

        job_id = self._create_terminal_job_with_artifacts(
            client,
            final_status="stopped",
            stdout_content=stdout_content,
            stderr_content=stderr_content,
        )

        response = client.get(f"/partials/jobs/{job_id}/logs")
        assert response.status_code == 200

        html = response.text

        # Both headings should be present
        assert "Stdout content" in html
        assert "Stderr content" in html

        # Verify red border for stderr (critical for stderr visibility)
        assert "border-red-500" in html

        # Verify stderr content with expected pattern
        assert "STDERR line" in html

    def test_terminal_job_failed_renders_stderr(self, client: TestClient) -> None:
        """Failed job should still render stderr artifact with error details."""
        stderr_content = "Error: Connection refused\nTraceback (most recent call last)"

        job_id = self._create_terminal_job_with_artifacts(
            client,
            final_status="failed",
            stdout_content=None,
            stderr_content=stderr_content,
        )

        response = client.get(f"/partials/jobs/{job_id}/logs")
        assert response.status_code == 200

        html = response.text

        # Stderr should be present
        assert "Stderr content" in html
        assert "border-red-500" in html
        assert stderr_content in html

        # Stdout section should NOT be present (no stdout artifact)
        assert "Stdout content" not in html


class TestDashboardLogsPartialJobArtifactShape:
    """Tests for dashboard rendering with post-fix artifact shape.

    These tests verify that the dashboard correctly renders exactly one
    stdout block and one stderr block when persistence produces a single
    artifact row for each stream (after the dedup fix is applied).
    """

    def test_logs_partial_renders_one_stdout_and_one_stderr_with_log_rows(
        self, client: TestClient
    ) -> None:
        """Jobs with single stdout/stderr rows plus regular log rows render correctly.
        This mocks the post-fix artifact shape where:
        - One stdout artifact row persists
        - One stderr artifact row persists
        - Multiple regular log artifact rows persist
        The dashboard should render exactly one stdout block and one stderr block.
        """
        import asyncio
        import os
        from pxq.storage import create_artifact
        from pxq.storage import update_job_status
        from pxq.models import JobStatus

        # Create job first
        job_id = _create_job(client, command="python script.py")
        db_path = os.environ.get("PXQ_DB_PATH", ":memory:")

        # Use valid state transitions: QUEUED -> PROVISIONING -> UPLOADING -> RUNNING -> SUCCEEDED
        asyncio.run(
            update_job_status(
                db_path,
                job_id,
                JobStatus.PROVISIONING,
                message="Provisioning",
                pod_id="test-pod-123",
            )
        )
        asyncio.run(
            update_job_status(
                db_path,
                job_id,
                JobStatus.UPLOADING,
                message="Uploading",
                pod_id="test-pod-123",
            )
        )
        asyncio.run(
            update_job_status(
                db_path,
                job_id,
                JobStatus.RUNNING,
                message="Running",
                pod_id="test-pod-123",
            )
        )
        asyncio.run(
            update_job_status(
                db_path,
                job_id,
                JobStatus.SUCCEEDED,
                message="Job succeeded",
                pod_id="test-pod-123",
                exit_code=0,
            )
        )

        # Seed artifacts as they would appear after post-fix persistence:
        # 1. Single stdout artifact (final row only, no duplicates)
        asyncio.run(
            create_artifact(
                db_path,
                job_id,
                artifact_type="stdout",
                path="/workspace/pxq_stdout.log",
                size_bytes=37,
                content="Starting job...\nJob completed successfully!\n",
            )
        )

        # 2. Single stderr artifact (final row only, no duplicates)
        asyncio.run(
            create_artifact(
                db_path,
                job_id,
                artifact_type="stderr",
                path="/workspace/pxq_stderr.log",
                size_bytes=24,
                content="Warning: deprecated flag\n",
            )
        )

        # 3. Multiple regular log artifacts (non stdout/stderr)
        asyncio.run(
            create_artifact(
                db_path,
                job_id,
                artifact_type="log",
                path="/workspace/app.log",
                size_bytes=42,
                content="[INFO] Starting application\n[INFO] Ready.\n",
            )
        )
        asyncio.run(
            create_artifact(
                db_path,
                job_id,
                artifact_type="log",
                path="/workspace/debug.log",
                size_bytes=31,
                content="[DEBUG] Trace level enabled\n",
            )
        )

        # Render logs partial
        response = client.get(f"/partials/jobs/{job_id}/logs")
        assert response.status_code == 200
        html = response.text

        # --- Assertions for stdout/stderr rendering ---
        # Exactly ONE stdout section heading (not duplicated)
        assert (
            html.count("Stdout content") == 1
        ), f"Expected exactly 1 'Stdout content' heading, found {html.count('Stdout content')}"
        # Exactly ONE stdout block (one <pre> element)
        stdout_pre_count = html.count("border-green-500")
        assert (
            stdout_pre_count == 1
        ), f"Expected exactly 1 stdout <pre> block with 'border-green-500', found {stdout_pre_count}"
        # Stdout content fully rendered
        assert "Starting job..." in html
        assert "Job completed successfully!" in html

        # Exactly ONE stderr section heading (not duplicated)
        assert (
            html.count("Stderr content") == 1
        ), f"Expected exactly 1 'Stderr content' heading, found {html.count('Stderr content')}"
        # Exactly ONE stderr block (one <pre> element)
        stderr_pre_count = html.count("border-red-500")
        assert (
            stderr_pre_count == 1
        ), f"Expected exactly 1 stderr <pre> block with 'border-red-500', found {stderr_pre_count}"
        # Stderr content fully rendered
        assert "Warning: deprecated flag" in html

        # Regular log artifacts are listed (not rendered as pre blocks)
        assert "/workspace/app.log" in html
        assert "/workspace/debug.log" in html

        # Job events present
        assert "Provisioning" in html
        assert "Job succeeded" in html
