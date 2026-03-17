from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from pxq.models import Job, JobStatus
from pxq.providers.runpod_client import PodResponse, RunPodClient
from pxq.storage import update_job_status
from pxq.log_collector import start_log_collection


class SSHError(Exception):
    """Raised when SSH transfer or command execution fails."""


async def upload_directory(
    local_dir: Path | str,
    host: str,
    port: int,
    user: str = "root",
    remote_dir: str = "/workspace",
    timeout_seconds: float = 600.0,
) -> bool:
    """Upload a local working directory to a remote pod via rsync over SSH.

    Parameters
    ----------
    local_dir : Path | str
        Local directory to upload.
    host : str
        Remote host address.
    port : int
        Remote SSH port.
    user : str
        SSH username. Defaults to ``root``.
    remote_dir : str
        Remote destination directory. Defaults to ``/workspace``.
    timeout_seconds : float
        Maximum transfer time before timeout.

    Returns
    -------
    bool
        ``True`` when upload succeeds, otherwise ``False``.

    Raises
    ------
    SSHError
        If the rsync process cannot be started or times out.
    """
    local_path = Path(local_dir)
    if not local_path.exists() or not local_path.is_dir():
        return False

    ssh_base = [
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
    ]

    mkdir_command = [
        "ssh",
        *ssh_base,
        "-p",
        str(port),
        f"{user}@{host}",
        f"mkdir -p {shlex.quote(remote_dir)}",
    ]

    scp_command = [
        "scp",
        *ssh_base,
        "-P",
        str(port),
        "-r",
        f"{local_path}/.",
        f"{user}@{host}:{remote_dir}",
    ]

    try:
        mkdir_proc = await asyncio.create_subprocess_exec(
            *mkdir_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise SSHError(
            f"Failed to start ssh process for remote directory setup: {exc}"
        ) from exc

    try:
        mkdir_stdout, mkdir_stderr = await asyncio.wait_for(
            mkdir_proc.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError as exc:
        # タイムアウト時にプロセスを明示的に終了し、ゾンビ化を避ける。
        mkdir_proc.kill()
        await mkdir_proc.wait()
        raise SSHError(
            f"Directory setup timed out after {timeout_seconds} seconds"
        ) from exc

    if mkdir_proc.returncode != 0:
        detail = (
            mkdir_stderr.decode(errors="replace").strip()
            or mkdir_stdout.decode(errors="replace").strip()
            or "unknown ssh mkdir failure"
        )
        raise SSHError(
            f"Failed to prepare remote directory with exit code {mkdir_proc.returncode}: {detail}"
        )

    try:
        scp_proc = await asyncio.create_subprocess_exec(
            *scp_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise SSHError(f"Failed to start scp process: {exc}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            scp_proc.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError as exc:
        scp_proc.kill()
        await scp_proc.wait()
        raise SSHError(f"SCP upload timed out after {timeout_seconds} seconds") from exc

    if scp_proc.returncode != 0:
        stderr_text = stderr.decode(errors="replace").strip()
        stdout_text = stdout.decode(errors="replace").strip()
        detail = stderr_text or stdout_text or "unknown scp failure"
        raise SSHError(
            f"SCP upload failed with exit code {scp_proc.returncode}: {detail}"
        )

    return True


async def execute_remote_command(
    command: str,
    host: str,
    port: int,
    user: str = "root",
    remote_dir: str = "/workspace",
    timeout_seconds: float = 3600.0,
) -> int:
    """Execute a command on a remote pod via SSH and return its exit code.

    Parameters
    ----------
    command : str
        Command to execute on the remote host.
    host : str
        Remote host address.
    port : int
        Remote SSH port.
    user : str
        SSH username. Defaults to ``root``.
    remote_dir : str
        Working directory on the remote pod. Defaults to ``/workspace``.
    timeout_seconds : float
        Maximum execution time before timeout.

    Returns
    -------
    int
        Remote command exit code.

    Raises
    ------
    SSHError
        If the ssh process cannot be started, times out, or reports connection failure.
    """
    remote_command = f"cd {shlex.quote(remote_dir)} && {command}"
    ssh_command = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        "-p",
        str(port),
        f"{user}@{host}",
        remote_command,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *ssh_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise SSHError(f"Failed to start ssh process: {exc}") from exc

    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        # タイムアウト時は即座にkillし、次ジョブへの影響を防ぐ。
        proc.kill()
        await proc.wait()
        raise SSHError(
            f"Remote command timed out after {timeout_seconds} seconds"
        ) from exc

    if proc.returncode is None:
        raise SSHError("SSH process finished without return code")

    if proc.returncode == 255:
        stderr_text = stderr.decode(errors="replace").strip()
        raise SSHError(f"SSH connection failed: {stderr_text}")

    return proc.returncode


async def managed_stop(
    db_path: Path | str,
    job_id: int,
    pod_id: str,
    runpod_client: RunPodClient,
) -> Job:
    """Stop a managed pod and persist stopping/stopped lifecycle states.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database.
    job_id : int
        Target job ID.
    pod_id : str
        Pod ID to stop.
    runpod_client : RunPodClient
        RunPod client used to request pod stop.

    Returns
    -------
    Job
        Updated job state after stop handling.
    """
    job = await update_job_status(
        db_path,
        job_id,
        JobStatus.STOPPING,
        message="Managed stop requested",
    )

    try:
        await runpod_client.stop_pod(pod_id)
    except Exception as exc:
        return await update_job_status(
            db_path,
            job_id,
            JobStatus.FAILED,
            message="Managed stop failed",
            error_message=f"Failed to stop pod: {exc}",
            exit_code=job.exit_code,
        )

    return await update_job_status(
        db_path,
        job_id,
        JobStatus.STOPPED,
        message="Pod stopped",
    )


async def run_job_on_pod(
    db_path: Path | str,
    job: Job,
    pod: PodResponse,
    runpod_client: RunPodClient,
    ssh_user: str = "root",
    remote_dir: str = "/workspace",
    upload_timeout_seconds: float = 600.0,
    execution_timeout_seconds: float = 3600.0,
) -> Job:
    """Upload workdir to a pod, execute command remotely, and persist lifecycle.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database.
    job : Job
        Job to execute. ``job.id`` must be present.
    pod : PodResponse
        Provisioned pod information including SSH endpoint.
    runpod_client : RunPodClient
        RunPod client used for managed stop.
    ssh_user : str
        SSH username. Defaults to ``root``.
    remote_dir : str
        Remote working directory. Defaults to ``/workspace``.
    upload_timeout_seconds : float
        Timeout for directory upload.
    execution_timeout_seconds : float
        Timeout for remote command execution.

    Returns
    -------
    Job
        Final job state after execution and optional managed stop.
    """
    if job.id is None:
        raise ValueError("job.id is required")

    host = pod.ssh_host
    if host is None:
        current_job = await update_job_status(
            db_path,
            job.id,
            JobStatus.FAILED,
            message="Missing SSH host",
            error_message="Pod does not expose a public SSH host",
        )
        if job.managed and job.pod_id:
            return await managed_stop(db_path, job.id, job.pod_id, runpod_client)
        return current_job

    current_job = job
    stop_event: asyncio.Event | None = None
    log_task: asyncio.Task[None] | None = None
    try:
        current_job = await update_job_status(
            db_path,
            job.id,
            JobStatus.UPLOADING,
            message="Uploading working directory",
            pod_id=pod.id,
        )

        upload_success = await upload_directory(
            local_dir=job.workdir or ".",
            host=host,
            port=pod.ssh_port,
            user=ssh_user,
            remote_dir=remote_dir,
            timeout_seconds=upload_timeout_seconds,
        )
        if not upload_success:
            current_job = await update_job_status(
                db_path,
                job.id,
                JobStatus.FAILED,
                message="Directory upload failed",
                error_message="Failed to upload working directory via SSH",
            )
            if job.managed and job.pod_id:
                return await managed_stop(db_path, job.id, job.pod_id, runpod_client)
            return current_job

        current_job = await update_job_status(
            db_path,
            job.id,
            JobStatus.RUNNING,
            message="Remote command started",
        )

        # Start log collection in parallel
        stop_event = asyncio.Event()
        log_task = asyncio.create_task(
            start_log_collection(
                db_path=db_path,
                job_id=job.id,
                host=host,
                port=pod.ssh_port,
                stop_event=stop_event,
            )
        )

        exit_code = await execute_remote_command(
            command=job.command,
            host=host,
            port=pod.ssh_port,
            user=ssh_user,
            remote_dir=remote_dir,
            timeout_seconds=execution_timeout_seconds,
        )

        # Stop log collection
        if stop_event is not None and log_task is not None:
            stop_event.set()
            try:
                await asyncio.wait_for(log_task, timeout=5.0)
            except asyncio.TimeoutError:
                log_task.cancel()

        if exit_code == 0:
            current_job = await update_job_status(
                db_path,
                job.id,
                JobStatus.SUCCEEDED,
                message="Command completed",
                exit_code=exit_code,
            )
        else:
            current_job = await update_job_status(
                db_path,
                job.id,
                JobStatus.FAILED,
                message="Command failed",
                exit_code=exit_code,
                error_message=f"Remote command exited with code {exit_code}",
            )
    except SSHError as exc:
        current_job = await update_job_status(
            db_path,
            job.id,
            JobStatus.FAILED,
            message="SSH execution failed",
            error_message=str(exc),
        )

        # Stop log collection on SSH error
        if stop_event is not None and log_task is not None:
            stop_event.set()
            try:
                await asyncio.wait_for(log_task, timeout=5.0)
            except asyncio.TimeoutError:
                log_task.cancel()

    if job.managed and job.pod_id:
        # managedジョブは成功/失敗を問わず停止を保証する設計にする。
        return await managed_stop(db_path, job.id, job.pod_id, runpod_client)

    return current_job
