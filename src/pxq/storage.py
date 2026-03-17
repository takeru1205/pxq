"""pxq Storage - SQLite database operations for job management."""

from __future__ import annotations

import json

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from pxq.models import (
    Artifact,
    InvalidStateTransitionError,
    Job,
    JobEvent,
    JobStatus,
    validate_transition,
)


async def init_db(db_path: Path | str) -> None:
    """Initialize the SQLite database with required tables.

    This function is idempotent - safe to call multiple times.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database file.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(path) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                provider TEXT NOT NULL DEFAULT 'local',
                managed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                exit_code INTEGER,
                pod_id TEXT,
                workdir TEXT,
                gpu_type TEXT,
                cpu_count INTEGER,
                volume_id TEXT,
                region TEXT,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                from_status TEXT,
                to_status TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                message TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                artifact_type TEXT NOT NULL,
                path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                content TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_job_id ON artifacts(job_id);
            """
        )

        cursor = await db.execute("PRAGMA table_info(jobs)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "region" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN region TEXT")
        if "secure_cloud" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN secure_cloud INTEGER")
        if "cpu_flavor_ids" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN cpu_flavor_ids TEXT")
        if "env" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN env TEXT")
        if "volume_mount_path" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN volume_mount_path TEXT")
        if "image_name" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN image_name TEXT")
        if "template_id" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN template_id TEXT")
        if "local_pid" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN local_pid INTEGER")

        await db.commit()


