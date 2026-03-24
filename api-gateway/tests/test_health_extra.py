"""Extra tests for health route — covering _check_simple, _check_llm, _check_tabby, /api/models."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from gateway.main import app


# ---------------------------------------------------------------------------
# _check_simple
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_simple_healthy():
    from gateway.routes.health import _check_simple

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("gateway.routes.health.httpx.AsyncClient") as MockClient:
        mc = AsyncMock()
        mc.__aenter__ = AsyncMock(return_value=mc)
        mc.__aexit__ = AsyncMock(return_value=None)
        mc.get.return_value = mock_resp
        MockClient.return_value = mc

        result = await _check_simple("TestService", "http://test/health")
    assert result == {"status": "healthy"}


@pytest.mark.asyncio
async def test_check_simple_unhealthy():
    from gateway.routes.health import _check_simple

    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("gateway.routes.health.httpx.AsyncClient") as MockClient:
        mc = AsyncMock()
        mc.__aenter__ = AsyncMock(return_value=mc)
        mc.__aexit__ = AsyncMock(return_value=None)
        mc.get.return_value = mock_resp
        MockClient.return_value = mc

        result = await _check_simple("TestService", "http://test/health")
    assert result == {"status": "unhealthy"}


@pytest.mark.asyncio
async def test_check_simple_timeout():
    from gateway.routes.health import _check_simple

    with patch("gateway.routes.health.httpx.AsyncClient") as MockClient:
        mc = AsyncMock()
        mc.__aenter__ = AsyncMock(return_value=mc)
        mc.__aexit__ = AsyncMock(return_value=None)
        mc.get.side_effect = httpx.TimeoutException("timed out")
        MockClient.return_value = mc

        result = await _check_simple("TestService", "http://test/health")
    assert result == {"status": "unreachable"}


@pytest.mark.asyncio
async def test_check_simple_connect_error():
    from gateway.routes.health import _check_simple

    with patch("gateway.routes.health.httpx.AsyncClient") as MockClient:
        mc = AsyncMock()
        mc.__aenter__ = AsyncMock(return_value=mc)
        mc.__aexit__ = AsyncMock(return_value=None)
        mc.get.side_effect = httpx.ConnectError("refused")
        MockClient.return_value = mc

        result = await _check_simple("TestService", "http://test/health")
    assert result == {"status": "unreachable"}


@pytest.mark.asyncio
async def test_check_simple_generic_exception():
    from gateway.routes.health import _check_simple

    with patch("gateway.routes.health.httpx.AsyncClient") as MockClient:
        mc = AsyncMock()
        mc.__aenter__ = AsyncMock(return_value=mc)
        mc.__aexit__ = AsyncMock(return_value=None)
        mc.get.side_effect = RuntimeError("unexpected")
        MockClient.return_value = mc

        result = await _check_simple("TestService", "http://test/health")
    assert result == {"status": "unreachable"}


# ---------------------------------------------------------------------------
# _check_llm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_llm_healthy_ollama():
    from gateway.routes.health import _check_llm

    mock_llm = AsyncMock()
    mock_llm.__aenter__ = AsyncMock(return_value=mock_llm)
    mock_llm.__aexit__ = AsyncMock(return_value=None)
    mock_llm.engine = "ollama"
    mock_llm.list_models.return_value = [{"name": "qwen2.5-coder:32b"}]

    with patch("gateway.routes.health.LLMClient", return_value=mock_llm):
        result = await _check_llm()

    assert result["status"] == "healthy"
    assert result["engine"] == "ollama"
    assert result["model"] == "qwen2.5-coder:32b"


@pytest.mark.asyncio
async def test_check_llm_healthy_vllm():
    from gateway.routes.health import _check_llm

    mock_llm = AsyncMock()
    mock_llm.__aenter__ = AsyncMock(return_value=mock_llm)
    mock_llm.__aexit__ = AsyncMock(return_value=None)
    mock_llm.engine = "vllm"
    mock_llm.list_models.return_value = [{"id": "Qwen/Qwen2.5-Coder-32B"}]

    with patch("gateway.routes.health.LLMClient", return_value=mock_llm):
        result = await _check_llm()

    assert result["status"] == "healthy"
    assert result["engine"] == "vllm"
    assert result["model"] == "Qwen/Qwen2.5-Coder-32B"


@pytest.mark.asyncio
async def test_check_llm_healthy_no_models():
    from gateway.routes.health import _check_llm

    mock_llm = AsyncMock()
    mock_llm.__aenter__ = AsyncMock(return_value=mock_llm)
    mock_llm.__aexit__ = AsyncMock(return_value=None)
    mock_llm.engine = "ollama"
    mock_llm.list_models.return_value = []

    with patch("gateway.routes.health.LLMClient", return_value=mock_llm):
        result = await _check_llm()

    assert result["status"] == "healthy"
    assert result["model"] is None


@pytest.mark.asyncio
async def test_check_llm_timeout():
    from gateway.routes.health import _check_llm

    call_count = 0

    def make_mock_llm():
        nonlocal call_count
        call_count += 1
        mock_llm = AsyncMock()
        mock_llm.__aenter__ = AsyncMock(return_value=mock_llm)
        mock_llm.__aexit__ = AsyncMock(return_value=None)
        if call_count == 1:
            mock_llm.list_models.side_effect = httpx.TimeoutException("timeout")
        else:
            mock_llm.engine = "ollama"
        return mock_llm

    with patch("gateway.routes.health.LLMClient", side_effect=make_mock_llm):
        result = await _check_llm()

    assert result["status"] == "unreachable"


@pytest.mark.asyncio
async def test_check_llm_connect_error():
    from gateway.routes.health import _check_llm

    call_count = 0

    def make_mock_llm():
        nonlocal call_count
        call_count += 1
        mock_llm = AsyncMock()
        mock_llm.__aenter__ = AsyncMock(return_value=mock_llm)
        mock_llm.__aexit__ = AsyncMock(return_value=None)
        if call_count == 1:
            mock_llm.list_models.side_effect = httpx.ConnectError("refused")
        else:
            mock_llm.engine = "ollama"
        return mock_llm

    with patch("gateway.routes.health.LLMClient", side_effect=make_mock_llm):
        result = await _check_llm()

    assert result["status"] == "unreachable"


@pytest.mark.asyncio
async def test_check_llm_generic_exception():
    from gateway.routes.health import _check_llm

    call_count = 0

    def make_mock_llm():
        nonlocal call_count
        call_count += 1
        mock_llm = AsyncMock()
        mock_llm.__aenter__ = AsyncMock(return_value=mock_llm)
        mock_llm.__aexit__ = AsyncMock(return_value=None)
        if call_count == 1:
            mock_llm.list_models.side_effect = RuntimeError("unexpected")
        else:
            mock_llm.engine = "ollama"
        return mock_llm

    with patch("gateway.routes.health.LLMClient", side_effect=make_mock_llm):
        result = await _check_llm()

    assert result["status"] == "unreachable"


# ---------------------------------------------------------------------------
# _check_tabby
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_tabby_not_configured():
    from gateway.routes.health import _check_tabby

    with patch("gateway.routes.health.TABBY_URL", ""):
        result = await _check_tabby()
    assert result is None


@pytest.mark.asyncio
async def test_check_tabby_configured():
    from gateway.routes.health import _check_tabby

    with patch("gateway.routes.health.TABBY_URL", "http://tabby:8080"):
        with patch("gateway.routes.health._check_simple", AsyncMock(return_value={"status": "healthy"})) as mock_check:
            result = await _check_tabby()

    assert result == {"status": "healthy"}
    mock_check.assert_awaited_once_with("Tabby", "http://tabby:8080/v1/health")


# ---------------------------------------------------------------------------
# /api/models endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_endpoint():
    mock_llm = AsyncMock()
    mock_llm.__aenter__ = AsyncMock(return_value=mock_llm)
    mock_llm.__aexit__ = AsyncMock(return_value=None)
    mock_llm.list_models.return_value = [{"name": "model1"}, {"name": "model2"}]

    with patch("gateway.routes.health.LLMClient", return_value=mock_llm):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/models")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["models"]) == 2
