"""pxq CLI - Command-line interface for job management."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
import typer
from typer import Context

from .client import PxqClient
from .config_loader import (
    ConfigFileError,
    load_config_file,
    merge_config_with_cli,
    resolve_workdir,
)
from .models import JobStatus
from .server_pid import (
    cleanup_stale_pid,
    clear_pid,
    get_pid_path,
    get_pxq_server_pid,
    get_server_pid,
    is_pxq_server_running,
    is_server_running,
    read_pid,
    write_pid,
)


import importlib.metadata


def _extract_http_error_message(exc: httpx.HTTPStatusError) -> str:
    """Extract a user-friendly error message from HTTPStatusError.

    API detail を優先し、取得できない場合は status code + text にフォールバックする。

    Parameters
    ----------
    exc : httpx.HTTPStatusError
        The HTTP error exception.

    Returns
    -------
    str
        User-friendly error message.
    """
    response = exc.response
    try:
        data = response.json()
        if isinstance(data, dict) and "detail" in data:
            return str(data["detail"])
    except Exception:
        pass
    # JSON パース失敗時はフォールバック
    return f"HTTP {response.status_code}: {response.text}"


app = typer.Typer(
    name="pxq",
    help="A pueue-like CLI for local and RunPod job management.",
    context_settings={
        "auto_envvar_prefix": "PXQ",
    },
)


@app.callback(invoke_without_command=True)
def version_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
    ),
) -> None:
    if version:
        try:
            ver = importlib.metadata.version("pxq")
        except importlib.metadata.PackageNotFoundError:
            ver = "dev"
        typer.echo(f"pxq version {ver}")
        raise typer.Exit()


@app.command()
def add(
    command: str = typer.Argument(..., help="Command to execute"),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p", help="Execution provider (local, runpod)"
    ),
    gpu: str = typer.Option(
        None, "--gpu", help="GPU type for RunPod (e.g., RTX4090:1)"
    ),
    region: str = typer.Option(
        None, "--region", "-r", help="RunPod data center (e.g., EU-RO-1)"
    ),
    cpu: bool = typer.Option(False, "--cpu", help="Use CPU-only instance"),
    volume: str = typer.Option(None, "--volume", "-v", help="Network volume ID"),
    volume_path: str = typer.Option(
        "/volume",
        "--volume-path",
        help="Mount path for the network volume (default: /volume)",
    ),
    secure_cloud: Optional[bool] = typer.Option(
        None, "--secure-cloud", help="Use Secure Cloud instead of Community Cloud"
    ),
    cpu_flavor: str = typer.Option(
        None,
        "--cpu-flavor",
        help="Comma-separated CPU flavors (e.g., cpu3c,cpu3g). Available: cpu3c, cpu3g, cpu3m, cpu5c, cpu5g, cpu5m",
    ),
    template: str = typer.Option(None, "--template", "-t", help="RunPod Template ID"),
    image: str = typer.Option(
        None, "--image", "-i", help="RunPod container image (e.g., ubuntu:22.04)"
    ),
    managed: Optional[bool] = typer.Option(
        None, "--managed", help="Managed mode - auto-stop pod after completion"
    ),
    dir: str = typer.Option(None, "--dir", "-d", help="Working directory"),
    config: str = typer.Option(None, "--config", "-c", help="Config file path"),
) -> None:
    """Add a new job to the queue.

    Sends a request to the pxq server to create a job with the given parameters.
    """
    # --gpu and --cpu are mutually exclusive
    if gpu and cpu:
        typer.echo("Error: --gpu and --cpu are mutually exclusive options.", err=True)
        raise typer.Exit(code=1)

    # --image and --template are mutually exclusive
    if image and template:
        typer.echo(
            "Error: --image and --template are mutually exclusive options.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Load config file if provided
    config_values: dict = {}
    if config:
        try:
            config_values = load_config_file(config)
        except ConfigFileError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=1)

    # Resolve working directory to absolute path
    resolved_dir = str(resolve_workdir(dir))

    # Merge CLI args with config file values
    # CLI args take precedence over config file
    merged = merge_config_with_cli(
        {
            "provider": provider,
            "gpu_type": gpu,
            "region": region,
            "cpu_count": 1 if cpu else None,
            "volume": volume,
            "volume_path": volume_path if volume else None,
            "secure_cloud": secure_cloud,
            "cpu_flavor_ids": cpu_flavor.split(",") if cpu_flavor else None,
            "template_id": template,
            "image_name": image,
            "env": None,
            "managed": managed,
            "workdir": resolved_dir,
        },
        config_values,
    )

    async def _run():
        client = PxqClient()
        return await client.create_job(
            command,
            provider=merged.get("provider") or "local",
            managed=merged.get("managed", False),
            workdir=merged.get("workdir"),
            gpu_type=merged.get("gpu_type"),
            region=merged.get("region"),
            cpu_count=merged.get("cpu_count"),
            volume_id=merged.get("volume"),
            volume_mount_path=merged.get("volume_path"),
            secure_cloud=merged.get("secure_cloud", False),
            cpu_flavor_ids=merged.get("cpu_flavor_ids"),
            template_id=merged.get("template_id"),
            image_name=merged.get("image_name"),
            env=merged.get("env"),
        )

    try:
        resp = asyncio.run(_run())
        typer.echo(json.dumps(resp.model_dump(mode="json"), indent=2))
    except (ConnectionError, RuntimeError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)


@app.command()
def ls(
    all: bool = typer.Option(False, "--all", "-a", help="Include terminal state jobs"),
) -> None:
    """List all jobs in the queue."""

    async def _run():
        client = PxqClient()
        jobs = await client.list_jobs(include_all=all)
        return {
            "jobs": [job.model_dump(mode="json") for job in jobs],
            "count": len(jobs),
        }

    try:
        resp = asyncio.run(_run())
        typer.echo(json.dumps(resp, indent=2))
    except (ConnectionError, RuntimeError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)


@app.command("status")
def status_cmd(
    job_id: int = typer.Argument(None, help="Job ID to check status"),
    all: bool = typer.Option(
        False, "--all", "-a", help="Show all jobs including completed"
    ),
) -> None:
    """Check status of jobs."""

    async def _run():
        client = PxqClient()
        if job_id is not None:
            job = await client.get_job(job_id)
            if job is None:
                return None
            return job.model_dump(mode="json")
        else:
            jobs = await client.list_jobs(include_all=all)
            return {
                "jobs": [job.model_dump(mode="json") for job in jobs],
                "count": len(jobs),
            }

    try:
        resp = asyncio.run(_run())
        if resp is None:
            typer.echo(f"Job {job_id} not found", err=True)
            raise typer.Exit(code=1)
        typer.echo(json.dumps(resp, indent=2))
    except (ConnectionError, RuntimeError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)


@app.command()
def ssh(
    job_id: int = typer.Argument(..., help="Job ID to connect to"),
) -> None:
    """SSH into a running job's pod."""
    from .providers.runpod_ssh import SSHConnectionInfo, build_interactive_ssh_args

    async def _run() -> SSHConnectionInfo:
        client = PxqClient()
        job = await client.get_job(job_id)
        if job is None:
            typer.echo(f"Job {job_id} not found", err=True)
            raise typer.Exit(code=1)
        # Support dict or model job object
        if isinstance(job, dict):
            job_status = JobStatus(job["status"])
            job_pod_id = job.get("pod_id")
        else:
            job_status = job.status
            job_pod_id = job.pod_id
        if job_status != JobStatus.RUNNING:
            typer.echo(f"Job {job_id} is not running", err=True)
            raise typer.Exit(code=1)
        if not job_pod_id:
            typer.echo(f"Job {job_id} has no pod", err=True)
            raise typer.Exit(code=1)
        # Retrieve pod details for SSH
        from .config import Settings
        from .providers.runpod_client import RunPodClient

        settings = Settings()
        if settings.runpod_api_key is None:
            raise RuntimeError("RunPod API key not configured")
        rp_client = RunPodClient(settings.runpod_api_key)
        pod = await rp_client.get_pod(job_pod_id)
        host = pod.ssh_host
        port = pod.ssh_port
        if not host:
            typer.echo(f"Pod {job_pod_id} does not expose SSH host", err=True)
            raise typer.Exit(code=1)
        return SSHConnectionInfo(
            method="direct_tcp",
            host=host,
            port=port,
            username="root",
        )

    try:
        conn_info = asyncio.run(_run())
        ssh_args = build_interactive_ssh_args(conn_info)
        # os.execvp replaces current process with ssh - never returns on success
        os.execvp("ssh", ssh_args)
    except FileNotFoundError:
        typer.echo(
            "Error: 'ssh' command not found. Please install OpenSSH client.",
            err=True,
        )
        raise typer.Exit(code=1)
    except (ConnectionError, RuntimeError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)


