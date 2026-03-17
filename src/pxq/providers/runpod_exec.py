from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from pxq.models import Job, JobStatus
from pxq.providers.runpod_client import PodResponse, RunPodClient, RunPodAPIError
from pxq.providers.runpod_ssh import (
    SSHConnectionInfo,
    build_interactive_ssh_args,
    build_non_interactive_ssh_args,
)
from pxq.storage import update_job_status, update_job_metadata
from pxq.log_collector import start_log_collection


async def _collect_final_logs(
    db_path,
    job_id,
    host,
    port,
    user="root",
):
    """Collect final stdout/stderr logs from remote pod.

    This is a best-effort synchronous collection that runs after
    the main command completes. Only appends content not already
    persisted by the async log collector.
    """
    from pxq.storage import create_artifact, get_artifacts

    # Query existing artifacts to find what's already been persisted
    try:
        existing_artifacts = await get_artifacts(db_path, job_id)
    except Exception:
        existing_artifacts = []  # Best effort - continue if query fails

    # Calculate persisted byte count per (artifact_type, path)
    persisted_bytes = {}
    for artifact in existing_artifacts:
        key = (artifact.artifact_type, artifact.path)
        persisted_bytes[key] = persisted_bytes.get(key, 0) + artifact.size_bytes

    for log_path, artifact_type in [
        (REMOTE_STDOUT_PATH, "stdout"),
        (REMOTE_STDERR_PATH, "stderr"),
    ]:
        try:
            conn_info = _build_ssh_connection_info(host, port, user)
            ssh_command = build_non_interactive_ssh_args(conn_info) + ["cat", log_path]
            proc = await asyncio.create_subprocess_exec(
                *ssh_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)

            if proc.returncode == 0 and stdout is not None:
                content_text = stdout.decode("utf-8", errors="replace")
                # 空白のみのコンテンツでも artifact として保存（改行のみなどを保持）
                if content_text:
                    content_bytes = content_text.encode()
                    remote_len = len(content_bytes)

                    # Check how many bytes were already persisted for this path
                    key = (artifact_type, log_path)
                    already_persisted = persisted_bytes.get(key, 0)

                    # Skip if already persisted >= remote length
                    if already_persisted >= remote_len:
                        continue

                    # Append only the not-yet-persisted suffix
                    suffix = content_text[already_persisted:]
                    if suffix:
                        await create_artifact(
                            db_path,
                            job_id,
                            artifact_type=artifact_type,
                            path=log_path,
                            size_bytes=len(suffix.encode()),
                            content=suffix,
                        )

        except Exception:
            pass  # Best effort only


# Remote wrapper constants for stdout/stderr capture and exit code polling
REMOTE_STDOUT_PATH = "/workspace/pxq_stdout.log"
REMOTE_STDERR_PATH = "/workspace/pxq_stderr.log"
REMOTE_EXIT_CODE_PATH = "/workspace/pxq_exit_code"
REMOTE_DONE_PATH = "/workspace/pxq_done"


class SSHError(Exception):
    """Raised when SSH transfer or command execution fails."""


