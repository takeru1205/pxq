"""Client layer for interacting with the pxq server API.

Provides a high-level asynchronous interface for creating, listing, and retrieving jobs.
"""

from __future__ import annotations

import httpx
from typing import Any, List, Optional

from .config import Settings
from .models import Job


class PxqClient:
    """Asynchronous client for the pxq server API.

    Attributes
    ----------
    settings: Settings
        Configuration containing server host and port.
    base_url: str
        Base URL constructed from settings, e.g., ``http://127.0.0.1:8765/api``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the client with optional custom settings.

        Parameters
        ----------
        settings: Settings | None, optional
            If omitted, the global :class:`Settings` singleton is used.
        """
        self.settings: Settings = settings or Settings()
        # サーバーのホストとポートからベースURLを組み立てる
        self.base_url: str = (
            f"http://{self.settings.server_host}:{self.settings.server_port}/api"
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Internal helper to perform an HTTP request with error handling.

        Parameters
        ----------
        method: str
            HTTP method name ("GET", "POST", etc.).
        path: str
            API path relative to the base URL, e.g., ``"/jobs"``.
        **kwargs:
            Additional arguments passed to :func:`httpx.AsyncClient.request`.

        Returns
        -------
        httpx.Response
            The response object if the request succeeds.

        Raises
        ------
        RuntimeError
            If a connection error occurs.
        """
        try:
            async with httpx.AsyncClient(base_url=self.base_url) as client:
                response = await client.request(method, path, **kwargs)
                response.raise_for_status()
                return response
        except httpx.ConnectError as exc:
            # 接続エラーはユーザーに分かりやすいメッセージで伝える
            raise RuntimeError(
                f"Failed to connect to pxq server at {self.base_url}: {exc}"
            ) from exc

    async def create_job(self, command: str, **kwargs: Any) -> Job:
        """Create a new job on the server.

        Parameters
        ----------
        command: str
            Command to be executed by the job.
        **kwargs:
            Additional fields accepted by the server's ``JobCreateRequest`` model,
            such as ``provider``, ``managed``, ``workdir``, etc.

        Returns
        -------
        Job
            The created job model.
        """
        payload: dict[str, Any] = {"command": command, **kwargs}
        response = await self._request("POST", "/jobs", json=payload)
        data = response.json()
        return Job.model_validate(data)

    async def list_jobs(self, include_all: bool = False) -> List[Job]:
        """Retrieve a list of jobs from the server.

        Parameters
        ----------
        include_all: bool, default ``False``
            If ``True``, include jobs in terminal states.

        Returns
        -------
        list[Job]
            List of job models.
        """
        response = await self._request("GET", "/jobs", params={"all": include_all})
        data = response.json()
        jobs_data: list[dict[str, Any]] = data.get("jobs", [])
        return [Job.model_validate(job) for job in jobs_data]

    async def get_job(self, job_id: int) -> Optional[Job]:
        """Fetch a single job by its identifier.

        Parameters
        ----------
        job_id: int
            Identifier of the job to retrieve.

        Returns
        -------
        Job | None
            The job model if found, otherwise ``None``.
        """
        try:
            response = await self._request("GET", f"/jobs/{job_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        data = response.json()
        return Job.model_validate(data)

    async def close(self) -> None:
        """Close any resources. Currently no persistent client."""
        # No persistent httpx.AsyncClient stored; nothing to close
        pass

    async def cancel_job(self, job_id: int) -> Job:
        """Cancel a queued job.

        Parameters
        ----------
        job_id: int
            Identifier of the job to cancel.

        Returns
        -------
        Job
            The cancelled job model.

        Raises
        ------
        httpx.HTTPStatusError
            If the job is not found (404) or not in queued state (400).
        """
        response = await self._request("POST", f"/jobs/{job_id}/cancel")
        data = response.json()
        return Job.model_validate(data)

    async def stop_job(self, job_id: int | None = None) -> Job:
        """Stop a running job.

        If job_id is provided, stops the specified job directly.
        If job_id is None, stops a job only when exactly one job is in RUNNING status.

        The job always transitions to STOPPED status. For RunPod jobs,
        any existing exit_code and error_message are preserved through
        the stop transition.

        Parameters
        ----------
        job_id: int | None, default ``None``
            Identifier of the job to stop. If None, the server determines
            which job to stop (only when exactly one RUNNING job exists).

        Returns
        -------
        Job
            The stopped job model with status STOPPED.

        Raises
        ------
        httpx.HTTPStatusError
            If job_id is specified: job not found (404) or job not running (400).
            If job_id is None: no running jobs found (400) or multiple running jobs found (400).
        """
        if job_id is not None:
            response = await self._request("POST", f"/jobs/{job_id}/stop")
        else:
            response = await self._request("POST", "/jobs/stop")
        data = response.json()
        return Job.model_validate(data)

    async def stop_running_job(self) -> Job:
        """Stop the single running job.

        Stops a job only when exactly one job is in RUNNING status.
        The job always transitions to STOPPED status. For RunPod jobs,
        any existing exit_code and error_message are preserved through
        the stop transition.

        Requires no job_id parameter - the server determines which job to stop.

        Returns
        -------
        Job
            The stopped job model with status STOPPED.

        Raises
        ------
        httpx.HTTPStatusError
            If no running jobs found (400) or multiple running jobs found (400).
        """
        return await self.stop_job(job_id=None)
