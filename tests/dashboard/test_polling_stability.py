"""Tests for dashboard polling stability - regression coverage for /?all=true.

This module ensures that partial and full dashboard views share the same
DB state semantics to prevent flicker during HTMX polling.

Regression scenario:
- User visits /?all=true (full view with all jobs including terminal)
- HTMX polls /partials/jobs?all=true (partial view)
- Both endpoints must return identical job lists when DB state hasn't changed
"""

from __future__ import annotations

import pytest
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


class TestPollingStability:
    """Regression tests for /?all=true polling stability.

    These tests ensure that:
    1. / and /partials/jobs share the same include_all semantics
    2. Repeated requests to /partials/jobs?all=true return identical output
    3. No flicker occurs when switching between views or during auto-refresh
    """

    def test_partial_and_full_view_share_same_include_all_semantics(
        self, client: TestClient
    ) -> None:
        """Test that /?all=true and /partials/jobs?all=true use identical filtering logic.

        This is the core regression test for the flicker bug where partial and
        full views would show different job lists even though they should share
        the same DB state and filtering semantics.
        """
        import asyncio
        import os
        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        # Create two jobs
        job1_id = _create_job(client, command="echo job1")
        job2_id = _create_job(client, command="echo job2")

        # Make job2 succeed through valid path (terminal state)
        db_path = os.environ["PXQ_DB_PATH"]
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.RUNNING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.SUCCEEDED))

        # Fetch full view with all=true (should show both jobs)
        full_response = client.get("/?all=true")
        assert full_response.status_code == 200
        full_html = full_response.text

        # Fetch partial view with all=true (should show identical jobs)
        partial_response = client.get("/partials/jobs?all=true")
        assert partial_response.status_code == 200
        partial_html = partial_response.text

        # Both should include both job IDs
        assert f">{job1_id}<" in full_html, "Full view should include job1"
        assert f">{job1_id}<" in partial_html, "Partial view should include job1"
        assert f">{job2_id}<" in full_html, "Full view should include job2 (terminal)"
        assert (
            f">{job2_id}<" in partial_html
        ), "Partial view should include job2 (terminal)"

    def test_partial_and_full_view_both_exclude_terminal_without_all(
        self, client: TestClient
    ) -> None:
        """Test that both views exclude terminal jobs when all=false (default).

        This ensures the default view_behavior is consistent between
        full dashboard and partial refresh.
        """
        import asyncio
        import os
        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        # Create two jobs
        job1_id = _create_job(client, command="echo job1")
        job2_id = _create_job(client, command="echo job2")

        # Make job2 succeed (terminal state)
        db_path = os.environ["PXQ_DB_PATH"]
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.RUNNING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.SUCCEEDED))

        # Fetch full view without all (should show only job1)
        full_response = client.get("/")
        assert full_response.status_code == 200
        full_html = full_response.text

        # Fetch partial view without all (should show identical jobs)
        partial_response = client.get("/partials/jobs")
        assert partial_response.status_code == 200
        partial_html = partial_response.text

        # Both should include job1 (non-terminal)
        assert f">{job1_id}<" in full_html, "Full view should include job1"
        assert f">{job1_id}<" in partial_html, "Partial view should include job1"

        # Both should exclude job2 (terminal) - NOT in unfiltered view
        assert (
            f">{job2_id}<" not in full_html
        ), "Full view should exclude terminal job2 by default"
        assert (
            f">{job2_id}<" not in partial_html
        ), "Partial view should exclude terminal job2 by default"

    def test_repeated_partial_jobs_requests_return_identical_output(
        self, client: TestClient
    ) -> None:
        """Test that repeated /partials/jobs?all=true requests return identical output.

        This verifies the QA scenario:
        ```bash
        curl -s 'http://127.0.0.1:8765/partials/jobs?all=true' > /tmp/pxq-partial-a.html
        curl -s 'http://127.0.0.1:8765/partials/jobs?all=true' > /tmp/pxq-partial-b.html
        cmp /tmp/pxq-partial-a.html /tmp/pxq-partial-b.html && echo stable
        ```

        Without this fix, timing-sensitive DB reads could cause flicker.
        """
        import asyncio
        import os
        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        # Create a job that becomes terminal
        job_id = _create_job(client, command="echo terminal")
        db_path = os.environ["PXQ_DB_PATH"]
        asyncio.run(update_job_status(db_path, job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.RUNNING))
        asyncio.run(update_job_status(db_path, job_id, JobStatus.SUCCEEDED))

        # Make multiple requests to /partials/jobs?all=true
        responses = []
        for _ in range(3):
            response = client.get("/partials/jobs?all=true")
            assert response.status_code == 200
            responses.append(response.text)

        # All responses should be identical (no flicker)
        assert (
            responses[0] == responses[1] == responses[2]
        ), "Repeated /partials/jobs?all=true requests should return identical HTML"

        # All should contain the terminal job
        for html in responses:
            assert f">{job_id}<" in html, "Terminal job should be visible with all=true"

    def test_repeated_partial_jobs_without_all_are_stable(
        self, client: TestClient
    ) -> None:
        """Test that /partials/jobs without all parameter also returns stable output.

        Ensures default behavior (excluding terminal jobs) is also stable.
        """
        import asyncio
        import os
        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        # Create jobs - one terminal, one active
        job1_id = _create_job(client, command="echo active")
        job2_id = _create_job(client, command="echo terminal")

        db_path = os.environ["PXQ_DB_PATH"]
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.RUNNING))
        asyncio.run(update_job_status(db_path, job2_id, JobStatus.SUCCEEDED))

        # Make multiple requests to /partials/jobs (without all)
        responses = []
        for _ in range(3):
            response = client.get("/partials/jobs")
            assert response.status_code == 200
            responses.append(response.text)

        # All responses should be identical
        assert (
            responses[0] == responses[1] == responses[2]
        ), "Repeated /partials/jobs requests should return identical HTML"

        # All should contain active job but not terminal job
        for html in responses:
            assert f">{job1_id}<" in html, "Active job should be visible"
            assert (
                f">{job2_id}<" not in html
            ), "Terminal job should be hidden by default"

    def test_job_lifecycle_reflected_consistently_across_views(
        self, client: TestClient
    ) -> None:
        """Test that job status changes are consistently reflected in both views.

        This ensures the regression doesn't reappear when jobs transition
        between states during auto-refresh.
        """
        import asyncio
        import os
        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        job_id = _create_job(client, command="echo lifecycle")
        db_path = os.environ["PXQ_DB_PATH"]

        # State transitions to test
        transitions = [
            (JobStatus.PROVISIONING, "Provisioning pod"),
            (JobStatus.UPLOADING, "Uploading"),
            (JobStatus.RUNNING, "Running job"),
            (JobStatus.SUCCEEDED, "Job completed"),
        ]

        for new_status, message in transitions:
            asyncio.run(update_job_status(db_path, job_id, new_status, message=message))

            # Fetch both views at each transition point
            full_response = client.get("/?all=true")
            partial_response = client.get("/partials/jobs?all=true")

            assert full_response.status_code == 200
            assert partial_response.status_code == 200

            full_html = full_response.text
            partial_html = partial_response.text

            # Both views should contain the job ID at all stages
            assert (
                f">{job_id}<" in full_html
            ), f"Full view should show job at {new_status.value}"
            assert (
                f">{job_id}<" in partial_html
            ), f"Partial view should show job at {new_status.value}"

            # Both views should contain the same status
            assert (
                f">{new_status.value}<" in full_html
            ), f"Full view should show {new_status.value}"
            assert (
                f">{new_status.value}<" in partial_html
            ), f"Partial view should show {new_status.value}"

    def test_default_view_shows_running_hides_succeeded(
        self, client: TestClient
    ) -> None:
        """Test that default view shows RUNNING jobs but hides SUCCEEDED jobs.

        This verifies the visibility semantics:
        - Non-managed completion-pending jobs (RUNNING) are visible by default
        - Managed success jobs (SUCCEEDED) are hidden by default as terminal
        """
        import asyncio
        import os
        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        running_job_id = _create_job(client, command="echo running")
        succeeded_job_id = _create_job(client, command="echo succeeded")

        db_path = os.environ["PXQ_DB_PATH"]
        asyncio.run(
            update_job_status(db_path, succeeded_job_id, JobStatus.PROVISIONING)
        )
        asyncio.run(update_job_status(db_path, succeeded_job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, succeeded_job_id, JobStatus.RUNNING))
        asyncio.run(update_job_status(db_path, succeeded_job_id, JobStatus.SUCCEEDED))

        asyncio.run(update_job_status(db_path, running_job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, running_job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, running_job_id, JobStatus.RUNNING))

        full_response = client.get("/")
        assert full_response.status_code == 200
        full_html = full_response.text

        assert (
            f">{running_job_id}<" in full_html
        ), "RUNNING job should be visible by default"
        assert (
            f">{succeeded_job_id}<" not in full_html
        ), "SUCCEEDED job should be hidden by default"

        partial_response = client.get("/partials/jobs")
        assert partial_response.status_code == 200
        partial_html = partial_response.text

        assert (
            f">{running_job_id}<" in partial_html
        ), "Partial view should show RUNNING job"
        assert (
            f">{succeeded_job_id}<" not in partial_html
        ), "Partial view should hide SUCCEEDED job"

    def test_all_true_shows_both_running_and_succeeded(
        self, client: TestClient
    ) -> None:
        """Test that all=true shows both RUNNING and SUCCEEDED jobs."""
        import asyncio
        import os
        from pxq.models import JobStatus
        from pxq.storage import update_job_status

        running_job_id = _create_job(client, command="echo running")
        succeeded_job_id = _create_job(client, command="echo succeeded")

        db_path = os.environ["PXQ_DB_PATH"]
        asyncio.run(
            update_job_status(db_path, succeeded_job_id, JobStatus.PROVISIONING)
        )
        asyncio.run(update_job_status(db_path, succeeded_job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, succeeded_job_id, JobStatus.RUNNING))
        asyncio.run(update_job_status(db_path, succeeded_job_id, JobStatus.SUCCEEDED))

        asyncio.run(update_job_status(db_path, running_job_id, JobStatus.PROVISIONING))
        asyncio.run(update_job_status(db_path, running_job_id, JobStatus.UPLOADING))
        asyncio.run(update_job_status(db_path, running_job_id, JobStatus.RUNNING))

        full_response = client.get("/?all=true")
        assert full_response.status_code == 200
        full_html = full_response.text

        assert f">{running_job_id}<" in full_html, "RUNNING job visible with all=true"
        assert (
            f">{succeeded_job_id}<" in full_html
        ), "SUCCEEDED job visible with all=true"

        partial_response = client.get("/partials/jobs?all=true")
        assert partial_response.status_code == 200
        partial_html = partial_response.text

        assert (
            f">{running_job_id}<" in partial_html
        ), "Partial view shows RUNNING with all=true"
        assert (
            f">{succeeded_job_id}<" in partial_html
        ), "Partial view shows SUCCEEDED with all=true"
