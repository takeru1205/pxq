"""Dashboard routes (FastAPI + Jinja2 + HTMX).

This module provides server-rendered HTML pages for inspecting jobs.
"""

# pyright: reportMissingImports=false

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pxq.config import Settings
from pxq.storage import get_artifacts, get_job, get_job_events, list_jobs

router = APIRouter(tags=["dashboard"])


def _templates() -> Jinja2Templates:
    templates_dir = Path(__file__).resolve().parent / "templates"
    if not templates_dir.exists():
        raise RuntimeError(f"Dashboard templates directory not found: {templates_dir}")
    return Jinja2Templates(directory=str(templates_dir))


def _get_db_path() -> str:
    return str(Settings().db_path)


def _fmt_dt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat(timespec="seconds")
    return str(value)


def _duration_seconds(
    started_at: datetime | None, finished_at: datetime | None
) -> int | None:
    if started_at is None:
        return None
    end = finished_at or datetime.now(UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    seconds = int((end - started_at).total_seconds())
    return max(0, seconds)


@router.get("/", response_class=HTMLResponse)
async def dashboard_index(
    request: Request, all: bool = Query(default=False)
) -> HTMLResponse:
    templates = _templates()
    jobs = await list_jobs(_get_db_path(), include_all=all)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "jobs": jobs,
            "include_all": all,
            "fmt_dt": _fmt_dt,
            "duration_seconds": _duration_seconds,
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def dashboard_job_detail(request: Request, job_id: int) -> HTMLResponse:
    templates = _templates()
    job = await get_job(_get_db_path(), job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # events/artifacts の欠損に対して safe defaults を提供
    events = await get_job_events(_get_db_path(), job_id) or []
    artifacts = await get_artifacts(_get_db_path(), job_id) or []

    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "job": job,
            "events": events,
            "artifacts": artifacts,
            "fmt_dt": _fmt_dt,
            "duration_seconds": _duration_seconds,
        },
    )


@router.get("/partials/jobs", response_class=HTMLResponse)
async def dashboard_partial_jobs(
    request: Request, all: bool = Query(default=False)
) -> HTMLResponse:
    templates = _templates()
    jobs = await list_jobs(_get_db_path(), include_all=all)
    return templates.TemplateResponse(
        request,
        "partials/job_list.html",
        {
            "jobs": jobs,
            "include_all": all,
            "fmt_dt": _fmt_dt,
            "duration_seconds": _duration_seconds,
        },
    )


@router.get("/partials/jobs/{job_id}/logs", response_class=HTMLResponse)
async def dashboard_partial_job_logs(request: Request, job_id: int) -> HTMLResponse:
    templates = _templates()
    job = await get_job(_get_db_path(), job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # events/artifacts の欠損に対して safe defaults を提供
    events = await get_job_events(_get_db_path(), job_id) or []
    artifacts = await get_artifacts(_get_db_path(), job_id) or []

    return templates.TemplateResponse(
        request,
        "partials/job_logs.html",
        {
            "job": job,
            "events": events,
            "artifacts": artifacts,
            "fmt_dt": _fmt_dt,
        },
    )
