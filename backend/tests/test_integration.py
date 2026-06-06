"""Integration tests — simulate HTTP/WebSocket flows against the real FastAPI app.

Uses httpx.AsyncClient + FastAPI TestClient for HTTP routes,
and the built-in WebSocket test client for WS handshake + message flow.

These tests do NOT start a real browser or connect to external AI services.
They verify that routes are mounted, messages are routed, and the app doesn't crash.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Import the FastAPI app (triggers lifespan registration but does NOT run it)."""
    import importlib
    mod = importlib.import_module("main")
    return mod.app


@pytest.fixture
async def client(app):
    """Async HTTP client wired to the app (no real server)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# 1. HTTP Route Tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """GET /health should return 200 with status ok."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "timestamp" in body


class TestSessionEndpoints:
    """Session CRUD routes should be mounted and respond."""

    @pytest.mark.asyncio
    async def test_sessions_status_returns_200(self, client: AsyncClient):
        resp = await client.get("/api/sessions/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "sessions" in body
        assert "authenticated" in body

    @pytest.mark.asyncio
    async def test_list_sessions_returns_200(self, client: AsyncClient):
        resp = await client.get("/api/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert "sessions" in body

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, client: AsyncClient):
        resp = await client.get("/api/sessions/nonexistent_id_12345")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_session_not_found(self, client: AsyncClient):
        resp = await client.delete("/api/sessions/nonexistent_id_12345")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_clear_sessions(self, client: AsyncClient):
        resp = await client.delete("/api/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "cleared"


# ---------------------------------------------------------------------------
# 2. WebSocket Route Mounting
# ---------------------------------------------------------------------------

class TestWebSocketMounting:
    """Verify /ws endpoint is mounted and accepts connections."""

    @pytest.mark.asyncio
    async def test_ws_endpoint_is_registered(self, app):
        """Check that the /ws route exists in the app's route table."""
        ws_routes = [
            route for route in app.routes
            if hasattr(route, "path") and route.path == "/ws"
        ]
        assert len(ws_routes) >= 1, "WebSocket route /ws not found in app.routes"

    @pytest.mark.asyncio
    async def test_ws_endpoint_has_correct_type(self, app):
        """Verify the /ws route is a WebSocket route."""
        ws_routes = [
            route for route in app.routes
            if hasattr(route, "path") and route.path == "/ws"
        ]
        route = ws_routes[0]
        # WebSocket routes have 'endpoint' attribute
        assert hasattr(route, "endpoint")


# ---------------------------------------------------------------------------
# 3. WebSocket Message Flow (using Starlette test client)
# ---------------------------------------------------------------------------

class TestWebSocketMessageFlow:
    """Simulate WebSocket connect → message → disconnect."""

    @pytest.mark.asyncio
    async def test_ws_connect_and_ping(self, app):
        """Connect to /ws, send ping, expect pong."""
        from starlette.testclient import TestClient

        # Use Starlette's synchronous test client for WS
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            # Should receive engine_status on connect
            data = ws.receive_json()
            assert data["type"] == "engine_status"
            assert "data" in data
            assert "connected" in data["data"]

            # Send ping
            ws.send_json({"type": "ping", "data": {}})

            # Should receive pong
            data = ws.receive_json()
            assert data["type"] == "pong"

    @pytest.mark.asyncio
    async def test_ws_submit_query_validation(self, app):
        """Send invalid submit_query — should get error response."""
        from starlette.testclient import TestClient

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            # Consume engine_status
            ws.receive_json()

            # Send invalid query (non-string)
            ws.send_json({
                "type": "submit_query",
                "data": {"query": 123, "ai_ids": ["deepseek"]}
            })

            data = ws.receive_json()
            assert data["type"] == "error"
            assert data["data"]["error"] == "Invalid query"

    @pytest.mark.asyncio
    async def test_ws_submit_query_invalid_ai_ids(self, app):
        """Send submit_query with non-list ai_ids — should get error."""
        from starlette.testclient import TestClient

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.receive_json()

            ws.send_json({
                "type": "submit_query",
                "data": {"query": "hello", "ai_ids": "not_a_list"}
            })

            data = ws.receive_json()
            assert data["type"] == "error"
            assert data["data"]["error"] == "Invalid ai_ids"

    @pytest.mark.asyncio
    async def test_ws_get_status(self, app):
        """Send get_status — should return status response."""
        from starlette.testclient import TestClient

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.receive_json()

            ws.send_json({"type": "get_status", "data": {}})

            data = ws.receive_json()
            assert data["type"] == "status"
            assert "connected" in data["data"]

    @pytest.mark.asyncio
    async def test_ws_check_sessions(self, app):
        """Send check_sessions — should return sessions_status."""
        from starlette.testclient import TestClient

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.receive_json()

            ws.send_json({"type": "check_sessions", "data": {}})

            data = ws.receive_json()
            assert data["type"] == "sessions_status"
            assert "sessions" in data["data"]


# ---------------------------------------------------------------------------
# 4. AppState Singleton
# ---------------------------------------------------------------------------

class TestAppStateSingleton:
    """Verify AppState lifecycle."""

    def test_instance_before_create_raises(self):
        """AppState.instance() should raise if not initialized."""
        from shared.app_state import AppState
        AppState.reset()
        with pytest.raises(RuntimeError, match="AppState not initialized"):
            AppState.instance()

    def test_create_and_instance(self):
        """After create(), instance() should return the same object."""
        from shared.app_state import AppState
        AppState.reset()
        state = AppState.create()
        assert AppState.instance() is state

    def test_reset_clears_singleton(self):
        """After reset(), instance() should raise again."""
        from shared.app_state import AppState
        AppState.create()
        AppState.reset()
        with pytest.raises(RuntimeError):
            AppState.instance()
