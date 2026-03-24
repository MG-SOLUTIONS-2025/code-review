"""Tests for the generic exception handler in main.py (lines 54-57)."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from gateway.main import app


@pytest.mark.asyncio
async def test_generic_exception_handler_returns_500():
    """An unhandled exception in a route should trigger the generic handler and return 500."""
    # Patch the health route to raise an unhandled exception
    with patch(
        "gateway.routes.health._check_llm",
        AsyncMock(side_effect=RuntimeError("unexpected crash")),
    ):
        with patch(
            "gateway.routes.health._check_simple",
            AsyncMock(side_effect=RuntimeError("unexpected crash")),
        ):
            with patch(
                "gateway.routes.health._check_tabby",
                AsyncMock(side_effect=RuntimeError("unexpected crash")),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app, raise_app_exceptions=False),
                    base_url="http://test",
                ) as ac:
                    resp = await ac.get("/api/health")

    assert resp.status_code == 500
    assert resp.json() == {"error": "Internal server error"}
