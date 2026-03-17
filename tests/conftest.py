from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import pytest_asyncio


@dataclass
class TestSettings:
    runpod_api_key: str
    max_parallelism: int
    log_max_size_mb: int
    provisioning_timeout_minutes: int
    server_host: str
    server_port: int
    db_path: Path


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path):
        pass
    return db_path


@pytest.fixture
def mock_settings(monkeypatch: pytest.MonkeyPatch, tmp_db: Path) -> TestSettings:
    monkeypatch.setenv("PXQ_RUNPOD_API_KEY", "test-api-key")
    monkeypatch.setenv("PXQ_MAX_PARALLELISM", "2")
    monkeypatch.setenv("PXQ_LOG_MAX_SIZE_MB", "10")
    monkeypatch.setenv("PXQ_PROVISIONING_TIMEOUT_MINUTES", "5")
    monkeypatch.setenv("PXQ_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("PXQ_SERVER_PORT", "9001")
    monkeypatch.setenv("PXQ_DB_PATH", str(tmp_db))
    return TestSettings(
        runpod_api_key="test-api-key",
        max_parallelism=2,
        log_max_size_mb=10,
        provisioning_timeout_minutes=5,
        server_host="127.0.0.1",
        server_port=9001,
        db_path=tmp_db,
    )


class MockHTTPXClient:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._responses: dict[tuple[str, str], deque[httpx.Response]] = defaultdict(
            deque
        )
        self._client = httpx.AsyncClient(transport=httpx.MockTransport(self._handler))

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    def add_response(
        self,
        method: str,
        url: str,
        *,
        status_code: int = 200,
        json: dict | list | None = None,
        text: str | None = None,
    ) -> None:
        if json is not None:
            response = httpx.Response(status_code=status_code, json=json)
        elif text is not None:
            response = httpx.Response(status_code=status_code, text=text)
        else:
            response = httpx.Response(status_code=status_code)
        self._responses[(method.upper(), url)].append(response)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method.upper(), str(request.url))
        if not self._responses[key]:
            return httpx.Response(
                status_code=500, json={"detail": f"No mocked response for {key}"}
            )
        return self._responses[key].popleft()

    async def aclose(self) -> None:
        await self._client.aclose()


@pytest_asyncio.fixture
async def mock_httpx_client() -> AsyncIterator[MockHTTPXClient]:
    mock_client = MockHTTPXClient()
    yield mock_client
    await mock_client.aclose()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests that use real external services",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: marks tests that call real external integrations",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-integration"):
        return

    skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
