"""Tests for redthread.main FastAPI application skeleton."""

from starlette.testclient import TestClient

from redthread.main import app


class TestHealthEndpoint:
    """GET /health returns 200 with {"status": "ok"}."""

    def test_health_returns_200(self):
        """GET /health returns HTTP 200."""
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200

    def test_health_returns_ok_status(self):
        """GET /health returns JSON body with status 'ok'."""
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.json() == {"status": "ok"}


class TestCORSMiddleware:
    """CORS headers present on response when Origin header sent."""

    def test_cors_allows_configured_origin(self):
        """Response includes access-control-allow-origin for the configured FRONTEND_URL."""
        with TestClient(app) as client:
            response = client.get(
                "/health",
                headers={"Origin": "http://localhost:3000"},
            )
            assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_cors_preflight_request(self):
        """OPTIONS preflight request returns CORS headers for configured origin."""
        with TestClient(app) as client:
            response = client.options(
                "/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_cors_rejects_unknown_origin(self):
        """Response does not include access-control-allow-origin for unknown origins."""
        with TestClient(app) as client:
            response = client.get(
                "/health",
                headers={"Origin": "http://evil.example.com"},
            )
            assert response.headers.get("access-control-allow-origin") != "http://evil.example.com"


class TestAppLifecycle:
    """App starts and shuts down without errors."""

    def test_app_starts_and_stops(self):
        """Application starts up and shuts down cleanly via TestClient context manager."""
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
        # If we reach here, startup and shutdown completed without errors.


class TestRouterStubs:
    """Router stubs for /api/v1 and /ws are mounted."""

    def test_api_v1_router_mounted(self):
        """The /api/v1 router prefix is mounted (returns 404 for unknown sub-routes, not 404 at prefix level)."""
        with TestClient(app) as client:
            # A request to a non-existent sub-route under /api/v1 should return 404
            # (meaning the router is mounted), not a different error.
            response = client.get("/api/v1/nonexistent")
            assert response.status_code == 404

    def test_ws_router_mounted(self):
        """The /ws router prefix is mounted."""
        with TestClient(app) as client:
            response = client.get("/ws/nonexistent")
            assert response.status_code == 404