def _row_to_job(row: aiosqlite.Row) -> Job:
    """Convert a database row to a Job model."""
    return Job(
        id=row["id"],
        command=row["command"],
        status=JobStatus(row["status"]),
        provider=row["provider"],
        managed=bool(row["managed"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        started_at=datetime.fromisoformat(row["started_at"])
        if row["started_at"]
        else None,
        finished_at=datetime.fromisoformat(row["finished_at"])
        if row["finished_at"]
        else None,
        exit_code=row["exit_code"],
        pod_id=row["pod_id"],
        workdir=row["workdir"],
        gpu_type=row["gpu_type"],
        cpu_count=row["cpu_count"],
        volume_id=row["volume_id"],
        region=row["region"],
        secure_cloud=bool(row["secure_cloud"])
        if row["secure_cloud"] is not None
        else None,
        cpu_flavor_ids=json.loads(row["cpu_flavor_ids"])
        if row["cpu_flavor_ids"]
        else None,
        env=json.loads(row["env"]) if row["env"] else None,
        volume_mount_path=row["volume_mount_path"],
        image_name=row["image_name"],
        template_id=row["template_id"],
        error_message=row["error_message"],
        local_pid=row["local_pid"],
    )


def _row_to_job_event(row: aiosqlite.Row) -> JobEvent:
    """Convert a database row to a JobEvent model."""
    return JobEvent(
        id=row["id"],
        job_id=row["job_id"],
        from_status=JobStatus(row["from_status"]) if row["from_status"] else None,
        to_status=JobStatus(row["to_status"]),
        timestamp=datetime.fromisoformat(row["timestamp"]),
        message=row["message"],
    )


def _row_to_artifact(row: aiosqlite.Row) -> Artifact:
    """Convert a database row to an Artifact model."""
    # Handle content column - use bracket notation with key check for nullable columns
    # sqlite3.Row does not have .get() method, so we must check key existence first
    content_value = row["content"] if "content" in row.keys() else None
    return Artifact(
        id=row["id"],
        job_id=row["job_id"],
        artifact_type=row["artifact_type"],
        path=row["path"],
        size_bytes=row["size_bytes"],
        content=content_value if content_value else None,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


async def create_job(db_path: Path | str, job: Job) -> Job:
    """Create a new job in the database.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database file.
    job : Job
        Job model to create.

    Returns
    -------
    Job
        Created job with assigned ID.
    """
    now = datetime.now(UTC).isoformat()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            INSERT INTO jobs (
                command, status, provider, managed, created_at, updated_at,
                started_at, finished_at, exit_code, pod_id, workdir,
                gpu_type, cpu_count, volume_id, region, secure_cloud, cpu_flavor_ids, env, volume_mount_path, image_name, template_id, error_message, local_pid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.command,
                job.status.value,
                job.provider,
                int(job.managed),
                now,
                now,
                job.started_at.isoformat() if job.started_at else None,
                job.finished_at.isoformat() if job.finished_at else None,
                job.exit_code,
                job.pod_id,
                job.workdir,
                job.gpu_type,
                job.cpu_count,
                job.volume_id,
                job.region,
                int(job.secure_cloud) if job.secure_cloud is not None else None,
                json.dumps(job.cpu_flavor_ids) if job.cpu_flavor_ids else None,
                json.dumps(job.env) if job.env else None,
                job.volume_mount_path,
                job.image_name,
                job.template_id,
                job.error_message,
                job.local_pid,
            ),
        )
        job_id = cursor.lastrowid

        await db.execute(
            """
            INSERT INTO job_events (job_id, from_status, to_status, timestamp, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, None, job.status.value, now, "Job created"),
        )
        await db.commit()

        job.id = job_id
        job.created_at = datetime.fromisoformat(now)
        job.updated_at = datetime.fromisoformat(now)
        return job


async def get_job(db_path: Path | str, job_id: int) -> Optional[Job]:
    """Get a job by ID.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database file.
    job_id : int
        Job ID to retrieve.

    Returns
    -------
    Optional[Job]
        Job model if found, None otherwise.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM jobs WHERE id = ?",
            (job_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_job(row)


async def list_jobs(
    db_path: Path | str,
    status: Optional[JobStatus] = None,
    include_all: bool = False,
) -> list[Job]:
    """List jobs, optionally filtered by status.

    By default, excludes terminal states (succeeded, failed, stopped, cancelled)
    unless include_all is True.

    Visibility semantics (derived from status, not filter changes):
    - Non-managed RunPod jobs stay RUNNING after remote command completion,
      awaiting explicit pxq stop. Since RUNNING is not terminal, they appear
      in the default view.
    - Managed RunPod jobs that complete successfully end at SUCCEEDED status.
      Since SUCCEEDED is terminal, they are excluded from the default view.
    - Manual stop via pxq stop always results in STOPPED (terminal, hidden).

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database file.
    status : Optional[JobStatus]
        Filter by specific status.
    include_all : bool
        Include all jobs including terminal states.

    Returns
    -------
    list[Job]
        List of matching jobs.
    """
    terminal_states = {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.STOPPED,
        JobStatus.CANCELLED,
    }

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        if status is not None:
            cursor = await db.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC",
                (status.value,),
            )
        elif include_all:
            cursor = await db.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC",
            )
        else:
            placeholders = ",".join("?" * len(terminal_states))
            cursor = await db.execute(
                f"SELECT * FROM jobs WHERE status NOT IN ({placeholders}) ORDER BY created_at DESC",
                tuple(s.value for s in terminal_states),
            )

        rows = await cursor.fetchall()
        return [_row_to_job(row) for row in rows]


async def update_job_status(
    db_path: Path | str,
    job_id: int,
    new_status: JobStatus,
    message: Optional[str] = None,
    exit_code: Optional[int] = None,
    error_message: Optional[str] = None,
    pod_id: Optional[str] = None,
    local_pid: Optional[int] = None,
) -> Job:
    """Update a job's status with state transition validation.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database file.
    job_id : int
        Job ID to update.
    new_status : JobStatus
        New status to set.
    message : Optional[str]
        Optional message for the event log.
    exit_code : Optional[int]
        Exit code (for succeeded/failed states).
    error_message : Optional[str]
        Error message (for failed state).
    pod_id : Optional[str]
        RunPod pod ID (for provisioning state).
    local_pid : Optional[int]
        Local process ID (for local execution).
    Returns
    -------
    Job
        Updated job model.

    Raises
    ------
    ValueError
        If job not found.
    InvalidStateTransitionError
        If the state transition is invalid.
    """
    job = await get_job(db_path, job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")

    validate_transition(job.status, new_status)

    now = datetime.now(UTC)
    now_iso = now.isoformat()

    terminal_states = {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.STOPPED,
        JobStatus.CANCELLED,
    }
    finished_at = now_iso if new_status in terminal_states else None
    started_at = now_iso if new_status == JobStatus.RUNNING else None

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE jobs SET
                status = ?,
                updated_at = ?,
                started_at = COALESCE(?, started_at),
                finished_at = COALESCE(?, finished_at),
                exit_code = COALESCE(?, exit_code),
                error_message = COALESCE(?, error_message),
                pod_id = COALESCE(?, pod_id),
                local_pid = COALESCE(?, local_pid)
            WHERE id = ?
            """,
            (
                new_status.value,
                now_iso,
                started_at,
                finished_at,
                exit_code,
                error_message,
                pod_id,
                local_pid,
                job_id,
            ),
        )

        await db.execute(
            """
            INSERT INTO job_events (job_id, from_status, to_status, timestamp, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, job.status.value, new_status.value, now_iso, message),
        )
        await db.commit()

    job.status = new_status
    job.updated_at = now
    if started_at:
        job.started_at = now
    if finished_at:
        job.finished_at = now
    if exit_code is not None:
        job.exit_code = exit_code
    if error_message is not None:
        job.error_message = error_message
    if pod_id is not None:
        job.pod_id = pod_id
    if local_pid is not None:
        job.local_pid = local_pid

    return job


async def get_job_events(db_path: Path | str, job_id: int) -> list[JobEvent]:
    """Get all events for a job.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database file.
    job_id : int
        Job ID to get events for.

    Returns
    -------
    list[JobEvent]
        List of job events, ordered by timestamp.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM job_events WHERE job_id = ? ORDER BY timestamp ASC",
            (job_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_job_event(row) for row in rows]


async def create_artifact(
    db_path: Path | str,
    job_id: int,
    artifact_type: str,
    path: str,
    size_bytes: int = 0,
    content: str | None = None,
) -> Artifact:
    """Create an artifact record.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database file.
    job_id : int
        Associated job ID.
    artifact_type : str
        Type of artifact (e.g., "log", "output").
    path : str
        File path or identifier.
    size_bytes : int
        Artifact size in bytes.

    Returns
    -------
    Artifact
        Created artifact with assigned ID.
    """
    now = datetime.now(UTC).isoformat()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            INSERT INTO artifacts (job_id, artifact_type, path, size_bytes, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)

            """,
            (job_id, artifact_type, path, size_bytes, content, now),
        )
        artifact_id = cursor.lastrowid
        await db.commit()

        return Artifact(
            id=artifact_id,
            job_id=job_id,
            artifact_type=artifact_type,
            path=path,
            size_bytes=size_bytes,
            content=content,
            created_at=datetime.fromisoformat(now),
        )


async def get_artifacts(db_path: Path | str, job_id: int) -> list[Artifact]:
    """Get all artifacts for a job.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database file.
    job_id : int
        Job ID to get artifacts for.

    Returns
    -------
    list[Artifact]
        List of artifacts.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM artifacts WHERE job_id = ? ORDER BY created_at ASC",
            (job_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_artifact(row) for row in rows]


async def count_jobs_by_status(db_path: Path | str) -> dict[JobStatus, int]:
    """Count jobs grouped by status.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database file.

    Returns
    -------
    dict[JobStatus, int]
        Dictionary mapping status to count.
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT status, COUNT(*) as count FROM jobs GROUP BY status"
        )
        rows = await cursor.fetchall()
        return {JobStatus(row["status"]): row["count"] for row in rows}


