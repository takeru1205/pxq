from pathlib import Path

import pytest

from pxq.config import Settings


def test_default_settings(monkeypatch):
    # Ensure no env vars affect defaults
    for var in [
        "PXQ_RUNPOD_API_KEY",
        "PXQ_MAX_PARALLELISM",
        "PXQ_LOG_MAX_SIZE_MB",
        "PXQ_PROVISIONING_TIMEOUT_MINUTES",
        "PXQ_SERVER_HOST",
        "PXQ_SERVER_PORT",
        "PXQ_DB_PATH",
    ]:
        monkeypatch.delenv(var, raising=False)

    settings = Settings()
    assert settings.runpod_api_key is None
    assert settings.max_parallelism == 4
    assert settings.log_max_size_mb == 100
    assert settings.provisioning_timeout_minutes == 15
    assert settings.server_host == "127.0.0.1"
    assert settings.server_port == 8765
    expected_path = Path.home() / ".pxq" / "pxq.db"
    assert settings.db_path == expected_path


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "testkey")
    monkeypatch.setenv("PXQ_MAX_PARALLELISM", "8")
    monkeypatch.setenv("PXQ_LOG_MAX_SIZE_MB", "200")
    monkeypatch.setenv("PXQ_PROVISIONING_TIMEOUT_MINUTES", "30")
    monkeypatch.setenv("PXQ_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("PXQ_SERVER_PORT", "9000")
    monkeypatch.setenv("PXQ_DB_PATH", "/tmp/pxq.db")

    settings = Settings()
    assert settings.runpod_api_key == "testkey"
    assert settings.max_parallelism == 8
    assert settings.log_max_size_mb == 200
    assert settings.provisioning_timeout_minutes == 30
    assert settings.server_host == "0.0.0.0"
    assert settings.server_port == 9000
    assert settings.db_path == Path("/tmp/pxq.db")


def test_validate_for_runpod_requires_key(monkeypatch):
    # No API key – should raise ValueError
    for var in ["PXQ_RUNPOD_API_KEY"]:
        monkeypatch.delenv(var, raising=False)
    settings = Settings()
    with pytest.raises(ValueError):
        settings.validate_for_runpod()

    # With API key – should not raise
    monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "validkey")
    settings = Settings()
    # Should not raise any exception
    settings.validate_for_runpod()
