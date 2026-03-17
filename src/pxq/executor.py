"""Job executor for processing jobs in PROVISIONING state."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from pxq.config import Settings
from pxq.models import Job, JobStatus
from pxq.providers.local_exec import (
    execute_local_command,
    start_local_command,
    stop_local_process,
)
from pxq.providers.runpod_client import (
    CloudType,
    ComputeType,
    PodCreateRequest,
    RunPodClient,
)
from pxq.providers.runpod_gpu_types import resolve_gpu_type
from pxq.providers.runpod_exec import managed_stop, run_job_on_pod
from pxq.providers.runpod_provider import (
    ProvisioningTimeoutError,
    handle_provisioning_timeout,
    wait_for_pod_ready,
)
from pxq.storage import (
    create_artifact,
    create_job,
    get_job,
    init_db,
    list_jobs,
    update_job_field,
    update_job_metadata,
    update_job_status,
)

logger = logging.getLogger(__name__)


class JobExecutor:
    """Processes jobs that are in PROVISIONING state."""

    def __init__(self, db_path: Path | str, settings: Settings | None = None) -> None:
        self.db_path = db_path
        self.settings = settings or Settings()

    async def process_local_job(self, job: Job) -> Job:
        """Execute a local job."""
        if job.id is None:
            raise ValueError("job.id is required")

        # Transition through UPLOADING (required by state machine)
        current_job = await update_job_status(
            self.db_path,
            job.id,
            JobStatus.UPLOADING,
            message="Skipping upload for local job",
        )

        # Then transition to RUNNING
        current_job = await update_job_status(
            self.db_path,
            job.id,
            JobStatus.RUNNING,
            message="Local command started",
        )

        # Start the process in a new process group and save PID
        handle = await start_local_command(
            command=job.command,
            workdir=job.workdir,
        )

        # Save the process group PID for stop functionality
        if handle.pid is not None:
            await update_job_field(
                self.db_path,
                job.id,
                "local_pid",
                handle.pid,
            )

        # Wait for process completion
        try:
            stdout, stderr = await asyncio.wait_for(
                handle.communicate(), timeout=3600.0
            )
        except asyncio.TimeoutError:
            # Kill the process group on timeout
            if handle.pid is not None:
                stop_local_process(handle.pid, timeout=0)
            await handle.wait()
            failed_job = await update_job_status(
                self.db_path,
                job.id,
                JobStatus.FAILED,
                message="Command timed out after 3600.0 seconds",
            )
            # Clear local_pid explicitly (COALESCE doesn't clear NULL values)
            await update_job_field(
                self.db_path,
                job.id,
                "local_pid",
                None,
            )
            return failed_job

        # Clear local_pid after completion
        await update_job_field(
            self.db_path,
            job.id,
            "local_pid",
            None,
        )

        # Save stdout/stderr as artifacts for dashboard visibility
        exit_code = handle.returncode if handle.returncode is not None else -1
        stdout_str = stdout.decode(errors="replace")
        stderr_str = stderr.decode(errors="replace")

        if stdout_str:
            await create_artifact(
                self.db_path,
                job.id,
                artifact_type="stdout",
                path="/workspace/pxq_stdout.log",
                size_bytes=len(stdout_str.encode("utf-8")),
                content=stdout_str,
            )
        if stderr_str:
            await create_artifact(
                self.db_path,
                job.id,
                artifact_type="stderr",
                path="/workspace/pxq_stderr.log",
                size_bytes=len(stderr_str.encode("utf-8")),
                content=stderr_str,
            )

        if exit_code == 0:
            return await update_job_status(
                self.db_path,
                job.id,
                JobStatus.SUCCEEDED,
                message="Command completed",
                exit_code=exit_code,
            )
        else:
            error_msg = (
                stderr_str if stderr_str else f"Command exited with code {exit_code}"
            )
            return await update_job_status(
                self.db_path,
                job.id,
                JobStatus.FAILED,
                message="Command failed",
                exit_code=exit_code,
                error_message=error_msg,
            )

    async def process_runpod_job(self, job: Job) -> Job:
        """Execute a RunPod job through the full lifecycle."""
        if job.id is None:
            raise ValueError("job.id is required")

        if not self.settings.runpod_api_key:
            return await update_job_status(
                self.db_path,
                job.id,
                JobStatus.FAILED,
                message="RunPod API key not configured",
                error_message=(
                    "PXQ_RUNPOD_API_KEY environment variable is not set. "
                    "The pxq server reads this variable at startup. "
                    "Please restart the server after setting: "
                    "export PXQ_RUNPOD_API_KEY='your-api-key'"
                ),
            )

        runpod_client = RunPodClient(self.settings.runpod_api_key)

        # 1. Create pod
        try:
            # Determine compute type and build request parameters
            compute_type: ComputeType | None = None
            gpu_type_ids: list[str] | None = None
            gpu_count = 1
            vcpu_count: int | None = None
            cpu_flavor_ids: list[str] | None = None

            if job.gpu_type:
                # GPU job: resolve GPU type using resolver
                compute_type = ComputeType.GPU
                gpu_type_ids, gpu_count = resolve_gpu_type(job.gpu_type)
            elif job.cpu_count or job.cpu_flavor_ids:
                # CPU job: use cpu_flavor_ids
                # vcpu_count is omitted to use RunPod default (2)
                compute_type = ComputeType.CPU
                cpu_flavor_ids = job.cpu_flavor_ids
                vcpu_count = None  # Use RunPod default
                # CPU pods must NOT include gpu_type_ids

            # Determine cloud type (Secure vs Community)
            cloud_type = CloudType.SECURE if job.secure_cloud else CloudType.COMMUNITY

            # Environment variables for RunPod secrets templating
            # RunPod will inject secret values for matching variable names
            env_vars = (
                job.env
                if job.env
                else {
                    "KAGGLE_KEY": "{{ RUNPOD_SECRET_KAGGLE_KEY }}",
                    "KAGGLE_USERNAME": "{{ RUNPOD_SECRET_KAGGLE_USERNAME }}",
                }
            )
            # Use runpod/base for CPU pods (required for secret expansion)
            # Use PyTorch image for GPU pods
            # Explicit image_name overrides defaults
            if job.image_name:
                image_name = job.image_name
            elif compute_type == ComputeType.CPU:
                image_name = "runpod/base:1.0.2-ubuntu2204"
            else:
                image_name = "runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04"

            request = PodCreateRequest(
                name=f"pxq-job-{job.id}",
                image_name=image_name,
                compute_type=compute_type,
                cloud_type=cloud_type,
                # GPU fields (only set for GPU jobs)
                gpu_type_ids=gpu_type_ids,
                gpu_count=gpu_count,
                # CPU fields (only set for CPU jobs)
                cpu_flavor_ids=cpu_flavor_ids,
                vcpu_count=vcpu_count,
                env=env_vars,
                # Common fields
                data_center_ids=[job.region] if job.region else None,
                network_volume_id=job.volume_id,
                volume_mount_path=job.volume_mount_path
                if job.volume_id
                else "/workspace",
                ports="22/tcp",
                container_disk_in_gb=20,
                volume_in_gb=0 if job.volume_id is None else 30,
                start_ssh=True,
            )

            pod = await runpod_client.create_pod(request)
            job.pod_id = pod.id

        except Exception as e:
            return await update_job_status(
                self.db_path,
                job.id,
                JobStatus.FAILED,
                message="Failed to create pod",
                error_message=str(e),
            )

        # 2. Wait for pod to be ready
        try:
            ready_pod = await wait_for_pod_ready(runpod_client, pod.id, self.settings)

        except ProvisioningTimeoutError:
            return await handle_provisioning_timeout(
                self.db_path, job.id, pod.id, runpod_client, self.settings
            )
        except Exception as e:
            return await update_job_status(
                self.db_path,
                job.id,
                JobStatus.FAILED,
                message="Failed while waiting for pod",
                error_message=str(e),
            )

        # 3. Upload and execute using existing run_job_on_pod
        try:
            final_job = await run_job_on_pod(
                db_path=self.db_path,
                job=job,
                pod=ready_pod,
                runpod_client=runpod_client,
            )
            return final_job

        except Exception as e:
            # Non-managed jobs should stay in RUNNING status with error metadata
            # instead of terminalizing to FAILED. This allows users to inspect
            # the pod and logs before manually stopping.
            if not job.managed:
                current_job = await update_job_metadata(
                    self.db_path,
                    job.id,
                    error_message=str(e),
                    message="Execution failed; awaiting pxq stop",
                )
                return current_job

            # Managed jobs follow the auto-cleanup path to FAILED
            current_job = await update_job_status(
                self.db_path,
                job.id,
                JobStatus.FAILED,
                message="Execution failed",
                error_message=str(e),
            )
            # Still try to stop managed pods
            if job.pod_id:
                return await managed_stop(
                    self.db_path,
                    job.id,
                    job.pod_id,
                    runpod_client,
                    final_status=JobStatus.FAILED,
                    final_message="Pod deleted after execution exception",
                    final_error_message=str(e),
                    final_exit_code=current_job.exit_code,
                )
            return current_job

    async def process_job(self, job: Job) -> Job:
        """Execute a job based on its provider."""
        if job.provider == "local":
            return await self.process_local_job(job)
        elif job.provider == "runpod":
            return await self.process_runpod_job(job)
        else:
            if job.id is None:
                raise ValueError("job.id is required")
            return await update_job_status(
                self.db_path,
                job.id,
                JobStatus.FAILED,
                message=f"Unknown provider: {job.provider}",
                error_message=f"Provider '{job.provider}' is not supported",
            )


async def run_executor_loop(
    db_path: Path | str, settings: Settings | None = None
) -> None:
    """Background task that processes jobs in PROVISIONING state."""
    settings = settings or Settings()
    executor = JobExecutor(db_path, settings)

    while True:
        try:
            provisioning_jobs = await list_jobs(db_path, status=JobStatus.PROVISIONING)
            for job in provisioning_jobs:
                if job.id is None:
                    continue
                try:
                    await executor.process_job(job)
                except Exception as e:
                    logger.exception(f"Failed to process job {job.id}: {e}")
                    await update_job_status(
                        db_path,
                        job.id,
                        JobStatus.FAILED,
                        message="Executor error",
                        error_message=str(e),
                    )
        except Exception as e:
            logger.exception(f"Executor loop error: {e}")

        await asyncio.sleep(0.5)


async def stop_local_job(db_path: Path | str, job_id: int) -> bool:
    """Stop a running local job by its process group.

    Sends SIGTERM to the process group, waits for graceful shutdown,
    then sends SIGKILL if needed. Updates job status to STOPPED.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database.
    job_id : int
        ID of the job to stop.

    Returns
    -------
    bool
        True if job was stopped successfully, False if job was not running
        or had no local_pid.
    """
    from pxq.storage import get_job, update_job_field, update_job_status

    job = await get_job(db_path, job_id)
    if job is None or job.local_pid is None:
        return False

    # Stop the process group
    stopped = stop_local_process(job.local_pid, timeout=5.0)

    # Transition through STOPPING -> STOPPED
    await update_job_status(
        db_path,
        job_id,
        JobStatus.STOPPING,
        message="Local job stopping",
    )

    if stopped:
        await update_job_status(
            db_path,
            job_id,
            JobStatus.STOPPED,
            message="Local job stopped by user",
        )
        # Clear local_pid explicitly (COALESCE doesn't clear NULL values)
        await update_job_field(
            db_path,
            job_id,
            "local_pid",
            None,
        )
    else:
        # Process was already dead, still mark as stopped
        await update_job_status(
            db_path,
            job_id,
            JobStatus.STOPPED,
            message="Local job process not found (already dead)",
        )
        # Clear local_pid explicitly
        await update_job_field(
            db_path,
            job_id,
            "local_pid",
            None,
        )

    return True
