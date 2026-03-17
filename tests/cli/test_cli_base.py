# -*- coding: utf-8 -*-
"""Tests for the pxq CLI and client.

This module verifies basic CLI help output and the behaviour of
:class:`pxq.client.PxqClient` when interacting with a (mocked) server.
"""

import pytest
from typer.testing import CliRunner
from unittest import mock

import httpx

from pxq.cli import app
from pxq.client import PxqClient

# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_help_shows_commands() -> None:
    """Ensure ``pxq --help`` lists the expected sub‑commands.

    The help output should contain the command names ``add``, ``ls``,
    ``status``, ``ssh`` and ``server``.
    """
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ["add", "ls", "status", "ssh", "server"]:
        assert cmd in result.stdout


# ---------------------------------------------------------------------------
# PxqClient tests – use a mocked httpx.AsyncClient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pxqclient_raises_runtime_error() -> None:
    """PxqClient should raise ``RuntimeError`` when the server cannot be reached.

    The internal ``_request`` method catches ``httpx.ConnectError`` and re‑raises
    a ``RuntimeError`` with a helpful message.
    """

    async def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection failed")

    with mock.patch("httpx.AsyncClient.request", side_effect=_raise):
        client = PxqClient()
        with pytest.raises(RuntimeError):
            await client.list_jobs()


@pytest.mark.asyncio
async def test_pxqclient_create_job_works_with_mock() -> None:
    """``create_job`` should return a :class:`pxq.models.Job` instance.

    The HTTP request is mocked to return a JSON payload that matches the
    ``Job`` model schema.
    """
    fake_job = {
        "id": 1,
        "command": "echo hello",
        "status": "queued",
        "provider": "local",
        "managed": False,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }

    mock_response = mock.Mock()
    mock_response.json.return_value = fake_job
    mock_response.raise_for_status = mock.Mock()

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        client = PxqClient()
        job = await client.create_job("echo hello")
        assert job.id == 1
        assert job.command == "echo hello"
        assert job.status.value == "queued"


@pytest.mark.asyncio
async def test_pxqclient_list_jobs_works_with_mock() -> None:
    """``list_jobs`` should return a list of :class:`pxq.models.Job` objects."""
    fake_response = {
        "jobs": [
            {
                "id": 2,
                "command": "ls",
                "status": "running",
                "provider": "local",
                "managed": False,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        ]
    }

    mock_response = mock.Mock()
    mock_response.json.return_value = fake_response
    mock_response.raise_for_status = mock.Mock()

    with mock.patch("httpx.AsyncClient.request", return_value=mock_response):
        client = PxqClient()
        jobs = await client.list_jobs()
        assert isinstance(jobs, list)
        assert len(jobs) == 1
        job = jobs[0]
        assert job.id == 2
        assert job.command == "ls"
        assert job.status.value == "running"
