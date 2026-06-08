"""Unit tests for ws/connection.py message handlers."""

from __future__ import annotations


from ws.connection import ConnectionManager, GlobalExceptionHandler


class TestConnectionManagerExtended:
    def test_send_personal(self):
        import asyncio

        class FakeWS:
            async def send_json(self, data):
                self.sent = data

        cm = ConnectionManager()
        ws = FakeWS()
        asyncio.run(cm.send_personal(ws, {"type": "test"}))
        assert ws.sent == {"type": "test"}

    def test_broadcast_removes_dead(self):
        import asyncio

        class DeadWS:
            async def send_json(self, data):
                raise ConnectionError("dead")

        cm = ConnectionManager()
        dead = DeadWS()
        cm.active_connections.append(dead)
        asyncio.run(cm.broadcast({"type": "test"}))
        assert dead not in cm.active_connections


class TestGlobalExceptionHandlerExtended:
    def test_format_connection_error(self):
        handler = GlobalExceptionHandler(ConnectionManager())
        result = handler._format(ConnectionError, ConnectionError("test"))
        assert result["code"] == "NETWORK_ERROR"
        assert result["recoverable"] is True

    def test_format_timeout_error(self):
        handler = GlobalExceptionHandler(ConnectionManager())
        result = handler._format(TimeoutError, TimeoutError("test"))
        assert result["code"] == "TIMEOUT"

    def test_format_unknown_error(self):
        handler = GlobalExceptionHandler(ConnectionManager())
        result = handler._format(ValueError, ValueError("test"))
        assert result["code"] == "UNKNOWN"
        assert result["recoverable"] is False