@app.command()
def cancel(
    job_id: int = typer.Argument(..., help="Job ID to cancel"),
) -> None:
    """Cancel a queued job.

    Only jobs in QUEUED status can be cancelled.
    """

    async def _run():
        client = PxqClient()
        return await client.cancel_job(job_id)

    try:
        resp = asyncio.run(_run())
        typer.echo(json.dumps(resp.model_dump(mode="json"), indent=2))
    except httpx.HTTPStatusError as e:
        typer.echo(_extract_http_error_message(e), err=True)
        raise typer.Exit(code=1)
    except (ConnectionError, RuntimeError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)


@app.command()
def stop(
    job_id: int = typer.Argument(None, help="Job ID to stop"),
) -> None:
    """Stop a running job.

    If JOB_ID is provided, stops that specific job directly.

    If no JOB_ID is provided, stops a job only when exactly one job is
    in RUNNING status. For non-managed RunPod jobs awaiting explicit stop,
    specifying JOB_ID is recommended.

    The job always transitions to STOPPED status. For RunPod jobs,
    any existing exit_code and error_message are preserved.
    """

    async def _run():
        client = PxqClient()
        return await client.stop_job(job_id)

    try:
        resp = asyncio.run(_run())
        typer.echo(json.dumps(resp.model_dump(mode="json"), indent=2))
    except httpx.HTTPStatusError as e:
        typer.echo(_extract_http_error_message(e), err=True)
        raise typer.Exit(code=1)
    except (ConnectionError, RuntimeError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)


