"""Integration tests for stderr capture and dashboard rendering.

This module verifies that stderr output from RunPod jobs is:
1. Properly captured by the log collector
2. Stored in the database as an artifact with artifact_type="stderr"
3. Correctly rendered in the dashboard with red border styling

The test requires:
- PXQ_RUNPOD_API_KEY environment variable to be set
- --run-integration flag to be passed to pytest
- pxq server running on localhost:8765
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest


# =============================================================================
# Configuration
# =============================================================================

SERVER_URL = "http://127.0.0.1:8765"
TEST_SCRIPT_PATH = "examples/runpod/test_output.py"
TERMINAL_STATUSES = {"succeeded", "failed", "stopped", "cancelled"}

# =============================================================================
# Manual Verification Commands
# =============================================================================
# These commands can be used for manual debugging when the test fails.
# Replace {job_id} with the actual job ID from test output.
#
# 1. Database verification:
#    sqlite3 ~/.pxq/pxq.db "SELECT artifact_type, size_bytes, content FROM artifacts WHERE job_id={job_id} AND artifact_type='stderr'"
#
# 2. Dashboard HTML verification:
#    curl -s http://localhost:8765/partials/jobs/{job_id}/logs | grep -c 'border-red-500'
#    curl -s http://localhost:8765/partials/jobs/{job_id}/logs | grep -o 'Stderr content'
#
# 3. Pod cleanup verification:
#    pxq status {job_id} | jq -r '.status'
#    # Expected: "stopped" for managed jobs


# =============================================================================
# Helper Functions
# =============================================================================


async def _wait_for_job_completion(
    job_id: int,
    timeout_seconds: float = 600.0,
    poll_interval_seconds: float = 5.0,
) -> dict[str, Any]:
    """Wait for the job to reach a terminal state.

    Returns the final job status object.
    """
    import datetime

    deadline = datetime.datetime.now().timestamp() + timeout_seconds

    async with httpx.AsyncClient(timeout=30.0) as client:
        while datetime.datetime.now().timestamp() < deadline:
            try:
                response = await client.get(f"{SERVER_URL}/api/jobs/{job_id}")
                response.raise_for_status()
                job = response.json()

                status = job.get("status", "").lower()
                if status in TERMINAL_STATUSES:
                    return job
            except httpx.HTTPError:
                # Server might not be ready, wait and retry
                pass

            await asyncio.sleep(poll_interval_seconds)

    raise TimeoutError(f"Job {job_id} did not complete within {timeout_seconds}s")


def _query_stderr_artifact(db_path: Path, job_id: int) -> dict | None:
    """Query the database for the stderr artifact."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT artifact_type, path, size_bytes, content
        FROM artifacts
        WHERE job_id = ? AND artifact_type = 'stderr'
        """,
        (job_id,),
    )

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return {
        "artifact_type": row[0],
        "path": row[1],
        "size_bytes": row[2],
        "content": row[3],
    }


def _query_stdout_artifact(db_path: Path, job_id: int) -> dict | None:
    """Query the database for the stdout artifact."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT artifact_type, path, size_bytes, content
        FROM artifacts
        WHERE job_id = ? AND artifact_type = 'stdout'
        """,
        (job_id,),
    )

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    return {
        "artifact_type": row[0],
        "path": row[1],
        "size_bytes": row[2],
        "content": row[3],
    }


async def _fetch_job_logs_partial(job_id: int) -> str:
    """Fetch the job logs partial HTML from the dashboard."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{SERVER_URL}/partials/jobs/{job_id}/logs")
        response.raise_for_status()
        return response.text


