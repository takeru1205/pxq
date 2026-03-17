# -*- coding: utf-8 -*-
"""Tests for pxq ssh command.
"""

from typer.testing import CliRunner
from unittest import mock

from pxq.cli import app
from pxq.models import JobStatus

# Reuse helper from existing tests
from tests.cli.test_add_ls_status import make_fake_job

runner = CliRunner()


def mock_settings(*args, **kwargs):
    class Dummy:
        runpod_api_key = "dummy-key"

    return Dummy()


def test_ssh_running_job_success():
    """Success path: os.execvp called with -tt for PTY allocation, no printed command."""
    fake_job = make_fake_job(job_id=1, status=JobStatus.RUNNING)
    fake_job["pod_id"] = "pod123"

    class DummyPod:
        ssh_host = "1.2.3.4"
        ssh_port = 2222

    with (
        mock.patch("pxq.client.PxqClient.get_job", return_value=fake_job),
        mock.patch(
            "pxq.providers.runpod_client.RunPodClient.get_pod", return_value=DummyPod()
        ),
        mock.patch("pxq.config.Settings", mock_settings),
        mock.patch("os.execvp") as mock_execvp,
    ):
        result = runner.invoke(app, ["ssh", "1"])

    # CLI should exit cleanly with no output (execvp replaces process on success)
    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == ""

    # Verify os.execvp called with correct arguments
    mock_execvp.assert_called_once()
    call_args = mock_execvp.call_args
    assert call_args[0][0] == "ssh"
    ssh_args = call_args[0][1]

    # Verify -tt flag for PTY allocation (interactive SSH)
    assert "-tt" in ssh_args, "Missing -tt flag for interactive PTY allocation"
    tt_index = ssh_args.index("-tt")
    target_index = ssh_args.index("root@1.2.3.4")
    assert tt_index < target_index, "-tt must come before target"

    # Verify port flag
    assert "-p" in ssh_args
    assert "2222" in ssh_args

    # Verify target host
    assert "root@1.2.3.4" in ssh_args

    # Verify full argument structure
    assert ssh_args[0] == "ssh"
    assert "StrictHostKeyChecking=no" in ssh_args
    assert "UserKnownHostsFile=/dev/null" in ssh_args
    assert "BatchMode=yes" in ssh_args
    assert "ConnectTimeout=15" in ssh_args


def test_ssh_job_not_running():
    """Error path: job exists but is not in RUNNING status."""
    fake_job = make_fake_job(job_id=2, status=JobStatus.QUEUED)
    fake_job["pod_id"] = "pod123"
    with mock.patch("pxq.client.PxqClient.get_job", return_value=fake_job), mock.patch(
        "pxq.config.Settings", mock_settings
    ):
        result = runner.invoke(app, ["ssh", "2"])
    assert result.exit_code == 1
    assert "not running" in result.stderr.lower()


def test_ssh_job_not_found():
    """Error path: job does not exist."""
    with mock.patch("pxq.client.PxqClient.get_job", return_value=None), mock.patch(
        "pxq.config.Settings", mock_settings
    ):
        result = runner.invoke(app, ["ssh", "999"])
    assert result.exit_code == 1
    assert "not found" in result.stderr.lower()


def test_ssh_job_no_pod_id():
    """Error path: job exists but has no pod_id."""
    fake_job = make_fake_job(job_id=3, status=JobStatus.RUNNING)
    with mock.patch("pxq.client.PxqClient.get_job", return_value=fake_job), mock.patch(
        "pxq.config.Settings", mock_settings
    ):
        result = runner.invoke(app, ["ssh", "3"])
    assert result.exit_code == 1
    assert "no pod" in result.stderr.lower()


def test_ssh_pod_missing_host():
    """Error path: pod exists but SSH host is not available."""
    fake_job = make_fake_job(job_id=4, status=JobStatus.RUNNING)
    fake_job["pod_id"] = "pod123"

    class DummyPod:
        ssh_host = None
        ssh_port = 22

    with mock.patch("pxq.client.PxqClient.get_job", return_value=fake_job), mock.patch(
        "pxq.providers.runpod_client.RunPodClient.get_pod", return_value=DummyPod()
    ), mock.patch("pxq.config.Settings", mock_settings):
        result = runner.invoke(app, ["ssh", "4"])
    assert result.exit_code == 1
    assert "ssh host" in result.stderr.lower()


def test_ssh_binary_not_found():
    """Error path: ssh binary is not installed on the system."""
    fake_job = make_fake_job(job_id=5, status=JobStatus.RUNNING)
    fake_job["pod_id"] = "pod123"

    class DummyPod:
        ssh_host = "1.2.3.4"
        ssh_port = 2222

    with (
        mock.patch("pxq.client.PxqClient.get_job", return_value=fake_job),
        mock.patch(
            "pxq.providers.runpod_client.RunPodClient.get_pod", return_value=DummyPod()
        ),
        mock.patch("pxq.config.Settings", mock_settings),
        mock.patch("os.execvp", side_effect=FileNotFoundError),
    ):
        result = runner.invoke(app, ["ssh", "5"])

    assert result.exit_code == 1
    assert "ssh" in result.stderr.lower()
    assert "not found" in result.stderr.lower()
    # Verify the error message mentions OpenSSH client installation
    assert "openssh" in result.stderr.lower()
