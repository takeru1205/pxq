from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import aiosqlite

from pxq.config import Settings
from pxq.models import Job, JobStatus
from pxq.providers.runpod_client import PodResponse, PodStatus, RunPodClient
from pxq.storage import update_job_status


class ProvisioningTimeoutError(Exception):
    """Raised when a pod does not become ready before timeout."""

    def __init__(self, pod_id: str, timeout_minutes: int) -> None:
        self.pod_id = pod_id
        self.timeout_minutes = timeout_minutes
        super().__init__(
            f"Pod {pod_id} did not become ready within {timeout_minutes} minutes"
        )


async def wait_for_pod_ready(
    runpod_client: RunPodClient,
    pod_id: str,
    settings: Settings,
    poll_interval_seconds: float = 10.0,
) -> PodResponse:
    """Wait for a pod to reach RUNNING state within provisioning timeout.

    Parameters
    ----------
    runpod_client : RunPodClient
        RunPod client used to query pod status.
    pod_id : str
        Pod ID to poll.
    settings : Settings
        Application settings containing provisioning timeout.
    poll_interval_seconds : float
        Poll interval in seconds. Defaults to 10 seconds.

    Returns
    -------
    PodResponse
        Pod response when the pod reaches RUNNING state.

    Raises
    ------
    ProvisioningTimeoutError
        If the pod does not reach RUNNING before timeout.
    """
    timeout_minutes = settings.provisioning_timeout_minutes
    timeout_seconds = timeout_minutes * 60
    deadline = monotonic() + timeout_seconds

    while True:
        pod = await runpod_client.get_pod(pod_id)
        if pod.status == PodStatus.RUNNING and pod.has_public_ssh:
            # RunPod Secrets need time to expand after pod starts.
            # Wait 15 seconds to ensure env vars with {{ RUNPOD_SECRET_* }}
            # placeholders are fully expanded before command execution.
            await asyncio.sleep(30)
            return pod

        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ProvisioningTimeoutError(
                pod_id=pod_id, timeout_minutes=timeout_minutes
            )

        # タイムアウト時刻を超えないように待機時間を調整する。
        await asyncio.sleep(min(poll_interval_seconds, remaining))


async def handle_provisioning_timeout(
    db_path: Path | str,
    job_id: int,
    pod_id: str,
    runpod_client: RunPodClient,
    settings: Settings,
) -> Job:
    """Mark a provisioning job as failed and attempt pod stop on timeout.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database.
    job_id : int
        Job ID to mark as failed.
    pod_id : str
        Pod ID associated with the job.
    runpod_client : RunPodClient
        RunPod client used for pod stop operation.
    settings : Settings
        Application settings containing provisioning timeout.

    Returns
    -------
    Job
        Updated job after transitioning to failed.
    """
    timeout_minutes = settings.provisioning_timeout_minutes
    error_message = f"Pod did not become ready within {timeout_minutes} minutes"

    job = await update_job_status(
        db_path,
        job_id,
        JobStatus.FAILED,
        message="Provisioning timeout",
        error_message=error_message,
    )

    if not pod_id:
        await _append_job_event(db_path, job_id, "No pod_id found for stop attempt")
        return job

    try:
        await runpod_client.stop_pod(pod_id)
        await _append_job_event(
            db_path,
            job_id,
            f"Stop pod requested after provisioning timeout: {pod_id}",
        )
    except Exception as exc:
        # 停止失敗で処理全体を失敗させず、監査用イベントだけ記録する。
        await _append_job_event(
            db_path,
            job_id,
            f"Failed to stop pod after provisioning timeout: {pod_id}; error={exc}",
        )

    return job


async def _append_job_event(db_path: Path | str, job_id: int, message: str) -> None:
    now_iso = datetime.now(UTC).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO job_events (job_id, from_status, to_status, timestamp, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, JobStatus.FAILED.value, JobStatus.FAILED.value, now_iso, message),
        )
        await db.commit()
