# pyright: reportMissingImports=false

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pxq.api import internal_router
from pxq.config import Settings
from pxq.dashboard import router as dashboard_router
from pxq.recovery import reconcile_jobs
from pxq.storage import init_db
import asyncio
from pxq.scheduler import Scheduler
from pxq.executor import run_executor_loop


async def run_scheduler_loop(db_path, settings):
    """Background task that runs scheduler.tick() every second."""
    scheduler = Scheduler(db_path, settings)
    while True:
        await scheduler.tick()
        await asyncio.sleep(1.0)


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await init_db(settings.db_path)
        await reconcile_jobs(settings.db_path)

        # Start background tasks
        scheduler_task = asyncio.create_task(
            run_scheduler_loop(settings.db_path, settings)
        )
        executor_task = asyncio.create_task(
            run_executor_loop(settings.db_path, settings)
        )

        yield

        # Cleanup
        scheduler_task.cancel()
        executor_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        try:
            await executor_task
        except asyncio.CancelledError:
            pass

    app = FastAPI(
        title="pxq",
        description="A pueue-like CLI for local and RunPod job management",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(dashboard_router)
    app.include_router(internal_router)

    return app


app = create_app()
