"""Tests for /api/findings/summary endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from gateway.main import app


@pytest.fixture
def mock_dojo_client():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_findings_summary_single_page(mock_dojo_client):
    mock_dojo_client.get_findings.return_value = {
        "results": [
            {"severity": "High"},
            {"severity": "High"},
            {"severity": "Medium"},
            {"severity": "Low"},
        ],
        "count": 4,
    }

    with patch("gateway.routes.defectdojo.DefectDojoClient", return_value=mock_dojo_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/findings/summary")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    assert data["severity_counts"]["High"] == 2
    assert data["severity_counts"]["Medium"] == 1
    assert data["severity_counts"]["Low"] == 1


@pytest.mark.asyncio
async def test_findings_summary_multiple_pages(mock_dojo_client):
    # First call returns a full page, second returns partial
    mock_dojo_client.get_findings.side_effect = [
        {
            "results": [{"severity": "High"}] * 500,
            "count": 600,
        },
        {
            "results": [{"severity": "Medium"}] * 100,
            "count": 600,
        },
    ]

    with patch("gateway.routes.defectdojo.DefectDojoClient", return_value=mock_dojo_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/findings/summary")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 600
    assert data["severity_counts"]["High"] == 500
    assert data["severity_counts"]["Medium"] == 100


@pytest.mark.asyncio
async def test_findings_summary_empty_results(mock_dojo_client):
    mock_dojo_client.get_findings.return_value = {
        "results": [],
        "count": 0,
    }

    with patch("gateway.routes.defectdojo.DefectDojoClient", return_value=mock_dojo_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/findings/summary")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["severity_counts"] == {}


@pytest.mark.asyncio
async def test_findings_summary_error(mock_dojo_client):
    mock_dojo_client.get_findings.side_effect = Exception("connection refused")

    with patch("gateway.routes.defectdojo.DefectDojoClient", return_value=mock_dojo_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/findings/summary")

    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_findings_summary_unknown_severity(mock_dojo_client):
    mock_dojo_client.get_findings.return_value = {
        "results": [
            {"severity": "Critical"},
            {},  # missing severity => "Unknown"
        ],
        "count": 2,
    }

    with patch("gateway.routes.defectdojo.DefectDojoClient", return_value=mock_dojo_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/findings/summary")

    assert resp.status_code == 200
    data = resp.json()
    assert data["severity_counts"]["Critical"] == 1
    assert data["severity_counts"]["Unknown"] == 1


@pytest.mark.asyncio
async def test_findings_summary_stops_at_total(mock_dojo_client):
    """When offset >= total, pagination stops."""
    mock_dojo_client.get_findings.side_effect = [
        {
            "results": [{"severity": "Info"}] * 10,
            "count": 10,
        },
    ]

    with patch("gateway.routes.defectdojo.DefectDojoClient", return_value=mock_dojo_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/findings/summary")

    assert resp.status_code == 200
    # Only one call since offset (10) >= total (10) after first page
    assert mock_dojo_client.get_findings.call_count == 1


@pytest.mark.asyncio
async def test_findings_route_success(mock_dojo_client):
    """Test GET /api/findings with success."""
    mock_dojo_client.get_findings.return_value = {"results": [{"id": 1}], "count": 1}

    with patch("gateway.routes.defectdojo.DefectDojoClient", return_value=mock_dojo_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/findings")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_findings_route_error(mock_dojo_client):
    """Test GET /api/findings when DefectDojo is unreachable."""
    mock_dojo_client.get_findings.side_effect = Exception("unreachable")

    with patch("gateway.routes.defectdojo.DefectDojoClient", return_value=mock_dojo_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/findings")

    assert resp.status_code == 502
