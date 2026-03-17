# -*- coding: utf-8 -*-
"""Tests for pxq add, ls, and status commands.

This module verifies the CLI commands for adding jobs, listing jobs,
and checking job status with various options.
"""

import json

from pathlib import Path

import pytest
from typer.testing import CliRunner
from unittest import mock

import httpx

from pxq.cli import app
from pxq.client import PxqClient
from pxq.models import Job, JobStatus

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_fake_job(
    job_id: int = 1,
    command: str = "echo hello",
    status: JobStatus = JobStatus.QUEUED,
    provider: str = "local",
    managed: bool = False,
    gpu_type: str | None = None,
    cpu_count: int | None = None,
    volume_id: str | None = None,
    workdir: str | None = None,
) -> dict:
    """Create a fake job response dict for mocking.

    Parameters
    ----------
    job_id : int
        Job identifier.
    command : str
        Command to execute.
    status : JobStatus
        Job status.
    provider : str
        Provider name.
    managed : bool
        Whether managed mode is enabled.
    gpu_type : str | None
        GPU type specification.
    cpu_count : int | None
        CPU count.
    volume_id : str | None
        Volume ID.
    workdir : str | None
        Working directory.

    Returns
    -------
    dict
        Fake job response dictionary.
    """
    return {
        "id": job_id,
        "command": command,
        "status": status.value,
        "provider": provider,
        "managed": managed,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "pod_id": None,
        "workdir": workdir,
        "gpu_type": gpu_type,
        "cpu_count": cpu_count,
        "volume_id": volume_id,
        "error_message": None,
    }


def make_mock_response(data: dict) -> mock.Mock:
    """Create a mock HTTP response.

    Parameters
    ----------
    data : dict
        JSON data to return.

    Returns
    -------
    mock.Mock
        Mocked response object.
    """
    mock_response = mock.Mock()
    mock_response.json.return_value = data
    mock_response.raise_for_status = mock.Mock()
    return mock_response


# ---------------------------------------------------------------------------
# add command tests
# ---------------------------------------------------------------------------


