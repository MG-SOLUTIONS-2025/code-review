"""Tests for TabbyClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from gateway.services.tabby import TabbyClient


@pytest.mark.asyncio
async def test_aenter_creates_client():
    client = TabbyClient()
    client._base_url = "http://tabby:8080"
    async with client:
        assert client._client is not None
    # after exit, client is closed (no assertion needed, just no error)


@pytest.mark.asyncio
async def test_aexit_closes_client():
    client = TabbyClient()
    mock_http = AsyncMock()
    client._client = mock_http
    await client.__aexit__(None, None, None)
    mock_http.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_aexit_no_client():
    client = TabbyClient()
    client._client = None
    # Should not raise
    await client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_is_healthy_no_base_url():
    client = TabbyClient()
    client._base_url = ""
    result = await client.is_healthy()
    assert result is False


@pytest.mark.asyncio
async def test_is_healthy_success():
    client = TabbyClient()
    client._base_url = "http://tabby:8080"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    client._client = AsyncMock()
    client._client.get.return_value = mock_resp
    result = await client.is_healthy()
    assert result is True
    client._client.get.assert_awaited_once_with("/v1/health")


@pytest.mark.asyncio
async def test_is_healthy_non_200():
    client = TabbyClient()
    client._base_url = "http://tabby:8080"
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    client._client = AsyncMock()
    client._client.get.return_value = mock_resp
    result = await client.is_healthy()
    assert result is False


@pytest.mark.asyncio
async def test_is_healthy_exception():
    client = TabbyClient()
    client._base_url = "http://tabby:8080"
    client._client = AsyncMock()
    client._client.get.side_effect = Exception("connection refused")
    result = await client.is_healthy()
    assert result is False


@pytest.mark.asyncio
async def test_search_code_basic():
    client = TabbyClient()
    client._client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"hits": [{"id": 1, "doc": "test"}]}
    mock_resp.raise_for_status = MagicMock()
    client._client.get.return_value = mock_resp

    results = await client.search_code("def foo", limit=3)
    assert results == [{"id": 1, "doc": "test"}]
    client._client.get.assert_awaited_once_with(
        "/v1beta/search", params={"q": "def foo", "limit": 3}
    )


@pytest.mark.asyncio
async def test_search_code_with_language():
    client = TabbyClient()
    client._client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"hits": []}
    mock_resp.raise_for_status = MagicMock()
    client._client.get.return_value = mock_resp

    results = await client.search_code("def foo", language="python", limit=5)
    assert results == []
    call_kwargs = client._client.get.call_args
    assert call_kwargs[1]["params"]["language"] == "python"


@pytest.mark.asyncio
async def test_search_code_no_hits_key():
    client = TabbyClient()
    client._client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}
    mock_resp.raise_for_status = MagicMock()
    client._client.get.return_value = mock_resp

    results = await client.search_code("query")
    assert results == []


@pytest.mark.asyncio
async def test_search_code_raises_on_http_error():
    client = TabbyClient()
    client._client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )
    client._client.get.return_value = mock_resp

    with pytest.raises(httpx.HTTPStatusError):
        await client.search_code("query")


@pytest.mark.asyncio
async def test_get_context_for_file():
    client = TabbyClient()
    client._client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"hits": [{"snippet": "code"}]}
    mock_resp.raise_for_status = MagicMock()
    client._client.get.return_value = mock_resp

    results = await client.get_context_for_file("src/main.py", 10, 20)
    assert results == [{"snippet": "code"}]
    client._client.get.assert_awaited_once_with(
        "/v1beta/search", params={"q": "src/main.py:10-20", "limit": 5}
    )
