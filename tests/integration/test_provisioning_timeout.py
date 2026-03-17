from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from pxq.config import Settings
from pxq.models import Job, JobStatus
from pxq.providers.runpod_client import PodResponse, PodStatus, RunPodClient
from pxq.providers.runpod_provider import (
    ProvisioningTimeoutError,
    handle_provisioning_timeout,
    wait_for_pod_ready,
)
from pxq.storage import create_job, get_job, get_job_events, init_db


@pytest.mark.asyncio
async def test_wait_for_pod_ready_returns_when_running_within_timeout() -> None:
    client = AsyncMock(spec=RunPodClient)
    running_pod = PodResponse(id="pod-123", status=PodStatus.RUNNING)
    client.get_pod.return_value = running_pod

    settings = Settings(provisioning_timeout_minutes=1)
    result = await wait_for_pod_ready(
        client, "pod-123", settings, poll_interval_seconds=10
    )

    assert result == running_pod
    client.get_pod.assert_awaited_once_with("pod-123")


@pytest.mark.asyncio
async def test_wait_for_pod_ready_raises_timeout_when_pod_not_ready() -> None:
    client = AsyncMock(spec=RunPodClient)
    client.get_pod.return_value = PodResponse(id="pod-123", status=PodStatus.LAUNCHING)

    settings = Settings(provisioning_timeout_minutes=0)
    with pytest.raises(ProvisioningTimeoutError):
        await wait_for_pod_ready(client, "pod-123", settings, poll_interval_seconds=10)

    client.get_pod.assert_awaited_once_with("pod-123")


@pytest.mark.asyncio
async def test_handle_provisioning_timeout_transitions_job_to_failed(
    tmp_path: Path
) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(
        db_path,
        Job(command="echo test", status=JobStatus.PROVISIONING, pod_id="pod-123"),
    )

    client = AsyncMock(spec=RunPodClient)
    client.stop_pod.return_value = PodResponse(id="pod-123", status=PodStatus.STOPPED)

    settings = Settings(provisioning_timeout_minutes=15)
    await handle_provisioning_timeout(db_path, job.id, "pod-123", client, settings)

    updated_job = await get_job(db_path, job.id)
    assert updated_job is not None
    assert updated_job.status == JobStatus.FAILED
    assert updated_job.error_message == "Pod did not become ready within 15 minutes"

    events = await get_job_events(db_path, job.id)
    event_messages = [event.message for event in events if event.message]
    assert "Provisioning timeout" in event_messages


@pytest.mark.asyncio
async def test_handle_provisioning_timeout_attempts_stop_pod(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    job = await create_job(
        db_path,
        Job(command="echo test", status=JobStatus.PROVISIONING, pod_id="pod-123"),
    )

    client = AsyncMock(spec=RunPodClient)
    client.stop_pod.return_value = PodResponse(id="pod-123", status=PodStatus.STOPPED)

    settings = Settings(provisioning_timeout_minutes=15)
    await handle_provisioning_timeout(db_path, job.id, "pod-123", client, settings)

    client.stop_pod.assert_awaited_once_with("pod-123")
