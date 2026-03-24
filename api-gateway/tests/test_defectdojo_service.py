"""Tests for DefectDojoClient service."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from gateway.services.defectdojo import DefectDojoClient


@pytest.mark.asyncio
async def test_init_with_token():
    with patch.dict("os.environ", {"DEFECTDOJO_API_TOKEN": "secret123", "DEFECTDOJO_URL": "http://dojo:8080"}):
        # Re-import to pick up env vars
        from importlib import reload
        import gateway.services.defectdojo as mod
        reload(mod)
        client = mod.DefectDojoClient()
        assert client.token == "secret123"
        assert client.base_url == "http://dojo:8080"


@pytest.mark.asyncio
async def test_init_no_token_logs_warning():
    with patch.dict("os.environ", {"DEFECTDOJO_API_TOKEN": ""}, clear=False):
        from importlib import reload
        import gateway.services.defectdojo as mod
        reload(mod)
        client = mod.DefectDojoClient()
        assert client.token == ""


@pytest.mark.asyncio
async def test_aenter_creates_client():
    client = DefectDojoClient()
    client.token = "tok"
    client.base_url = "http://dojo:8080"
    async with client:
        assert client._client is not None


@pytest.mark.asyncio
async def test_aexit_closes_client():
    client = DefectDojoClient()
    mock_http = AsyncMock()
    client._client = mock_http
    await client.__aexit__(None, None, None)
    mock_http.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_aexit_no_client():
    client = DefectDojoClient()
    client._client = None
    await client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_get_findings_success():
    client = DefectDojoClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": [{"id": 1}], "count": 1}
    mock_resp.raise_for_status = MagicMock()
    client._client = AsyncMock()
    client._client.get.return_value = mock_resp

    result = await client.get_findings(limit=10, offset=0)
    assert result == {"results": [{"id": 1}], "count": 1}
    client._client.get.assert_awaited_once_with(
        "/api/v2/findings/", params={"limit": 10, "offset": 0}
    )


@pytest.mark.asyncio
async def test_get_findings_with_severity():
    client = DefectDojoClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": [], "count": 0}
    mock_resp.raise_for_status = MagicMock()
    client._client = AsyncMock()
    client._client.get.return_value = mock_resp

    await client.get_findings(severity="High")
    call_params = client._client.get.call_args[1]["params"]
    assert call_params["severity"] == "High"


@pytest.mark.asyncio
async def test_get_findings_with_scan_type():
    client = DefectDojoClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": [], "count": 0}
    mock_resp.raise_for_status = MagicMock()
    client._client = AsyncMock()
    client._client.get.return_value = mock_resp

    await client.get_findings(scan_type="Semgrep")
    call_params = client._client.get.call_args[1]["params"]
    assert call_params["test__test_type__name"] == "Semgrep"


@pytest.mark.asyncio
async def test_get_findings_http_error():
    client = DefectDojoClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )
    client._client = AsyncMock()
    client._client.get.return_value = mock_resp

    with pytest.raises(httpx.HTTPStatusError):
        await client.get_findings()


@pytest.mark.asyncio
async def test_get_findings_transport_error_retries():
    client = DefectDojoClient()
    client._client = AsyncMock()
    client._client.get.side_effect = httpx.TransportError("connection reset")

    with pytest.raises(Exception):
        # tenacity will retry 3 times then raise
        await client.get_findings()
    # Verify it was called 3 times (tenacity retries)
    assert client._client.get.call_count == 3
