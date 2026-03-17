# -*- coding: utf-8 -*-
"""Tests for pxq cancel and stop commands.

This module verifies the CLI commands for cancelling queued jobs
and stopping running jobs.
"""

import json

import pytest
from typer.testing import CliRunner
from unittest import mock

import httpx

from pxq.cli import app
from pxq.models import JobStatus

runner = CliRunner()


def make_fake_job(
    job_id: int = 1,
    command: str = "echo hello",
    status: JobStatus = JobStatus.QUEUED,
    provider: str = "local",
) -> dict:
    """Create a fake job response dict for mocking."""
    return {
        "id": job_id,
        "command": command,
        "status": status.value,
        "provider": provider,
        "managed": False,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "pod_id": None,
        "workdir": None,
        "gpu_type": None,
        "cpu_count": None,
        "volume_id": None,
        "error_message": None,
    }


def make_mock_response(data: dict) -> mock.Mock:
    """Create a mock HTTP response."""
    mock_response = mock.Mock()
    mock_response.json.return_value = data
    mock_response.raise_for_status = mock.Mock()
    return mock_response


# ---------------------------------------------------------------------------
# cancel command tests
# ---------------------------------------------------------------------------


def test_cancel_queued_job() -> None:
    """Test cancelling a queued job."""
    fake_job = make_fake_job(job_id=42, status=JobStatus.CANCELLED)
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(app, ["cancel", "42"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["id"] == 42
    assert output["status"] == "cancelled"


def test_cancel_nonexistent_job() -> None:
    """Test cancelling a job that does not exist."""
    mock_response = mock.Mock()
    mock_response.status_code = 404
    mock_response.json.return_value = {"detail": "Job not found"}
    mock_response.text = "Not Found"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found",
        request=mock.Mock(),
        response=mock_response,
    )

    with mock.patch(
        "httpx.AsyncClient.request", side_effect=mock_response.raise_for_status
    ):
        result = runner.invoke(app, ["cancel", "999"])

    assert result.exit_code == 1
    assert "Job not found" in result.stderr


def test_cancel_not_queued_job() -> None:
    """Test cancelling a job that is not in queued state."""
    mock_response = mock.Mock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"detail": "Job is not in queued status"}
    mock_response.text = "Bad Request"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Bad Request",
        request=mock.Mock(),
        response=mock_response,
    )

    with mock.patch(
        "httpx.AsyncClient.request", side_effect=mock_response.raise_for_status
    ):
        result = runner.invoke(app, ["cancel", "1"])

    assert result.exit_code == 1
    assert "Job is not in queued status" in result.stderr


def test_cancel_connection_error() -> None:
    """Test cancel command handles connection errors gracefully."""

    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection failed")

    with mock.patch("httpx.AsyncClient.request", side_effect=_raise):
        result = runner.invoke(app, ["cancel", "1"])

    assert result.exit_code == 1
    assert "Failed to connect" in result.stderr


# ---------------------------------------------------------------------------
# stop command tests
# ---------------------------------------------------------------------------


def test_stop_single_running_job() -> None:
    """Test stopping the single running job."""
    fake_job = make_fake_job(job_id=10, status=JobStatus.STOPPED)
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(app, ["stop"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["id"] == 10
    assert output["status"] == "stopped"


def test_stop_no_running_jobs() -> None:
    """Test stop command when no running jobs exist."""
    mock_response = mock.Mock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"detail": "No running jobs found"}
    mock_response.text = "Bad Request"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Bad Request",
        request=mock.Mock(),
        response=mock_response,
    )

    with mock.patch(
        "httpx.AsyncClient.request", side_effect=mock_response.raise_for_status
    ):
        result = runner.invoke(app, ["stop"])

    assert result.exit_code == 1
    assert "No running jobs found" in result.stderr


def test_stop_multiple_running_jobs() -> None:
    """Test stop command when multiple running jobs exist."""
    mock_response = mock.Mock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"detail": "Multiple running jobs found"}
    mock_response.text = "Bad Request"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Bad Request",
        request=mock.Mock(),
        response=mock_response,
    )

    with mock.patch(
        "httpx.AsyncClient.request", side_effect=mock_response.raise_for_status
    ):
        result = runner.invoke(app, ["stop"])

    assert result.exit_code == 1
    assert "Multiple running jobs found" in result.stderr


