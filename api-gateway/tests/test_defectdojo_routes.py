"""Tests for DefectDojo route query validation."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from gateway.main import app


@pytest.fixture
def mock_dojo_client():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get_findings.return_value = {"results": [], "count": 0}
    return client


@pytest.mark.asyncio
async def test_findings_limit_too_high():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/findings?limit=501")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_findings_limit_zero():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/findings?limit=0")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_findings_negative_offset():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/findings?offset=-1")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_findings_invalid_severity():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/findings?severity=InvalidSev")
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("severity", ["Critical", "High", "Medium", "Low", "Info"])
async def test_findings_valid_severity(severity, mock_dojo_client):
    with patch("gateway.routes.defectdojo.DefectDojoClient", return_value=mock_dojo_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get(f"/api/findings?severity={severity}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_findings_defaults(mock_dojo_client):
    with patch("gateway.routes.defectdojo.DefectDojoClient", return_value=mock_dojo_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/findings")
    assert resp.status_code == 200
    mock_dojo_client.get_findings.assert_called_once_with(limit=20, offset=0, severity=None, scan_type=None)
