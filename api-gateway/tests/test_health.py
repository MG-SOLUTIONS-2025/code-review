"""Tests for /api/health endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from gateway.main import app


@pytest.mark.asyncio
async def test_health_all_healthy():
    healthy = {"status": "healthy"}
    llm_healthy = {"engine": "ollama", "status": "healthy", "model": "qwen2.5-coder:32b"}

    with (
        patch("gateway.routes.health._check_llm", AsyncMock(return_value=llm_healthy)),
        patch("gateway.routes.health._check_simple", AsyncMock(return_value=healthy)),
        patch("gateway.routes.health._check_tabby", AsyncMock(return_value=None)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_health_degraded_when_service_unreachable():
    unreachable = {"status": "unreachable"}
    llm_ok = {"engine": "ollama", "status": "healthy", "model": "qwen2.5-coder:32b"}

    async def mock_check_simple(name, url):
        if "pr-agent" in url:
            return unreachable
        return {"status": "healthy"}

    with (
        patch("gateway.routes.health._check_llm", AsyncMock(return_value=llm_ok)),
        patch("gateway.routes.health._check_simple", mock_check_simple),
        patch("gateway.routes.health._check_tabby", AsyncMock(return_value=None)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_includes_tabby_when_configured():
    healthy = {"status": "healthy"}
    llm_ok = {"engine": "ollama", "status": "healthy", "model": "qwen2.5-coder:32b"}
    tabby_ok = {"status": "healthy"}

    with (
        patch("gateway.routes.health._check_llm", AsyncMock(return_value=llm_ok)),
        patch("gateway.routes.health._check_simple", AsyncMock(return_value=healthy)),
        patch("gateway.routes.health._check_tabby", AsyncMock(return_value=tabby_ok)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/health")

    data = resp.json()
    assert "tabby" in data["services"]