async def update_job_field(
    db_path: Path | str,
    job_id: int,
    field: str,
    value: Any,
) -> Job:
    """Update a single job field without state transition validation.

    Use this for metadata updates like local_pid that don't require
    state machine validation.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database file.
    job_id : int
        Job ID to update.
    field : str
        Field name to update (e.g., 'local_pid', 'pod_id').
    value : Any
        New value for the field.

    Raises
    ------
    ValueError
        If job not found or field is invalid.
    """
    # Explicit SQL queries for each allowed field - no string interpolation
    # to eliminate any possibility of SQL injection
    field_queries: dict[str, str] = {
        "local_pid": "UPDATE jobs SET local_pid = ? WHERE id = ?",
        "pod_id": "UPDATE jobs SET pod_id = ? WHERE id = ?",
    }

    if field not in field_queries:
        raise ValueError(
            f"Invalid field: {field}. Must be one of {set(field_queries.keys())}"
        )

    job = await get_job(db_path, job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            field_queries[field],
            (value, job_id),
        )
        await db.commit()

    # Update the job model
    setattr(job, field, value)
    return job


async def update_job_metadata(
    db_path: Path | str,
    job_id: int,
    exit_code: Optional[int] = None,
    error_message: Optional[str] = None,
    message: Optional[str] = None,
) -> Job:
    """Update job metadata without changing status.

    This helper updates exit_code, error_message, and updated_at WITHOUT
    changing the job status. Use this for non-managed jobs that need to
    stay in RUNNING status while capturing completion metadata.

    The helper still creates an event record for audit trail.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database file.
    job_id : int
        Job ID to update.
    exit_code : Optional[int]
        Exit code to record (optional).
    error_message : Optional[str]
        Error message to record (optional).
    message : Optional[str]
        Optional message for the event log.

    Returns
    -------
    Job
        Updated job model.

    Raises
    ------
    ValueError
        If job not found.
    """
    job = await get_job(db_path, job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")

    now = datetime.now(UTC)
    now_iso = now.isoformat()

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE jobs SET
                updated_at = ?,
                exit_code = COALESCE(?, exit_code),
                error_message = COALESCE(?, error_message)
            WHERE id = ?
            """,
            (
                now_iso,
                exit_code,
                error_message,
                job_id,
            ),
        )

        await db.execute(
            """
            INSERT INTO job_events (job_id, from_status, to_status, timestamp, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job.status.value,
                job.status.value,
                now_iso,
                message
                or f"Metadata updated: exit_code={exit_code}, error_message={error_message}",
            ),
        )
        await db.commit()

    # Update the job model
    job.updated_at = now
    if exit_code is not None:
        job.exit_code = exit_code
    if error_message is not None:
        job.error_message = error_message

    return job
