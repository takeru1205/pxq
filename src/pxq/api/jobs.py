"""Job API endpoints for pxq server."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from pxq.config import Settings
from pxq.models import Job, JobStatus
from pxq.storage import (
    create_job,
    get_job,
    list_jobs,
    get_artifacts,
    update_job_status,
    update_job_field,
)
from pxq.providers.runpod_exec import managed_stop
from pxq.executor import stop_local_job
from pxq.providers.runpod_client import RunPodClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


# Request/Response models
class JobCreateRequest(BaseModel):
    """Request model for creating a new job.

    Attributes
    ----------
    command : str
        Command to execute.
    provider : str
        Provider name (e.g., "local", "runpod").
    managed : bool
        Whether to stop the pod after job completion.
    workdir : Optional[str]
        Working directory for the job.
    gpu_type : Optional[str]
        GPU type specification.
    cpu_count : Optional[int]
        CPU count specification.
    volume_id : Optional[str]
        RunPod volume ID (if applicable).
    region : Optional[str]
        RunPod data center (e.g., "EU-RO-1").
    secure_cloud : Optional[bool]
        Use Secure Cloud instead of Community Cloud.
    cpu_flavor_ids : Optional[list[str]]
        List of CPU flavors. Available: cpu3c, cpu3g, cpu3m, cpu5c, cpu5g, cpu5m
    """

    command: str = Field(..., min_length=1, description="Command to execute")
    provider: str = Field(default="local", description="Provider name")
    managed: bool = Field(default=False, description="Stop pod after completion")
    workdir: Optional[str] = Field(default=None, description="Working directory")
    gpu_type: Optional[str] = Field(default=None, description="GPU type")
    cpu_count: Optional[int] = Field(default=None, ge=1, description="CPU count")
    volume_id: Optional[str] = Field(default=None, description="Volume ID")
    volume_mount_path: Optional[str] = Field(
        default=None, description="Mount path for network volume"
    )
    region: Optional[str] = Field(default=None, description="RunPod data center")
    secure_cloud: Optional[bool] = Field(default=None, description="Use Secure Cloud")
    cpu_flavor_ids: Optional[list[str]] = Field(
        default=None, description="CPU flavor IDs"
    )
    env: Optional[dict[str, str]] = Field(
        default=None, description="Environment variables (RunPod secrets)"
    )
    template_id: Optional[str] = Field(default=None, description="RunPod Template ID")
    image_name: Optional[str] = Field(
        default=None, description="RunPod container image"
    )


class JobResponse(BaseModel):
    """Response model for job data.

    Attributes
    ----------
    id : int
        Unique job identifier.
    command : str
        Command to execute.
    status : JobStatus
        Current job status.
    provider : str
        Provider name.
    managed : bool
        Whether to stop the pod after job completion.
    created_at : str
        Job creation timestamp (ISO format).
    updated_at : str
        Last update timestamp (ISO format).
    started_at : Optional[str]
        Job start timestamp (ISO format).
    finished_at : Optional[str]
        Job finish timestamp (ISO format).
    exit_code : Optional[int]
        Process exit code.
    pod_id : Optional[str]
        RunPod pod ID.
    workdir : Optional[str]
        Working directory.
    gpu_type : Optional[str]
        GPU type.
    cpu_count : Optional[int]
        CPU count.
    volume_id: Optional[str]
        Volume ID.
    volume_mount_path: Optional[str]
        Mount path for network volume.
        Volume ID.
    region : Optional[str]
        RunPod data center.
    secure_cloud : Optional[bool]
        Use Secure Cloud.
    cpu_flavor_ids : Optional[list[str]]
        CPU flavor IDs.
    error_message : Optional[str]
        Error message if job failed.
    """

    id: int
    command: str
    status: JobStatus
    provider: str
    managed: bool
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    pod_id: Optional[str] = None
    workdir: Optional[str] = None
    gpu_type: Optional[str] = None
    cpu_count: Optional[int] = None
    volume_id: Optional[str] = None
    volume_mount_path: Optional[str] = None
    region: Optional[str] = None
    secure_cloud: Optional[bool] = None
    cpu_flavor_ids: Optional[list[str]] = None
    env: Optional[dict[str, str]] = None
    template_id: Optional[str] = None
    image_name: Optional[str] = None
    error_message: Optional[str] = None
    artifacts: Optional[list[dict]] = None

    @classmethod
    def from_job(cls, job: Job) -> "JobResponse":
        """Create a JobResponse from a Job model.

        Parameters
        ----------
        job : Job
            Job model to convert.

        Returns
        -------
        JobResponse
            Converted response model.
        """
        assert job.id is not None, "Job must have an ID"
        return cls(
            id=job.id,
            command=job.command,
            status=job.status,
            provider=job.provider,
            managed=job.managed,
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
            started_at=job.started_at.isoformat() if job.started_at else None,
            finished_at=job.finished_at.isoformat() if job.finished_at else None,
            exit_code=job.exit_code,
            pod_id=job.pod_id,
            workdir=job.workdir,
            gpu_type=job.gpu_type,
            cpu_count=job.cpu_count,
            volume_id=job.volume_id,
            volume_mount_path=job.volume_mount_path,
            region=job.region,
            secure_cloud=job.secure_cloud,
            cpu_flavor_ids=job.cpu_flavor_ids,
            env=job.env,
            template_id=job.template_id,
            image_name=job.image_name,
            error_message=job.error_message,
        )


class JobListResponse(BaseModel):
    """Response model for job list.

    Attributes
    ----------
    jobs : list[JobResponse]
        List of jobs.
    count : int
        Total number of jobs in the list.
    """

    jobs: list[JobResponse]
    count: int


def _get_db_path() -> str:
    """Get the database path from settings.

    Returns
    -------
    str
        Database path.
    """
    return str(Settings().db_path)


@router.post("", response_model=JobResponse, status_code=201)
async def create_job_endpoint(request: JobCreateRequest) -> JobResponse:
    """Create a new job."""
    job = Job(
        command=request.command,
        provider=request.provider,
        managed=request.managed,
        workdir=request.workdir,
        gpu_type=request.gpu_type,
        cpu_count=request.cpu_count,
        volume_id=request.volume_id,
        volume_mount_path=request.volume_mount_path,
        region=request.region,
        secure_cloud=request.secure_cloud,
        cpu_flavor_ids=request.cpu_flavor_ids,
        env=request.env,
        template_id=request.template_id,
        image_name=request.image_name,
    )
    created_job = await create_job(_get_db_path(), job)
    return JobResponse.from_job(created_job)


@router.get("", response_model=JobListResponse)
async def list_jobs_endpoint(
    all: bool = Query(default=False, description="Include terminal state jobs"),
) -> JobListResponse:
    """List jobs.

    By default, excludes terminal states (succeeded, failed, stopped, cancelled).
    Use the 'all' query parameter to include all jobs.

    Visibility semantics (derived from status, not filter logic):
    - Non-managed RunPod jobs stay RUNNING after remote command completion,
      awaiting explicit pxq stop. Since RUNNING is not terminal, they appear
      in the default list.
    - Managed RunPod jobs that complete successfully end at SUCCEEDED status.
      Since SUCCEEDED is terminal, they are excluded from the default list.
    - Manual stop via pxq stop always results in STOPPED (terminal, hidden).

    Parameters
    ----------
    all : bool
        Include all jobs including terminal states.

    Returns
    -------
    JobListResponse
        List of jobs.
    """
    jobs = await list_jobs(_get_db_path(), include_all=all)
    return JobListResponse(
        jobs=[JobResponse.from_job(job) for job in jobs],
        count=len(jobs),
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_endpoint(job_id: int) -> JobResponse:
    """Get a job by ID.

    Parameters
    ----------
    job_id : int
        Job ID to retrieve.

    Returns
    -------
    JobResponse
        Job details.

    Raises
    ------
    HTTPException
        If job not found (404).
    """
    job = await get_job(_get_db_path(), job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Fetch artifacts for this job with resilience to corruption
    artifacts = None
    try:
        artifacts_list = await get_artifacts(_get_db_path(), job_id)
        artifacts = (
            [
                {
                    "id": a.id,
                    "artifact_type": a.artifact_type,
                    "path": a.path,
                    "size_bytes": a.size_bytes,
                    "content": a.content,
                    "created_at": a.created_at.isoformat(),
                }
                for a in artifacts_list
            ]
            if artifacts_list
            else None
        )
    except Exception as e:
        logger.warning(
            "Failed to fetch artifacts for job %s: %s. Returning empty artifacts.",
            job_id,
            e,
        )
        artifacts = None

    response = JobResponse.from_job(job)
    response.artifacts = artifacts
    return response


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job_endpoint(job_id: int) -> JobResponse:
    """Cancel a job in queued, provisioning, or uploading state.

    Parameters
    ----------
    job_id : int
        Job ID to cancel.

    Returns
    -------
    JobResponse
        Cancelled job details.

    Raises
    ------
    HTTPException
        If job not found (404) or not in a cancelable state (400).
    """
    job = await get_job(_get_db_path(), job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Cancelable states: queued, provisioning, uploading
    cancelable_states = {JobStatus.QUEUED, JobStatus.PROVISIONING, JobStatus.UPLOADING}

    if job.status not in cancelable_states:
        # Provide helpful error message based on current state
        if job.status == JobStatus.RUNNING:
            detail = f"Cannot cancel job {job_id}: job is running. Use 'pxq stop' to stop a running job."
        elif job.status == JobStatus.STOPPING:
            detail = f"Cannot cancel job {job_id}: job is stopping."
        else:
            # Terminal states: succeeded, failed, stopped, cancelled
            detail = f"Cannot cancel job {job_id}: job is already in terminal state '{job.status.value}'"
        raise HTTPException(status_code=400, detail=detail)

    updated_job = await update_job_status(_get_db_path(), job_id, JobStatus.CANCELLED)
    return JobResponse.from_job(updated_job)


async def _stop_job(job: Job, db_path: str, settings: Settings) -> Job:
    """Execute stop logic for a single job (internal helper).

    Parameters
    ----------
    job : Job
        Job to stop (must be in RUNNING status).
    db_path : str
        Database path.
    settings : Settings
        Application settings.

    Returns
    -------
    Job
        Stopped job with status STOPPED.

    Raises
    ------
    HTTPException
        If provider-specific stop fails.
    """
    assert job.id is not None, "Job must have an ID"

    if job.provider == "runpod":
        if not settings.runpod_api_key:
            raise HTTPException(status_code=500, detail="RunPod API key not configured")
        if not job.pod_id:
            raise HTTPException(status_code=400, detail=f"Job {job.id} has no pod_id")
        runpod_client = RunPodClient(settings.runpod_api_key)
        return await managed_stop(
            db_path,
            job.id,
            job.pod_id,
            runpod_client,
            final_status=JobStatus.STOPPED,
            final_message="Stop API: Pod deleted",
            final_exit_code=job.exit_code,
            final_error_message=job.error_message,
        )

    elif job.provider == "local":
        # Local provider: stop process and update status
        success = await stop_local_job(db_path, job.id)
        if not success:
            # Job had no local_pid - still mark as stopped
            return await update_job_status(
                db_path,
                job.id,
                JobStatus.STOPPED,
                message="Stop API: Local job stopped (no pid found)",
            )
        # Read updated job
        updated_job = await get_job(db_path, job.id)
        assert updated_job is not None, "Job must exist after stop"
        return updated_job

    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {job.provider}")


@router.post("/{job_id}/stop", response_model=JobResponse)
async def stop_job_by_id_endpoint(job_id: int) -> JobResponse:
    """Stop a specific running job by ID.

    Parameters
    ----------
    job_id : int
        Job ID to stop.

    Returns
    -------
    JobResponse
        Stopped job details with status STOPPED.

    Raises
    ------
    HTTPException
        If job not found (404) or not in RUNNING status (400).
    """
    db_path = _get_db_path()
    settings = Settings()

    job = await get_job(db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status != JobStatus.RUNNING:
        # Provide helpful error message based on current state
        if job.status == JobStatus.STOPPING:
            detail = f"Cannot stop job {job_id}: job is already stopping."
        elif job.status in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.STOPPED,
            JobStatus.CANCELLED,
        }:
            detail = f"Cannot stop job {job_id}: job is already in terminal state '{job.status.value}'"
        elif job.status in {
            JobStatus.QUEUED,
            JobStatus.PROVISIONING,
            JobStatus.UPLOADING,
        }:
            detail = f"Cannot stop job {job_id}: job is in '{job.status.value}' state. Use 'pxq cancel {job_id}' to cancel."
        else:
            detail = f"Cannot stop job {job_id}: job is in '{job.status.value}' state, not RUNNING."
        raise HTTPException(status_code=400, detail=detail)

    stopped_job = await _stop_job(job, db_path, settings)
    return JobResponse.from_job(stopped_job)


@router.post("/stop", response_model=JobResponse)
async def stop_job_endpoint() -> JobResponse:
    """Stop a single running job.

    Only allows stopping when exactly one job is in RUNNING status.
    - 0 running jobs: returns 400 "No running jobs found"
    - 2+ running jobs: returns 400 "Multiple running jobs found: [ids...]"
    - 1 running job: stops based on provider type
      - RunPod: calls managed_stop() with delete_pod(), always transitions to STOPPED
      - Local: calls stop_local_job() with local_pid

    For RunPod jobs, existing exit_code and error_message are preserved through
    the stop transition. This applies to both live-running jobs and completion-pending
    non-managed jobs (jobs that have completed remotely but are awaiting explicit stop).

    Returns
    -------
    JobResponse
        Stopped job details with status STOPPED.

    Raises
    ------
    HTTPException
        If no running jobs (400) or multiple running jobs (400).
    """
    db_path = _get_db_path()
    settings = Settings()

    # Get all running jobs
    running_jobs = await list_jobs(db_path, status=JobStatus.RUNNING)

    # Case 1: No running jobs
    if len(running_jobs) == 0:
        # Check for cancelable jobs (provisioning, uploading)
        provisioning_jobs = await list_jobs(db_path, status=JobStatus.PROVISIONING)
        uploading_jobs = await list_jobs(db_path, status=JobStatus.UPLOADING)
        cancelable_count = len(provisioning_jobs) + len(uploading_jobs)

        if cancelable_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"No running jobs found. {cancelable_count} job(s) in provisioning/uploading state. Use 'pxq cancel <job_id>' to cancel.",
            )
        else:
            raise HTTPException(status_code=400, detail="No running jobs found")

    # Case 2: Multiple running jobs
    if len(running_jobs) >= 2:
        job_ids = [job.id for job in running_jobs if job.id is not None]
        raise HTTPException(
            status_code=400, detail=f"Multiple running jobs found: {job_ids}"
        )

    # Case 3: Exactly one running job
    job = running_jobs[0]
    stopped_job = await _stop_job(job, db_path, settings)
    return JobResponse.from_job(stopped_job)