async def upload_directory(
    local_dir: Path | str,
    host: str,
    port: int,
    user: str = "root",
    remote_dir: str = "/workspace",
    timeout_seconds: float = 600.0,
    ignore_patterns: list[str] | None = None,
) -> bool:
    local_path = Path(local_dir)
    if not local_path.exists() or not local_path.is_dir():
        return False

    conn_info = _build_ssh_connection_info(host, port, user)

    mkdir_command = [
        *build_non_interactive_ssh_args(conn_info),
        f"mkdir -p {shlex.quote(remote_dir)}",
    ]

    # Create tar stream from local directory and pipe it to remote tar extract via SSH
    # Build tar command with exclude patterns if provided
    tar_stream_command = ["tar", "-C", str(local_path), "-cf", "-", "."]
    if ignore_patterns:
        # Insert --exclude options before the directory argument
        exclude_args = []
        for pattern in ignore_patterns:
            exclude_args.extend(["--exclude", pattern])
        tar_stream_command = (
            ["tar", "-C", str(local_path), "-cf", "-"] + exclude_args + ["."]
        )

    ssh_tar_command = [
        *build_non_interactive_ssh_args(conn_info),
        f"tar --no-same-owner -xf - -C {shlex.quote(remote_dir)}",
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

    # Execute tar streaming: run local tar to create archive, send to remote via SSH
    local_tar_proc = None  # Track for exception handling
    remote_tar_proc = None  # Track for exception handling

    try:
        # First, run local tar to generate the archive data

        local_tar_proc = await asyncio.create_subprocess_exec(
            *tar_stream_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Get the tar archive data from local tar command
        tar_stdout, tar_stderr = await asyncio.wait_for(
            local_tar_proc.communicate(), timeout=timeout_seconds
        )

        local_returncode = local_tar_proc.returncode

        # Check if local tar command succeeded
        if local_returncode != 0:
            detail = (
                tar_stderr.decode(errors="replace").strip()
                or "unknown local tar failure"
            )
            raise SSHError(
                f"Local tar command failed with exit code {local_returncode}: {detail}"
            )

        # Now send the tar data via SSH to the remote tar extraction command
        remote_tar_proc = await asyncio.create_subprocess_exec(
            *ssh_tar_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Send the tar archive data to the remote process via SSH
        ssh_stdout, ssh_stderr = await asyncio.wait_for(
            remote_tar_proc.communicate(input=tar_stdout), timeout=timeout_seconds
        )

        remote_returncode = remote_tar_proc.returncode

        # Check if remote tar command succeeded
        if remote_returncode != 0:
            detail = (
                ssh_stderr.decode(errors="replace").strip()
                or ssh_stdout.decode(errors="replace").strip()
                or "unknown remote tar extraction failure"
            )
            raise SSHError(
                f"Remote tar extraction failed with exit code {remote_returncode}: {detail}"
            )

    except asyncio.TimeoutError as exc:
        # Kill both processes on timeout
        if local_tar_proc is not None:
            try:
                local_tar_proc.kill()
                await local_tar_proc.wait()
            except:
                pass  # Process might have already terminated
        if remote_tar_proc is not None:
            try:
                remote_tar_proc.kill()
                await remote_tar_proc.wait()
            except:
                pass  # Process might have already terminated
        raise SSHError(
            f"Tar streaming upload timed out after {timeout_seconds} seconds"
        ) from exc
    except OSError as exc:
        raise SSHError(f"Failed to execute tar streaming: {exc}") from exc
    return True


def _build_ssh_connection_info(host: str, port: int, user: str) -> SSHConnectionInfo:
    """Build SSHConnectionInfo for direct TCP SSH connection.

    This is a helper to use the shared SSH argument builders from runpod_ssh.py.
    """
    return SSHConnectionInfo(
        method="direct_tcp",
        host=host,
        port=port,
        username=user,
    )


def _build_remote_wrapped_command(command: str, remote_dir: str) -> str:
    """Build a remote wrapper command that captures stdout/stderr and exit code.

    The wrapper:
    1. Removes old marker/log files
    2. Touches stdout/stderr files for early discovery by log collector
    3. Changes to remote_dir
    4. Runs user command with append redirection to log files
    5. Writes command exit code to marker file
    6. Touches done marker to signal completion
    7. Exits 0 so SSH success means "wrapper completed", not "user command succeeded"

    Shell/Environment Mode Justification:
    ----------------------------------------
    Uses `bash -il -c` to invoke an interactive login shell. This mode was chosen
    based on Task 1 same-Pod shell-mode comparison evidence which showed:

    - Plain remote command: KAGGLE vars NOT visible
    - `bash -l -c` (login non-interactive): KAGGLE vars NOT visible
    - `bash -il -c` (interactive login): Closest match to interactive shell behavior
    - Manual interactive SSH session: KAGGLE vars visible (user baseline)

    The `-i` flag ensures ~/.bashrc is read, which is critical for RunPod because:
    - RunPod container startup writes exports to `/etc/rp_environment`
    - `~/.bashrc` sources `/etc/rp_environment` on container startup
    - See: https://github.com/runpod/containers/blob/main/container-template/start.sh

    Note: Task 1 evidence showed even `bash -il -c` may not fully replicate manual
    interactive SSH behavior due to RunPod infrastructure-level TTY handling.
    However, `bash -il -c` remains the best approximation for programmatic SSH execution.

    Wrapper Components Preserved:
    - `-tt` PTY allocation: Set by caller in execute_remote_command SSH args
    - Marker files: REMOTE_STDOUT_PATH, REMOTE_STDERR_PATH, REMOTE_EXIT_CODE_PATH, REMOTE_DONE_PATH
    - Exit-code polling: Handled by _poll_remote_exit_code()
    """
    quoted_dir = shlex.quote(remote_dir)
    return (
        f"rm -f {REMOTE_STDOUT_PATH} {REMOTE_STDERR_PATH} {REMOTE_EXIT_CODE_PATH} {REMOTE_DONE_PATH} && "
        f"touch {REMOTE_STDOUT_PATH} {REMOTE_STDERR_PATH} && "
        f"cd {quoted_dir} && "
        f"bash -il -c '( {command} )' >> {REMOTE_STDOUT_PATH} 2>> {REMOTE_STDERR_PATH}; "
        f"printf '%s' \"$?\" > {REMOTE_EXIT_CODE_PATH}; "
        f"touch {REMOTE_DONE_PATH}"
    )


async def _poll_remote_exit_code(
    host: str,
    port: int,
    user: str = "root",
    *,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.5,
) -> int:
    """Poll remote exit code by checking for done marker and reading exit code file.

    Raises:
        SSHError: If SSH connection fails (returncode 255), polling times out,
                  or exit code file content is invalid.
    """
    import time

    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        # Build polling command: test for done marker and cat exit code if exists
        poll_command = f"test -f {REMOTE_DONE_PATH} && cat {REMOTE_EXIT_CODE_PATH}"
        conn_info = _build_ssh_connection_info(host, port, user)
        ssh_command = build_non_interactive_ssh_args(conn_info) + [poll_command]

        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise SSHError(f"Failed to start polling SSH process: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            # Continue polling - this is a short timeout for individual polling commands
            await asyncio.sleep(poll_interval_seconds)
            continue

        # SSH connection failure (255) - raise immediately
        if proc.returncode == 255:
            stderr_text = stderr.decode(errors="replace").strip()
            raise SSHError(
                f"SSH connection failed during exit code polling: {stderr_text}"
            )

        # If test -f failed (done marker not present), continue polling
        if proc.returncode != 0:
            await asyncio.sleep(poll_interval_seconds)
            continue

        # Done marker exists and cat succeeded - parse exit code
        stdout_text = stdout.decode(errors="replace").strip()
        if not stdout_text:
            raise SSHError("Invalid remote exit code content: empty exit code file")

        try:
            return int(stdout_text)
        except ValueError:
            raise SSHError(f"Invalid remote exit code content: {stdout_text!r}")

    # Timeout - polling loop completed without seeing done marker
    raise SSHError(
        f"Remote exit code polling timed out after {timeout_seconds} seconds"
    )


async def execute_remote_command(
    command: str,
    host: str,
    port: int,
    user: str = "root",
    remote_dir: str = "/workspace",
    timeout_seconds: float = 3600.0,
) -> int:
    """Execute a command on a remote pod via SSH and return its exit code.

    The command is wrapped to capture stdout/stderr to remote files and
    the real command exit code is retrieved via polling.

    Raises:
        SSHError: If SSH connection fails (returncode 255), command times out,
                  or exit code polling fails.
    """
    # Phase A: Launch wrapped command
    wrapped_command = _build_remote_wrapped_command(command, remote_dir)
    conn_info = _build_ssh_connection_info(host, port, user)
    ssh_command = build_interactive_ssh_args(conn_info) + [wrapped_command]

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
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SSHError(f"Remote command timed out after {timeout_seconds} seconds")

    if proc.returncode is None:
        raise SSHError("SSH process finished without return code")

    # SSH connection failure (255) - raise immediately
    if proc.returncode == 255:
        stderr_text = stderr.decode(errors="replace").strip()
        raise SSHError(f"SSH connection failed: {stderr_text}")

    # Phase B: Poll for real remote exit code
    # The wrapper SSH process exiting successfully only means the wrapper started.
    # We must poll for the done marker and read the actual command exit code.
    return await _poll_remote_exit_code(host, port, user, timeout_seconds=30.0)


async def managed_stop(
    db_path: Path | str,
    job_id: int,
    pod_id: str,
    runpod_client: RunPodClient,
    *,
    final_status: JobStatus = JobStatus.STOPPED,
    final_message: str = "Pod deleted",
    final_error_message: str | None = None,
    final_exit_code: int | None = None,
) -> Job:
    """Stop and delete a managed pod, then persist final lifecycle state.

    Notes
    -----
    - First requests pod stop.
    - Then deletes the pod via RunPod REST API.
    - The final persisted job status is configurable so callers can preserve
      SUCCEEDED / FAILED while still guaranteeing pod cleanup.
    """
    await update_job_status(
        db_path,
        job_id,
        JobStatus.STOPPING,
        message="Managed cleanup requested",
    )

    # Small delay to allow RunPod to finalize pod state transition
    await asyncio.sleep(3)

    # Use delete_pod (REST API) for guaranteed deletion.
    # The DELETE endpoint returns 204 on success - pod is deleted.
    # User requirement: managed job execution MUST result in pod deletion.
    delete_error: str | None = None
    for attempt in range(3):
        try:
            await runpod_client.delete_pod(pod_id)
            # 204 response means pod is deleted
            delete_error = None
            break
        except RunPodAPIError as exc:
            # Check for various "already deleted" indicators
            error_str = str(exc).lower()
            if (
                "pod not found" in error_str
                or "already" in error_str
                or "not found to terminate" in error_str
            ):
                # Already deleted - this is fine
                delete_error = None
                break
            delete_error = str(exc)
        except Exception as exc:
            delete_error = str(exc)

        # Wait before retry
        await asyncio.sleep(2)

    if delete_error:
        return await update_job_status(
            db_path,
            job_id,
            JobStatus.FAILED,
            message="Managed cleanup failed",
            error_message=f"Failed to delete pod: {delete_error}",
            exit_code=final_exit_code,
        )

    return await update_job_status(
        db_path,
        job_id,
        final_status,
        message=final_message,
        error_message=final_error_message,
        exit_code=final_exit_code,
    )


async def auto_cleanup_pod(
    db_path: Path | str,
    job_id: int,
    pod_id: str,
    runpod_client: RunPodClient,
    execution_status: JobStatus,
    execution_exit_code: int | None,
    execution_error_message: str | None,
) -> Job:
    """Auto-cleanup helper for managed jobs after command execution completes.

    This helper handles pod deletion with retry logic for the automatic cleanup
    path (not manual stop). It preserves the execution result (SUCCEEDED/FAILED)
    while ensuring the pod is deleted.

    Status flow:
    - SUCCEEDED -> STOPPING -> SUCCEEDED (cleanup success)
    - FAILED -> STOPPING -> FAILED (cleanup success)
    - SUCCEEDED/FAILED -> STOPPING -> FAILED (cleanup failure)

    Args:
        db_path: Database path
        job_id: Job ID
        pod_id: Pod ID to delete
        runpod_client: RunPod API client
        execution_status: The execution result status (SUCCEEDED or FAILED)
        execution_exit_code: The execution exit code to preserve
        execution_error_message: The execution error message to preserve

    Returns:
        Job with final status (SUCCEEDED/FAILED) after cleanup
    """
    await update_job_status(
        db_path,
        job_id,
        JobStatus.STOPPING,
        message="Managed cleanup requested",
    )

    # Small delay to allow RunPod to finalize pod state transition
    await asyncio.sleep(3)

    # Use delete_pod (REST API) for guaranteed deletion.
    # The DELETE endpoint returns 204 on success - pod is deleted.
    # User requirement: managed job execution MUST result in pod deletion.
    delete_error: str | None = None
    for attempt in range(3):
        try:
            await runpod_client.delete_pod(pod_id)
            # 204 response means pod is deleted
            delete_error = None
            break
        except RunPodAPIError as exc:
            # Check for various "already deleted" indicators
            error_str = str(exc).lower()
            if (
                "pod not found" in error_str
                or "already" in error_str
                or "not found to terminate" in error_str
            ):
                # Already deleted - this is fine
                delete_error = None
                break
            delete_error = str(exc)
        except Exception as exc:
            delete_error = str(exc)

        # Wait before retry
        await asyncio.sleep(2)

    if delete_error:
        # Cleanup failed - transition to FAILED, preserve original exit_code
        return await update_job_status(
            db_path,
            job_id,
            JobStatus.FAILED,
            message="Managed cleanup failed",
            error_message=f"Failed to delete pod: {delete_error}",
            exit_code=execution_exit_code,
        )

    # Cleanup succeeded - preserve the execution result (SUCCEEDED or FAILED)
    return await update_job_status(
        db_path,
        job_id,
        execution_status,
        message="Managed pod deleted",
        error_message=execution_error_message,
        exit_code=execution_exit_code,
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
    if job.id is None:
        raise ValueError("job.id is required")

    host = pod.ssh_host
    if host is None:
        if job.managed:
            current_job = await update_job_status(
                db_path,
                job.id,
                JobStatus.FAILED,
                message="Missing SSH host",
                error_message="Pod does not expose a public SSH host",
            )
            if job.pod_id:
                return await managed_stop(
                    db_path,
                    job.id,
                    job.pod_id,
                    runpod_client,
                    final_status=JobStatus.FAILED,
                    final_message="Pod deleted after SSH host resolution failure",
                    final_error_message="Pod does not expose a public SSH host",
                    final_exit_code=current_job.exit_code,
                )
            return current_job
        else:
            current_job = await update_job_metadata(
                db_path,
                job.id,
                error_message="Pod does not expose a public SSH host",
                message="Remote command aborted; awaiting pxq stop",
            )
            return current_job

    current_job = job
    stop_event: asyncio.Event | None = None
    log_task: asyncio.Task[None] | None = None
    try:
        # Check if workdir is specified
        if job.workdir is None:
            # No workdir specified - skip upload and go directly to RUNNING
            current_job = await update_job_status(
                db_path,
                job.id,
                JobStatus.RUNNING,
                message="Running without working directory upload",
                pod_id=pod.id,
            )
        else:
            # Upload working directory with .pxqignore support
            current_job = await update_job_status(
                db_path,
                job.id,
                JobStatus.UPLOADING,
                message="Uploading working directory",
                pod_id=pod.id,
            )

            # Read .pxqignore patterns if file exists
            ignore_patterns: list[str] | None = None
            workdir_path = Path(job.workdir)
            pxqignore_path = workdir_path / ".pxqignore"
            if pxqignore_path.exists():
                with open(pxqignore_path, "r") as f:
                    ignore_patterns = [
                        line.strip()
                        for line in f
                        if line.strip() and not line.startswith("#")
                    ]

            upload_success = await upload_directory(
                local_dir=workdir_path,
                host=host,
                port=pod.ssh_port,
                user=ssh_user,
                remote_dir=remote_dir,
                timeout_seconds=upload_timeout_seconds,
                ignore_patterns=ignore_patterns,
            )
            if not upload_success:
                if job.managed:
                    current_job = await update_job_status(
                        db_path,
                        job.id,
                        JobStatus.FAILED,
                        message="Directory upload failed",
                        error_message="Failed to upload working directory via SSH",
                    )
                    if job.pod_id:
                        return await managed_stop(
                            db_path,
                            job.id,
                            job.pod_id,
                            runpod_client,
                            final_status=JobStatus.FAILED,
                            final_message="Pod deleted after upload failure",
                            final_error_message="Failed to upload working directory via SSH",
                            final_exit_code=current_job.exit_code,
                        )
                    return current_job
                else:
                    current_job = await update_job_metadata(
                        db_path,
                        job.id,
                        error_message="Failed to upload working directory via SSH",
                        message="Remote command aborted; awaiting pxq stop",
                    )
                    return current_job

            current_job = await update_job_status(
                db_path,
                job.id,
                JobStatus.RUNNING,
                message="Remote command started",
            )

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

        # Give log collector time to do a final collection before stopping
        if stop_event is not None and log_task is not None:
            # Wait for one more collection cycle (3 seconds default)
            await asyncio.sleep(4.0)
            stop_event.set()
            try:
                await asyncio.wait_for(log_task, timeout=10.0)
            except asyncio.TimeoutError:
                log_task.cancel()

        # Always collect final stdout/stderr logs synchronously
        # This ensures we capture the final output even if the async collector missed it
        try:
            await _collect_final_logs(
                db_path=db_path,
                job_id=job.id,
                host=host,
                port=pod.ssh_port,
            )
        except Exception:
            pass  # Best effort only - don't fail the job if log collection fails

        if job.managed:
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
        else:
            if exit_code == 0:
                current_job = await update_job_metadata(
                    db_path,
                    job.id,
                    exit_code=exit_code,
                    message="Remote command completed; awaiting pxq stop",
                )
            else:
                current_job = await update_job_metadata(
                    db_path,
                    job.id,
                    exit_code=exit_code,
                    error_message=f"Remote command exited with code {exit_code}",
                    message="Remote command failed; awaiting pxq stop",
                )
    except SSHError as exc:
        if job.managed:
            current_job = await update_job_status(
                db_path,
                job.id,
                JobStatus.FAILED,
                message="SSH execution failed",
                error_message=str(exc),
            )
        else:
            current_job = await update_job_metadata(
                db_path,
                job.id,
                error_message=str(exc),
                message="Remote command aborted; awaiting pxq stop",
            )

        # Give log collector time to do a final collection before stopping
        if stop_event is not None and log_task is not None:
            # Wait for one more collection cycle (3 seconds default)
            await asyncio.sleep(4.0)
            stop_event.set()
            try:
                await asyncio.wait_for(log_task, timeout=10.0)
            except asyncio.TimeoutError:
                log_task.cancel()

        # Always collect final stdout/stderr logs synchronously
        # This ensures we capture the final output even if the async collector missed it
        try:
            await _collect_final_logs(
                db_path=db_path,
                job_id=job.id,
                host=host,
                port=pod.ssh_port,
            )
        except Exception:
            pass  # Best effort only - don't fail the job if log collection fails

    if job.managed and job.pod_id:
        # Auto-cleanup path: preserve execution result (SUCCEEDED/FAILED)
        # Final status will be SUCCEEDED or FAILED, not STOPPED
        return await auto_cleanup_pod(
            db_path,
            job.id,
            job.pod_id,
            runpod_client,
            execution_status=current_job.status,
            execution_exit_code=current_job.exit_code,
            execution_error_message=current_job.error_message,
        )

    return current_job