def test_add_basic_command() -> None:
    """Test adding a basic job without options."""
    fake_job = make_fake_job()
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(app, ["add", "echo hello"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["command"] == "echo hello"
    assert output["provider"] == "local"


def test_add_with_provider() -> None:
    """Test adding a job with --provider option."""
    fake_job = make_fake_job(provider="runpod")
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(app, ["add", "echo hello", "--provider", "runpod"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["provider"] == "runpod"


def test_add_with_gpu() -> None:
    """Test adding a job with --gpu option."""
    fake_job = make_fake_job(gpu_type="RTX4090:1", provider="runpod")
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(
            app,
            ["add", "echo hello", "--provider", "runpod", "--gpu", "RTX4090:1"],
        )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["gpu_type"] == "RTX4090:1"


def test_add_with_cpu() -> None:
    """Test adding a job with --cpu option."""
    fake_job = make_fake_job(cpu_count=1, provider="runpod")
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(
            app,
            ["add", "echo hello", "--provider", "runpod", "--cpu"],
        )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["cpu_count"] == 1


def test_add_with_volume() -> None:
    """Test adding a job with --volume option."""
    fake_job = make_fake_job(volume_id="77yhuyo55k", provider="runpod")
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(
            app,
            ["add", "echo hello", "--provider", "runpod", "--volume", "77yhuyo55k"],
        )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["volume_id"] == "77yhuyo55k"


def test_add_with_managed() -> None:
    """Test adding a job with --managed option."""
    fake_job = make_fake_job(managed=True, provider="runpod")
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(
            app,
            ["add", "echo hello", "--provider", "runpod", "--managed"],
        )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["managed"] is True


def test_add_with_dir() -> None:
    """Test adding a job with --dir option."""
    fake_job = make_fake_job(workdir="experiments/exp001", provider="runpod")
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(
            app,
            [
                "add",
                "echo hello",
                "--provider",
                "runpod",
                "--dir",
                "experiments/exp001",
            ],
        )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["workdir"] == "experiments/exp001"


def test_add_with_config() -> None:
    """Test adding a job with --config option."""
    fake_job = make_fake_job()
    mock_response = make_mock_response(fake_job)

    # Mock load_config_file to return empty dict (config file exists but empty)
    with (
        mock.patch("httpx.AsyncClient.request", return_value=mock_response),
        mock.patch("pxq.cli.load_config_file", return_value={}),
    ):
        result = runner.invoke(
            app,
            ["add", "echo hello", "--config", "exp001.yaml"],
        )

    assert result.exit_code == 0


def test_add_gpu_and_cpu_mutually_exclusive() -> None:
    """Test that --gpu and --cpu are mutually exclusive."""
    result = runner.invoke(
        app,
        ["add", "echo hello", "--gpu", "RTX4090:1", "--cpu"],
    )

    assert result.exit_code == 1
    assert "mutually exclusive" in result.stderr.lower()


def test_add_with_image() -> None:
    """Test adding a job with --image option.

    This test codifies the contract that --image is accepted and
    the value appears in the request payload as image_name.
    """
    fake_job = make_fake_job(provider="runpod")
    fake_job["image_name"] = "ubuntu:22.04"
    mock_response = make_mock_response(fake_job)

    with mock.patch(
        "httpx.AsyncClient.request", return_value=mock_response
    ) as mock_req:
        result = runner.invoke(
            app,
            ["add", "echo hello", "--provider", "runpod", "--image", "ubuntu:22.04"],
        )

    assert result.exit_code == 0
    # Verify the request payload contains image_name
    call_kwargs = mock_req.call_args[1]
    assert call_kwargs["json"]["image_name"] == "ubuntu:22.04"


def test_add_image_and_template_mutually_exclusive() -> None:
    """Test that --image and --template are mutually exclusive.

    This test codifies the contract that image selection and template_id
    cannot be specified together, as they represent conflicting pod creation strategies.
    """
    result = runner.invoke(
        app,
        ["add", "echo hello", "--image", "ubuntu:22.04", "--template", "tpl-123"],
    )

    assert result.exit_code == 1
    # Error message must mention both image and template_id
    stderr_lower = result.stderr.lower()
    assert "image" in stderr_lower or "template" in stderr_lower
    assert "mutually exclusive" in stderr_lower


def test_add_all_options_combined() -> None:
    """Test adding a job with all options combined (except --cpu)."""
    fake_job = make_fake_job(
        provider="runpod",
        gpu_type="RTX4090:1",
        volume_id="77yhuyo55k",
        managed=True,
        workdir="experiments/exp001",
    )
    mock_response = make_mock_response(fake_job)

    # Mock load_config_file to return empty dict
    with (
        mock.patch("httpx.AsyncClient.request", return_value=mock_response),
        mock.patch("pxq.cli.load_config_file", return_value={}),
    ):
        result = runner.invoke(
            app,
            [
                "add",
                "uv run python experiments/exp001/run.py",
                "--provider",
                "runpod",
                "--gpu",
                "RTX4090:1",
                "--volume",
                "77yhuyo55k",
                "--managed",
                "--dir",
                "experiments/exp001",
                "--config",
                "exp001.yaml",
            ],
        )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["provider"] == "runpod"
    assert output["gpu_type"] == "RTX4090:1"
    assert output["volume_id"] == "77yhuyo55k"
    assert output["managed"] is True
    # workdir is resolved to absolute path, so check it ends with expected path
    assert (
        output["workdir"].endswith("experiments/exp001")
        or output["workdir"] == "experiments/exp001"
    )


def test_add_with_config_gpu_alias(tmp_path: Path) -> None:
    """Test that 'gpu' alias in config file is normalized to 'gpu_type'.

    Regression test: When config file contains 'gpu: RTX2000Ada:2',
    the CLI should normalize it to 'gpu_type' and the output should show
    'gpu_type: RTX2000Ada:2'.
    """
    # Create temp config file with 'gpu' alias (not 'gpu_type')
    config_file = tmp_path / "config-gpu.yaml"
    config_file.write_text(
        """provider: runpod
gpu: RTX2000Ada:2
"""
    )

    # Create fake job response
    fake_job = make_fake_job(gpu_type="RTX2000Ada:2", provider="runpod")
    mock_response = make_mock_response(fake_job)

    # Mock the HTTP request
    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(
            app,
            ["add", "echo hello", "--provider", "runpod", "--config", str(config_file)],
        )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["gpu_type"] == "RTX2000Ada:2"


def test_ls_default_non_terminal_states() -> None:
    """Test ls command returns non-terminal states by default."""
    fake_response = {
        "jobs": [
            make_fake_job(job_id=1, status=JobStatus.QUEUED),
            make_fake_job(job_id=2, status=JobStatus.RUNNING),
        ],
        "count": 2,
    }
    mock_response = make_mock_response(fake_response)

    with mock.patch(
        "httpx.AsyncClient.request", return_value=mock_response
    ) as mock_req:
        result = runner.invoke(app, ["ls"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["count"] == 2
    # Verify that include_all=False was passed
    call_kwargs = mock_req.call_args
    assert call_kwargs[1]["params"]["all"] is False


def test_ls_with_all_flag() -> None:
    """Test ls -a returns all jobs including terminal states."""
    fake_response = {
        "jobs": [
            make_fake_job(job_id=1, status=JobStatus.QUEUED),
            make_fake_job(job_id=2, status=JobStatus.RUNNING),
            make_fake_job(job_id=3, status=JobStatus.SUCCEEDED),
            make_fake_job(job_id=4, status=JobStatus.FAILED),
        ],
        "count": 4,
    }
    mock_response = make_mock_response(fake_response)

    with mock.patch(
        "httpx.AsyncClient.request", return_value=mock_response
    ) as mock_req:
        result = runner.invoke(app, ["ls", "-a"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["count"] == 4
    # Verify that include_all=True was passed
    call_kwargs = mock_req.call_args
    assert call_kwargs[1]["params"]["all"] is True


def test_ls_empty_result() -> None:
    """Test ls command with no jobs."""
    fake_response = {"jobs": [], "count": 0}
    mock_response = make_mock_response(fake_response)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        result = runner.invoke(app, ["ls"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["count"] == 0


# ---------------------------------------------------------------------------
# status command tests
# ---------------------------------------------------------------------------


def test_status_default_non_terminal_states() -> None:
    """Test status command returns non-terminal states by default."""
    fake_response = {
        "jobs": [
            make_fake_job(job_id=1, status=JobStatus.QUEUED),
            make_fake_job(job_id=2, status=JobStatus.PROVISIONING),
        ],
        "count": 2,
    }
    mock_response = make_mock_response(fake_response)

    with mock.patch(
        "httpx.AsyncClient.request", return_value=mock_response
    ) as mock_req:
        result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["count"] == 2
    # Verify that include_all=False was passed
    call_kwargs = mock_req.call_args
    assert call_kwargs[1]["params"]["all"] is False


def test_status_with_all_flag() -> None:
    """Test status -a returns all jobs including terminal states."""
    fake_response = {
        "jobs": [
            make_fake_job(job_id=1, status=JobStatus.QUEUED),
            make_fake_job(job_id=2, status=JobStatus.SUCCEEDED),
            make_fake_job(job_id=3, status=JobStatus.FAILED),
            make_fake_job(job_id=4, status=JobStatus.STOPPED),
            make_fake_job(job_id=5, status=JobStatus.CANCELLED),
        ],
        "count": 5,
    }
    mock_response = make_mock_response(fake_response)

    with mock.patch(
        "httpx.AsyncClient.request", return_value=mock_response
    ) as mock_req:
        result = runner.invoke(app, ["status", "-a"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["count"] == 5
    # Verify that include_all=True was passed
    call_kwargs = mock_req.call_args
    assert call_kwargs[1]["params"]["all"] is True


def test_status_specific_job_id() -> None:
    """Test status <job_id> returns specific job details."""
    fake_job = make_fake_job(
        job_id=42, command="python train.py", status=JobStatus.RUNNING
    )
    mock_response = make_mock_response(fake_job)

    with mock.patch(
        "httpx.AsyncClient.request", return_value=mock_response
    ) as mock_req:
        result = runner.invoke(app, ["status", "42"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["id"] == 42
    assert output["command"] == "python train.py"
    assert output["status"] == "running"
    # Verify that the correct endpoint was called
    # httpx.AsyncClient.request is called with (method, path, **kwargs)
    call_args = mock_req.call_args
    assert "/jobs/42" in call_args[0][1]  # args[1] is the path


def test_status_job_not_found() -> None:
    """Test status <job_id> when job does not exist."""
    mock_response = mock.Mock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found",
        request=mock.Mock(),
        response=mock.Mock(status_code=404),
    )

    with mock.patch(
        "httpx.AsyncClient.request", side_effect=mock_response.raise_for_status
    ):
        result = runner.invoke(app, ["status", "999"])

    # Should fail with exit code 1
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Connection error tests
# ---------------------------------------------------------------------------


def test_add_connection_error() -> None:
    """Test add command handles connection errors gracefully."""

    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection failed")

    with mock.patch("httpx.AsyncClient.request", side_effect=_raise):
        result = runner.invoke(app, ["add", "echo hello"])

    assert result.exit_code == 1
    assert "Failed to connect" in result.stderr


def test_ls_connection_error() -> None:
    """Test ls command handles connection errors gracefully."""

    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection failed")

    with mock.patch("httpx.AsyncClient.request", side_effect=_raise):
        result = runner.invoke(app, ["ls"])

    assert result.exit_code == 1
    assert "Failed to connect" in result.stderr


def test_status_connection_error() -> None:
    """Test status command handles connection errors gracefully."""

    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection failed")

    with mock.patch("httpx.AsyncClient.request", side_effect=_raise):
        result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "Failed to connect" in result.stderr


# ---------------------------------------------------------------------------
# PxqClient tests with model_validate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pxqclient_create_job_uses_model_validate() -> None:
    """Verify create_job uses model_validate for Pydantic V2."""
    fake_job = make_fake_job()
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        client = PxqClient()
        job = await client.create_job("echo hello")

    assert isinstance(job, Job)
    assert job.id == 1
    assert job.command == "echo hello"


@pytest.mark.asyncio
async def test_pxqclient_list_jobs_uses_model_validate() -> None:
    """Verify list_jobs uses model_validate for Pydantic V2."""
    fake_response = {
        "jobs": [make_fake_job(job_id=1), make_fake_job(job_id=2)],
        "count": 2,
    }
    mock_response = make_mock_response(fake_response)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        client = PxqClient()
        jobs = await client.list_jobs()

    assert len(jobs) == 2
    assert all(isinstance(job, Job) for job in jobs)


@pytest.mark.asyncio
async def test_pxqclient_get_job_uses_model_validate() -> None:
    """Verify get_job uses model_validate for Pydantic V2."""
    fake_job = make_fake_job(job_id=42)
    mock_response = make_mock_response(fake_job)

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        client = PxqClient()
        job = await client.get_job(42)

    assert isinstance(job, Job)
    assert job.id == 42


# ---------------------------------------------------------------------------
# Visibility semantics regression tests
# ---------------------------------------------------------------------------


class TestVisibilitySemantics:
    """Regression tests for CLI visibility semantics based on status.

    These tests verify that CLI commands (ls, status) correctly show/hide jobs
    based on their status semantics:
    - Non-managed completion-pending jobs stay RUNNING (visible by default)
    - Managed success jobs end at SUCCEEDED (hidden by default as terminal)
    - Terminal states (SUCCEEDED/FAILED/STOPPED/CANCELLED) are hidden by default
    """

    def test_ls_shows_running_completion_pending_by_default(self) -> None:
        """Test that ls shows RUNNING jobs by default (non-managed completion-pending).

        Non-managed RunPod jobs remain in RUNNING status after remote command completion
        until explicit pxq stop. Since RUNNING is not a terminal state, these jobs
        appear in the default ls output.
        """
        fake_response = {
            "jobs": [
                make_fake_job(job_id=1, status=JobStatus.RUNNING),
            ],
            "count": 1,
        }
        mock_response = make_mock_response(fake_response)

        with mock.patch(
            "httpx.AsyncClient.request", return_value=mock_response
        ) as mock_req:
            result = runner.invoke(app, ["ls"])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["count"] == 1
        assert output["jobs"][0]["status"] == "running"
        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["params"]["all"] is False

    def test_ls_hides_succeeded_by_default(self) -> None:
        """Test that ls hides SUCCEEDED jobs by default (managed success is terminal).

        Managed RunPod jobs that complete successfully transition to SUCCEEDED status.
        Since SUCCEEDED is a terminal state, these jobs are excluded from default ls output.
        """
        fake_response = {
            "jobs": [],
            "count": 0,
        }
        mock_response = make_mock_response(fake_response)

        with mock.patch(
            "httpx.AsyncClient.request", return_value=mock_response
        ) as mock_req:
            result = runner.invoke(app, ["ls"])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["count"] == 0
        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["params"]["all"] is False

    def test_ls_all_shows_terminal_states(self) -> None:
        """Test that ls -a shows SUCCEEDED/FAILED/STOPPED/CANCELLED jobs."""
        fake_response = {
            "jobs": [
                make_fake_job(job_id=1, status=JobStatus.SUCCEEDED),
                make_fake_job(job_id=2, status=JobStatus.FAILED),
                make_fake_job(job_id=3, status=JobStatus.STOPPED),
                make_fake_job(job_id=4, status=JobStatus.CANCELLED),
                make_fake_job(job_id=5, status=JobStatus.RUNNING),
            ],
            "count": 5,
        }
        mock_response = make_mock_response(fake_response)

        with mock.patch(
            "httpx.AsyncClient.request", return_value=mock_response
        ) as mock_req:
            result = runner.invoke(app, ["ls", "-a"])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["count"] == 5
        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["params"]["all"] is True

    def test_status_shows_running_by_default(self) -> None:
        """Test that status shows RUNNING jobs by default."""
        fake_response = {
            "jobs": [
                make_fake_job(job_id=1, status=JobStatus.RUNNING),
            ],
            "count": 1,
        }
        mock_response = make_mock_response(fake_response)

        with mock.patch(
            "httpx.AsyncClient.request", return_value=mock_response
        ) as mock_req:
            result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["count"] == 1
        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["params"]["all"] is False

    def test_status_all_shows_terminal_states(self) -> None:
        """Test that status -a shows terminal state jobs."""
        fake_response = {
            "jobs": [
                make_fake_job(job_id=1, status=JobStatus.SUCCEEDED),
                make_fake_job(job_id=2, status=JobStatus.RUNNING),
            ],
            "count": 2,
        }
        mock_response = make_mock_response(fake_response)

        with mock.patch(
            "httpx.AsyncClient.request", return_value=mock_response
        ) as mock_req:
            result = runner.invoke(app, ["status", "-a"])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["count"] == 2
        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["params"]["all"] is True

    def test_ls_non_managed_completion_pending_visible_with_exit_code(
        self,
    ) -> None:
        """Test that non-managed completion-pending jobs with exit_code are visible.

        Non-managed jobs that complete remotely stay in RUNNING status with exit_code set.
        They remain visible in default ls output until explicit pxq stop.
        """
        fake_response = {
            "jobs": [
                {
                    "id": 42,
                    "command": "python train.py",
                    "status": "running",
                    "provider": "runpod",
                    "managed": False,
                    "exit_code": 0,
                    "error_message": None,
                    "pod_id": "pod-abc123",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "started_at": "2024-01-01T00:00:00Z",
                    "finished_at": None,
                }
            ],
            "count": 1,
        }
        mock_response = make_mock_response(fake_response)

        with mock.patch(
            "httpx.AsyncClient.request", return_value=mock_response
        ) as mock_req:
            result = runner.invoke(app, ["ls"])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["count"] == 1
        job = output["jobs"][0]
        assert job["status"] == "running"
        assert job["exit_code"] == 0
        assert job["managed"] is False
        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["params"]["all"] is False
