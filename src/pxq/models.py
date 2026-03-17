"""pxq Models - Data models for jobs and state machine."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Job status enumeration with state machine semantics.

    Valid transitions:
    - queued -> provisioning, cancelled
    - provisioning -> uploading, failed, cancelled
    - uploading -> running, failed, cancelled
    - running -> succeeded, failed, stopping, cancelled
    - succeeded -> stopping (for managed jobs)
    - failed -> stopping (for managed jobs)
    - stopping -> stopped, failed
    - stopped -> (terminal)
    - cancelled -> (terminal)
    """

    QUEUED = "queued"
    PROVISIONING = "provisioning"
    UPLOADING = "uploading"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"
    CANCELLED = "cancelled"


# Valid state transitions mapping
VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.PROVISIONING, JobStatus.CANCELLED},
    JobStatus.PROVISIONING: {
        JobStatus.UPLOADING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.UPLOADING: {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.RUNNING: {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.STOPPING,
        JobStatus.CANCELLED,
    },
    JobStatus.SUCCEEDED: {JobStatus.STOPPING},
    JobStatus.FAILED: {JobStatus.STOPPING},
    JobStatus.STOPPING: {JobStatus.STOPPED, JobStatus.FAILED, JobStatus.SUCCEEDED},
    JobStatus.STOPPED: set(),  # Terminal state
    JobStatus.CANCELLED: set(),  # Terminal state
}


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, current: JobStatus, target: JobStatus) -> None:
        self.current = current
        self.target = target
        valid = VALID_TRANSITIONS.get(current, set())
        super().__init__(
            f"Invalid state transition: {current.value} -> {target.value}. "
            f"Valid transitions from {current.value}: {[s.value for s in valid]}"
        )


def validate_transition(current: JobStatus, target: JobStatus) -> None:
    """Validate a state transition.

    Parameters
    ----------
    current : JobStatus
        Current job status.
    target : JobStatus
        Target job status.

    Raises
    ------
    InvalidStateTransitionError
        If the transition is not valid.
    """
    valid_targets = VALID_TRANSITIONS.get(current, set())
    if target not in valid_targets:
        raise InvalidStateTransitionError(current, target)


class Job(BaseModel):
    """Job model representing a single job in the queue.

    Attributes
    ----------
    id : Optional[int]
        Unique job identifier (assigned by database).
    command : str
        Command to execute.
    status : JobStatus
        Current job status.
    provider : str
        Provider name (e.g., "local", "runpod").
    managed : bool
        Whether to stop the pod after job completion.
    created_at : datetime
        Job creation timestamp.
    updated_at : datetime
        Last update timestamp.
    started_at : Optional[datetime]
        Job start timestamp (when entering running state).
    finished_at : Optional[datetime]
        Job finish timestamp (when entering terminal state).
    exit_code : Optional[int]
        Process exit code.
    pod_id : Optional[str]
        RunPod pod ID (if applicable).
    workdir : Optional[str]
        Working directory for the job.
    gpu_type : Optional[str]
        GPU type specification.
    cpu_count : Optional[int]
        CPU count specification.
    volume_id : Optional[str]
        RunPod volume ID (if applicable).
    volume_mount_path : Optional[str]
        Mount path for the network volume (default: /volume).
    region : Optional[str]
        RunPod region/data center (e.g., "EU-RO-1").
    secure_cloud : Optional[bool]
        Use Secure Cloud instead of Community Cloud.
    cpu_flavor_ids : Optional[list[str]]
        List of RunPod CPU flavors (e.g., ["cpu3c", "cpu3g"]).
        Available: cpu3c, cpu3g, cpu3m, cpu5c, cpu5g, cpu5m
    error_message : Optional[str]
        Error message if job failed.
    """

    id: Optional[int] = None
    command: str
    status: JobStatus = JobStatus.QUEUED
    provider: str = "local"
    managed: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
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
    local_pid: Optional[int] = None  # Internal: PID for local process management
    model_config = {"from_attributes": True}


class JobEvent(BaseModel):
    """Job event model for tracking state transitions.

    Attributes
    ----------
    id : Optional[int]
        Unique event identifier (assigned by database).
    job_id : int
        Associated job ID.
    from_status : Optional[JobStatus]
        Previous status (None for initial state).
    to_status : JobStatus
        New status.
    timestamp : datetime
        Event timestamp.
    message : Optional[str]
        Optional message describing the event.
    """

    id: Optional[int] = None
    job_id: int
    from_status: Optional[JobStatus] = None
    to_status: JobStatus
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    message: Optional[str] = None

    model_config = {"from_attributes": True}


class Artifact(BaseModel):
    """Artifact model for storing job outputs and logs.

    Attributes
    ----------
    id : Optional[int]
        Unique artifact identifier (assigned by database).
    job_id : int
        Associated job ID.
    artifact_type : str
        Type of artifact (e.g., "log", "output", "stdout", "stderr").
    path : str
        File path or identifier.
    size_bytes : int
        Artifact size in bytes.
    content : Optional[str]
        Log content (text) for log artifacts.
    created_at : datetime
        Artifact creation timestamp.
    """

    id: Optional[int] = None
    job_id: int
    artifact_type: str
    path: str
    size_bytes: int = 0
    content: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"from_attributes": True}
