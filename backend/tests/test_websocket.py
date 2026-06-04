"""Tests for WebSocket communication."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.receive_json = AsyncMock()
    return ws


class TestConnectionManager:
    """Test WebSocket connection manager."""

    @pytest.mark.asyncio
    async def test_connect(self):
        from main import ConnectionManager
        manager = ConnectionManager()
        ws = AsyncMock()

        await manager.connect(ws)
        assert len(manager.active_connections) == 1
        assert ws in manager.active_connections

    @pytest.mark.asyncio
    async def test_disconnect(self):
        from main import ConnectionManager
        manager = ConnectionManager()
        ws = AsyncMock()

        await manager.connect(ws)
        manager.disconnect(ws)
        assert len(manager.active_connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast(self):
        from main import ConnectionManager
        manager = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        await manager.connect(ws1)
        await manager.connect(ws2)

        message = {"type": "test", "data": {}}
        await manager.broadcast(message)

        ws1.send_json.assert_called_once_with(message)
        ws2.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_send_personal(self):
        from main import ConnectionManager
        manager = ConnectionManager()
        ws = AsyncMock()

        message = {"type": "test", "data": {}}
        await manager.send_personal(ws, message)

        ws.send_json.assert_called_once_with(message)


class TestGlobalExceptionHandler:
    """Test global exception handler."""

    def test_format_known_error(self):
        from main import GlobalExceptionHandler, ConnectionManager
        handler = GlobalExceptionHandler(ConnectionManager())

        result = handler._format(ConnectionError, ConnectionError("test"))
        assert result["code"] == "NETWORK_ERROR"
        assert result["recoverable"] is True

    def test_format_unknown_error(self):
        from main import GlobalExceptionHandler, ConnectionManager
        handler = GlobalExceptionHandler(ConnectionManager())

        result = handler._format(ValueError, ValueError("unknown"))
        assert result["code"] == "UNKNOWN"
        assert result["recoverable"] is False
