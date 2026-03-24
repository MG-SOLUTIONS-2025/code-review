"""Tests for GET /api/reviews endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from gateway.main import app


@pytest.fixture
def mock_git_client():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_get_reviews_success(mock_git_client):
    mock_git_client.list_merge_requests.return_value = [
        {
            "id": 1,
            "title": "Test MR",
            "author": "alice",
            "state": "open",
            "url": "http://example.com/mr/1",
            "created_at": "2024-01-01T00:00:00Z",
        }
    ]
    mock_git_client.get_review_comments.return_value = [
        {"id": 10, "body": "LGTM", "author": "bob", "created_at": "2024-01-02T00:00:00Z"}
    ]

    with patch("gateway.routes.reviews.create_git_client", return_value=mock_git_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/reviews")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["reviews"]) == 1
    assert data["reviews"][0]["title"] == "Test MR"
    assert len(data["reviews"][0]["review_comments"]) == 1


@pytest.mark.asyncio
async def test_get_reviews_empty(mock_git_client):
    mock_git_client.list_merge_requests.return_value = []

    with patch("gateway.routes.reviews.create_git_client", return_value=mock_git_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/reviews")

    assert resp.status_code == 200
    assert resp.json() == {"reviews": []}


@pytest.mark.asyncio
async def test_get_reviews_error(mock_git_client):
    mock_git_client.list_merge_requests.side_effect = Exception("connection refused")

    with patch("gateway.routes.reviews.create_git_client", return_value=mock_git_client):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/reviews")

    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_get_reviews_limit_validation():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/reviews?limit=999")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_reviews_limit_zero():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/reviews?limit=0")
    assert resp.status_code == 422
