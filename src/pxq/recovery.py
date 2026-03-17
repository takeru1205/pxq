from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pxq.models import Job, JobStatus
from pxq.config import Settings
from pxq.providers.runpod_client import RunPodClient
from pxq.storage import list_jobs, update_job_status

INTERMEDIATE_STATUSES: tuple[JobStatus, ...] = (
    JobStatus.PROVISIONING,
    JobStatus.UPLOADING,
    JobStatus.RUNNING,
)
RESTART_INTERRUPTION_ERROR = "Job interrupted during server restart"


@dataclass(slots=True)
class RecoveryResult:
    reconciled_jobs: list[Job] = field(default_factory=list)
    failed_without_pod: int = 0
    marked_for_cleanup: int = 0
    cleanup_job_ids: list[int] = field(default_factory=list)
    skipped_completion_pending: int = 0
    """Number of RUNNING jobs with exit_code set (manual-stop pending) that were skipped."""

    @property
    def total_reconciled(self) -> int:
        return len(self.reconciled_jobs)


async def reconcile_jobs(db_path: Path | str) -> RecoveryResult:
    intermediate_jobs: list[Job] = []
    for status in INTERMEDIATE_STATUSES:
        intermediate_jobs.extend(await list_jobs(db_path, status=status))

    result = RecoveryResult()

    for job in intermediate_jobs:
        if job.id is None:
            continue

        # Skip RUNNING jobs with exit_code set - these are completion-pending
        # (manual-stop pending) and should not be auto-stopped by recovery.
        # They are waiting for explicit `pxq stop` command.
        if job.status == JobStatus.RUNNING and job.exit_code is not None:
            result.skipped_completion_pending += 1
            result.reconciled_jobs.append(job)
            continue

        if job.pod_id:
            # Attempt to stop the pod via RunPod API
            try:
                settings = Settings()
                if settings.runpod_api_key:
                    client = RunPodClient(settings.runpod_api_key)
                    await client.stop_pod(job.pod_id)
            except Exception as e:
                # Log warning but continue reconciliation
                import logging

                logging.getLogger(__name__).warning(
                    f"Failed to stop pod {job.pod_id} for job {job.id}: {e}"
                )

            result.marked_for_cleanup += 1
            result.cleanup_job_ids.append(job.id)
            # Append original job to reconciled list without changing status
            result.reconciled_jobs.append(job)
            continue

        # Jobs without pod_id: distinguish managed vs non-managed
        # Managed jobs without pod_id are orphaned and should be FAILED
        # Non-managed jobs should stay in their current state (no pod to clean up)
        if not job.managed:
            # Non-managed job without pod_id - keep current state, no pod to stop
            result.reconciled_jobs.append(job)
            continue

        updated_job = await update_job_status(
            db_path,
            job.id,
            JobStatus.FAILED,
            message=RESTART_INTERRUPTION_ERROR,
            error_message=RESTART_INTERRUPTION_ERROR,
        )
        result.failed_without_pod += 1
        result.reconciled_jobs.append(updated_job)

    return result