def test_stop_connection_error() -> None:
    """Test stop command handles connection errors gracefully."""

    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection failed")

    with mock.patch("httpx.AsyncClient.request", side_effect=_raise):
        result = runner.invoke(app, ["stop"])

    assert result.exit_code == 1
    assert "Failed to connect" in result.stderr


def test_cancel_error_fallback_non_json() -> None:
    """Test cancel command handles non-JSON error responses."""
    mock_response = mock.Mock()
    mock_response.status_code = 500
    mock_response.json.side_effect = Exception("Not JSON")
    mock_response.text = "Internal Server Error"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Internal Server Error",
        request=mock.Mock(),
        response=mock_response,
    )

    with mock.patch(
        "httpx.AsyncClient.request", side_effect=mock_response.raise_for_status
    ):
        result = runner.invoke(app, ["cancel", "1"])

    assert result.exit_code == 1
    assert "HTTP 500" in result.stderr
    assert "Internal Server Error" in result.stderr


def test_stop_non_json_error() -> None:
    """Test stop command handles non-JSON error responses."""
    mock_response = mock.Mock()
    mock_response.status_code = 500
    mock_response.json.side_effect = Exception("Not JSON")
    mock_response.text = "Internal Server Error"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Internal Server Error",
        request=mock.Mock(),
        response=mock_response,
    )

    with mock.patch(
        "httpx.AsyncClient.request", side_effect=mock_response.raise_for_status
    ):
        result = runner.invoke(app, ["stop"])

    assert result.exit_code == 1
    assert "HTTP 500" in result.stderr
    assert "Internal Server Error" in result.stderr


# ---------------------------------------------------------------------------
# Regression tests for stop-by-job-id feature (Task 4)
# ---------------------------------------------------------------------------


def test_stop_by_job_id() -> None:
    """Test stopping a specific job by job id.

    This verifies that pxq stop 42 works correctly with the targeted stop API.
    """
    fake_job = make_fake_job(job_id=42, status=JobStatus.STOPPED)
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(app, ["stop", "42"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["id"] == 42
    assert output["status"] == "stopped"


def test_stop_by_job_id_not_found() -> None:
    """Test stop with job id when job does not exist."""
    mock_response = mock.Mock()
    mock_response.status_code = 404
    mock_response.json.return_value = {"detail": "Job not found"}
    mock_response.text = "Not Found"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found",
        request=mock.Mock(),
        response=mock_response,
    )

    with mock.patch(
        "httpx.AsyncClient.request", side_effect=mock_response.raise_for_status
    ):
        result = runner.invoke(app, ["stop", "999"])

    assert result.exit_code == 1
    assert "Job not found" in result.stderr


def test_stop_by_job_id_not_running() -> None:
    """Test stop with job id when job is not in running state."""
    mock_response = mock.Mock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"detail": "Job is not in running status"}
    mock_response.text = "Bad Request"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Bad Request",
        request=mock.Mock(),
        response=mock_response,
    )

    with mock.patch(
        "httpx.AsyncClient.request", side_effect=mock_response.raise_for_status
    ):
        result = runner.invoke(app, ["stop", "1"])

    assert result.exit_code == 1
    assert "Job is not in running status" in result.stderr


def test_stop_by_job_id_non_managed_completion_pending() -> None:
    """Test stopping a non-managed completion-pending job by id.

    Non-managed jobs stay in RUNNING status after remote command completion
    until explicit pxq stop. This test verifies that pxq stop JOB_ID works
    for completion-pending jobs that have exit_code set but remain RUNNING.
    """
    fake_job = {
        "id": 42,
        "command": "python train.py",
        "status": "stopped",
        "provider": "runpod",
        "managed": False,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "started_at": "2024-01-01T00:00:00Z",
        "finished_at": None,
        "exit_code": 0,
        "pod_id": "pod-abc123",
        "workdir": None,
        "gpu_type": "RTX4090:1",
        "cpu_count": None,
        "volume_id": None,
        "error_message": None,
    }
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(app, ["stop", "42"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["id"] == 42
    assert output["status"] == "stopped"
    assert output["exit_code"] == 0
    assert output["managed"] is False