# Server management subcommands
server_app = typer.Typer(help="Server management commands")


@server_app.callback(invoke_without_command=True)
def server_callback(
    ctx: typer.Context,
    port: int = typer.Option(None, "--port", "-p", help="Port to run the server on"),
    host: str = typer.Option(None, "--host", "-h", help="Host to bind the server to"),
) -> None:
    """Server management commands."""
    import warnings

    if ctx.invoked_subcommand is None:
        warnings.warn(
            "The 'pxq server' command is deprecated. Use 'pxq server start' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        typer.echo(
            "Warning: 'pxq server' is deprecated. Use 'pxq server start' instead.",
            err=True,
        )
        import uvicorn

        from pxq.config import Settings
        from pxq.server import create_app

        settings = Settings()
        server_host = host or settings.server_host
        server_port = port or settings.server_port

        fastapi_app = create_app()
        uvicorn.run(fastapi_app, host=server_host, port=server_port)


@server_app.command("start")
def server_start(
    port: int = typer.Option(None, "--port", "-p", help="Port to run the server on"),
    host: str = typer.Option(None, "--host", "-h", help="Host to bind the server to"),
) -> None:
    """Start the pxq server in background."""
    from .config import Settings

    # Use canonical server identity check - only start if no pxq server is running
    if is_pxq_server_running():
        pid = get_pxq_server_pid()
        typer.echo(f"Server is already running with PID {pid}", err=True)
        raise typer.Exit(code=1)

    settings = Settings()
    server_host = host or settings.server_host
    server_port = port or settings.server_port

    # Prepare log file path
    log_path = Path.home() / ".pxq" / "server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Build the command to run uvicorn
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "pxq.server:app",
        "--host",
        server_host,
        "--port",
        str(server_port),
    ]

    # Start the server in background
    with open(log_path, "a") as log_file:
        process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )

    # Save the PID
    write_pid(process.pid)

    typer.echo(f"Server started (PID: {process.pid})")
    typer.echo(f"URL: http://{server_host}:{server_port}")
    typer.echo(f"Logs: {log_path}")


@server_app.command("stop")
def server_stop() -> None:
    """Stop the pxq server."""
    # Get the actual pxq server PID (canonical identity check)
    pid = get_pxq_server_pid()
    if pid is None:
        typer.echo("Server is not running", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Stopping server with PID {pid}...")

    # Send SIGTERM
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        # Process already dead - clean up PID file
        clear_pid()
        typer.echo("Server process not found")
        raise typer.Exit(code=1)

    # Wait for process to terminate (up to 5 seconds)
    for _ in range(50):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            # Process has terminated
            clear_pid()
            typer.echo("Server stopped")
            return

    # Force kill with SIGKILL
    typer.echo("Server did not stop gracefully, sending SIGKILL...")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    clear_pid()
    typer.echo("Server stopped (killed)")


@server_app.command("restart")
def server_restart(
    port: int = typer.Option(None, "--port", "-p", help="Port to run the server on"),
    host: str = typer.Option(None, "--host", "-h", help="Host to bind the server to"),
) -> None:
    """Restart the pxq server."""
    if is_pxq_server_running():
        server_stop()
    else:
        cleanup_stale_pid()

    server_start(port=port, host=host)


@server_app.command("status")
def server_status() -> None:
    """Show the server status."""
    # Get actual pxq server PID (canonical identity)
    actual_pid = get_pxq_server_pid()
    # Also read PID file for comparison
    file_pid = read_pid()

    if actual_pid is None:
        # Check if PID file exists but server is not running (stale PID)
        if file_pid is not None:
            typer.echo(f"Server is not running (stale PID file: {file_pid})")
        else:
            typer.echo("Server is not running")
        raise typer.Exit(code=0)

    # Server is running - show both PID file and live listener status
    typer.echo(f"Server is running with PID {actual_pid}")
    if file_pid is not None and file_pid != actual_pid:
        typer.echo(f"Warning: PID file contains {file_pid} (expected {actual_pid})")

    from .config import Settings

    settings = Settings()
    typer.echo(f"URL: http://{settings.server_host}:{settings.server_port}")
    typer.echo(f"Logs: {Path.home() / '.pxq' / 'server.log'}")


app.add_typer(server_app, name="server")


if __name__ == "__main__":
    # typer.run does not support async directly; use asyncio.run
    asyncio.run(app())
