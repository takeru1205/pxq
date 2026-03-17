"""Tests for FastAPI server."""

import pytest
from fastapi.testclient import TestClient

from pxq.server import create_app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        """Test that /health returns status ok."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestAppCreation:
    """Tests for app creation and configuration."""

    def test_create_app_returns_fastapi_instance(self) -> None:
        """Test that create_app returns a FastAPI instance."""
        from fastapi import FastAPI

        app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_has_cors_middleware(self) -> None:
        """Test that CORS middleware is configured."""
        app = create_app()
        # Check that CORS middleware is present
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    def test_app_includes_internal_router(self) -> None:
        """Test that internal router is included."""
        app = create_app()
        routes = [route.path for route in app.routes]
        assert "/api/health" in routes