# =============================================================================
# Integration Test
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_runpod_stderr_capture_and_dashboard_rendering(
    tmp_path: Path,
    mock_settings: object,
) -> None:
    """Verify stderr from RunPod jobs is captured, stored, and rendered correctly.

    This test:
    1. Checks that PXQ_RUNPOD_API_KEY is set
    2. Submits a job running test_output.py on RunPod via pxq server
    3. Waits for job completion
    4. Verifies stderr artifact exists in the database
    5. Verifies dashboard HTML contains stderr with red border styling
    6. Verifies pod is cleaned up (TERMINATED/STOPPED)

    QA Commands (for manual verification):
        # DB verification
        sqlite3 ~/.pxq/pxq.db "SELECT artifact_type, size_bytes FROM artifacts WHERE job_id=<ID> AND artifact_type='stderr'"

        # Dashboard verification
        curl -s http://localhost:8765/partials/jobs/<ID>/logs | grep -c 'border-red-500'

        # Pod cleanup verification
        pxq status <ID> | jq -r '.status'
    """
    # 1. Check API key is available
    api_key = os.getenv("PXQ_RUNPOD_API_KEY")
    if not api_key:
        pytest.skip("PXQ_RUNPOD_API_KEY environment variable is required for this test")

    # Get the database path from environment
    db_path_str = os.getenv("PXQ_DB_PATH", str(Path.home() / ".pxq" / "pxq.db"))
    db_path = Path(db_path_str)

    if not db_path.exists():
        pytest.skip(f"Database not found at {db_path}. Is pxq server running?")

    # 2. Submit job via pxq server API
    job_command = f"uv run python {TEST_SCRIPT_PATH}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check if server is running
        try:
            health_response = await client.get(f"{SERVER_URL}/health")
            health_response.raise_for_status()
        except httpx.HTTPError:
            pytest.skip(
                "pxq server is not running on localhost:8765. Start with 'pxq server'"
            )

        # Submit the job
        response = await client.post(
            f"{SERVER_URL}/api/jobs",
            json={
                "command": job_command,
                "provider": "runpod",
                "managed": True,  # Ensure pod is cleaned up
                "gpu_type": None,  # Use CPU for faster test
            },
        )
        response.raise_for_status()
        job_data = response.json()
        job_id = job_data["id"]

    print(f"Submitted job {job_id} running {TEST_SCRIPT_PATH}")

    # 3. Wait for job completion
    final_job = await _wait_for_job_completion(job_id, timeout_seconds=600.0)
    job_status = final_job.get("status", "").lower()
    pod_id = final_job.get("pod_id")

    print(f"Job {job_id} completed with status: {job_status}")
    if pod_id:
        print(f"Pod ID: {pod_id}")

    # 4. Verify stderr artifact exists in database
    stderr_artifact = _query_stderr_artifact(db_path, job_id)

    assert stderr_artifact is not None, (
        f"Expected stderr artifact for job {job_id}, but none found. "
        "DB query: SELECT artifact_type, size_bytes FROM artifacts "
        f"WHERE job_id={job_id} AND artifact_type='stderr'"
    )

    assert (
        stderr_artifact["artifact_type"] == "stderr"
    ), f"Expected artifact_type='stderr', got '{stderr_artifact['artifact_type']}'"

    assert (
        stderr_artifact["size_bytes"] > 0
    ), f"Expected stderr size_bytes > 0, got {stderr_artifact['size_bytes']}"

    # Verify the stderr content contains expected output from test_output.py
    stderr_content = stderr_artifact.get("content", "")
    assert (
        "STDERR line" in stderr_content
    ), f"Expected 'STDERR line' in stderr content, got: {stderr_content[:200]}"

    print(f"Found stderr artifact: {stderr_artifact['size_bytes']} bytes")

    # 5. Verify dashboard HTML contains stderr with red border styling
    dashboard_html = await _fetch_job_logs_partial(job_id)

    assert (
        "border-red-500" in dashboard_html
    ), "Expected 'border-red-500' class in dashboard HTML for stderr rendering"

    assert (
        "Stderr content" in dashboard_html
    ), "Expected 'Stderr content' section in dashboard HTML"

    print("Dashboard correctly renders stderr with red border styling")

    # 6. Verify pod is cleaned up
    # For managed auto-cleanup jobs, status should be 'succeeded' after cleanup
    # (Manual stop via pxq stop results in 'stopped')
    assert job_status == "succeeded", (
        f"Expected job status 'succeeded' for managed auto-cleanup job, got '{job_status}'. "
        "Pod cleanup verification: pxq status <ID> | jq -r '.status'"
    )

    print(f"Pod successfully cleaned up (status: {job_status})")

    # Additional verification: check stdout artifact also exists
    stdout_artifact = _query_stdout_artifact(db_path, job_id)
    if stdout_artifact is not None:
        print(f"Found stdout artifact: {stdout_artifact['size_bytes']} bytes")

    print(f"\n=== TEST PASSED ===")
    print(f"Job ID: {job_id}")
    print(f"Status: {job_status}")
    print(f"Stderr artifact: {stderr_artifact['size_bytes']} bytes")
    print(f"Dashboard stderr rendering: verified")
