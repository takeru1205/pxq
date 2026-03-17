from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    runpod_api_key: Optional[str] = None
    max_parallelism: int = 4
    log_max_size_mb: int = 100
    provisioning_timeout_minutes: int = 15
    server_host: str = "127.0.0.1"
    server_port: int = 8765
    cors_origins: list[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
    db_path: Path = Path.home() / ".pxq" / "pxq.db"
    runpod_ssh_public_key_path: Optional[Path] = None
    runpod_ssh_private_key_path: Optional[Path] = None

    model_config = SettingsConfigDict(
        env_prefix="PXQ_",
        extra="allow",
    )

    def model_post_init(self, __context) -> None:
        if self.runpod_ssh_public_key_path is None:
            ssh_pubkey_env = os.environ.get("RUNPOD_SSH_PUBLIC_KEY_PATH")
            if ssh_pubkey_env:
                self.runpod_ssh_public_key_path = Path(ssh_pubkey_env).expanduser()
        if self.runpod_ssh_private_key_path is None:
            ssh_privkey_env = os.environ.get("RUNPOD_SSH_PRIVATE_KEY")
            if ssh_privkey_env:
                self.runpod_ssh_private_key_path = Path(ssh_privkey_env).expanduser()

    def validate_for_runpod(self) -> None:
        """Validate configuration for RunPod usage.

        Raises
        ------
        ValueError
            If :attr:`runpod_api_key` is ``None``.
        """
        if self.runpod_api_key is None:
            raise ValueError("RUNPOD_API_KEY is required for RunPod provider")
