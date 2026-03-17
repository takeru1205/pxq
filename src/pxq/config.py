from __future__ import annotations

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    Environment variables are prefixed with ``PXQ_``. For example,
    ``PXQ_RUNPOD_API_KEY`` sets :attr:`runpod_api_key`.
    """

    # RunPod API key – optional, required only when using RunPod provider
    runpod_api_key: Optional[str] = None

    # Concurrency settings
    max_parallelism: int = 4
    log_max_size_mb: int = 100
    provisioning_timeout_minutes: int = 15

    # Server settings
    server_host: str = "127.0.0.1"
    server_port: int = 8765

    # CORS settings - comma-separated list of allowed origins
    cors_origins: list[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # Database path – defaults to ``~/.pxq/pxq.db``
    db_path: Path = Path.home() / ".pxq" / "pxq.db"

    # SSH key path – optional, for RunPod SSH connections
    runpod_ssh_key_path: Optional[Path] = None

    model_config = SettingsConfigDict(env_prefix="PXQ_")

    def validate_for_runpod(self) -> None:
        """Validate configuration for RunPod usage.

        Raises
        ------
        ValueError
            If :attr:`runpod_api_key` is ``None``.
        """
        if self.runpod_api_key is None:
            raise ValueError("RUNPOD_API_KEY is required for RunPod provider")
