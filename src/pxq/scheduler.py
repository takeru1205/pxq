from __future__ import annotations

from pathlib import Path

from pxq.config import Settings
from pxq.models import Job, JobStatus
from pxq.storage import count_jobs_by_status, list_jobs, update_job_status


class Scheduler:
    _RUNNING_STATUSES = (
        JobStatus.PROVISIONING,
        JobStatus.UPLOADING,
        JobStatus.RUNNING,
    )

    def __init__(self, db_path: Path | str, settings: Settings | None = None) -> None:
        self.db_path = db_path
        self.settings = settings or Settings()

    async def get_running_count(self) -> int:
        counts = await count_jobs_by_status(self.db_path)
        return sum(counts.get(status, 0) for status in self._RUNNING_STATUSES)

    async def can_start_job(self) -> bool:
        running_count = await self.get_running_count()
        return running_count < self.settings.max_parallelism

    async def start_next_job(self) -> Job | None:
        if not await self.can_start_job():
            return None

        queued_jobs = await list_jobs(self.db_path, status=JobStatus.QUEUED)
        if not queued_jobs:
            return None

        oldest_job = min(queued_jobs, key=lambda job: job.created_at)
        if oldest_job.id is None:
            return None

        return await update_job_status(
            self.db_path,
            oldest_job.id,
            JobStatus.PROVISIONING,
            message="Job picked by scheduler",
        )

    async def tick(self) -> list[Job]:
        started_jobs: list[Job] = []

        while await self.can_start_job():
            started_job = await self.start_next_job()
            if started_job is None:
                break
            started_jobs.append(started_job)

        return started_jobs
