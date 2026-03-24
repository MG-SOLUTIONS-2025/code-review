"""Tests for /api/webhook endpoint."""

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from gateway.main import app


@pytest.mark.asyncio
async def test_webhook_no_secret_forwards_to_pr_agent():
    """When WEBHOOK_SECRET is empty, request is forwarded without signature check."""
    mock_resp = MagicMock()
    mock_resp.content = b'{"ok": true}'
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}

    with patch("gateway.routes.webhook.WEBHOOK_SECRET", ""):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request.return_value = mock_resp
            MockClient.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.post(
                    "/api/webhook",
                    content=b'{"action": "opened"}',
                    headers={"content-type": "application/json"},
                )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_valid_gitlab_token():
    """When X-Gitlab-Token matches WEBHOOK_SECRET, request is forwarded."""
    mock_resp = MagicMock()
    mock_resp.content = b'{"ok": true}'
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}

    with patch("gateway.routes.webhook.WEBHOOK_SECRET", "my-secret"):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request.return_value = mock_resp
            MockClient.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.post(
                    "/api/webhook",
                    content=b'{"action": "opened"}',
                    headers={
                        "content-type": "application/json",
                        "X-Gitlab-Token": "my-secret",
                    },
                )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_invalid_gitlab_token():
    """When X-Gitlab-Token doesn't match, 401 is returned."""
    with patch("gateway.routes.webhook.WEBHOOK_SECRET", "my-secret"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/webhook",
                content=b'{"action": "opened"}',
                headers={
                    "content-type": "application/json",
                    "X-Gitlab-Token": "wrong-secret",
                },
            )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_valid_gitea_signature():
    """When X-Gitea-Signature matches HMAC, request is forwarded."""
    secret = "my-secret"
    body = b'{"action": "opened"}'
    expected_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    mock_resp = MagicMock()
    mock_resp.content = b'{"ok": true}'
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}

    with patch("gateway.routes.webhook.WEBHOOK_SECRET", secret):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request.return_value = mock_resp
            MockClient.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.post(
                    "/api/webhook",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "X-Gitea-Signature": expected_sig,
                    },
                )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_invalid_gitea_signature():
    """When X-Gitea-Signature doesn't match, 401 is returned."""
    with patch("gateway.routes.webhook.WEBHOOK_SECRET", "my-secret"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/webhook",
                content=b'{"action": "opened"}',
                headers={
                    "content-type": "application/json",
                    "X-Gitea-Signature": "badsig",
                },
            )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_missing_signature_header():
    """When secret is set but no signature header is present, 401 is returned."""
    with patch("gateway.routes.webhook.WEBHOOK_SECRET", "my-secret"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/webhook",
                content=b'{"action": "opened"}',
                headers={"content-type": "application/json"},
            )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_proxy_failure():
    """When forwarding to pr-agent fails, 502 is returned."""
    with patch("gateway.routes.webhook.WEBHOOK_SECRET", ""):
        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request.side_effect = Exception("connection refused")
            MockClient.return_value = mock_client

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                resp = await ac.post(
                    "/api/webhook",
                    content=b'{"action": "opened"}',
                    headers={"content-type": "application/json"},
                )

    assert resp.status_code == 502
