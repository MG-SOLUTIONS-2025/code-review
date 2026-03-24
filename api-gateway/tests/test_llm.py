"""Comprehensive tests for gateway.services.llm module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import tiktoken
from tenacity import RetryError

import gateway.services.llm as llm_module
from gateway.services.llm import (
    LLMClient,
    _get_encoder,
    count_tokens,
    get_git_semaphore,
    get_llm_semaphore,
    trim_messages_to_budget,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_semaphores():
    """Reset lazy-initialized semaphores between tests."""
    llm_module._llm_semaphore = None
    llm_module._git_semaphore = None
    yield
    llm_module._llm_semaphore = None
    llm_module._git_semaphore = None


@pytest.fixture(autouse=True)
def _clear_encoder_cache():
    """Clear the lru_cache on _get_encoder so tests are independent."""
    _get_encoder.cache_clear()
    yield
    _get_encoder.cache_clear()


@pytest.fixture
def sample_messages() -> list[dict]:
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, world!"},
    ]


@pytest.fixture
def mock_httpx_client():
    """Return an AsyncMock that behaves like httpx.AsyncClient."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.aclose = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# get_llm_semaphore / get_git_semaphore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_llm_semaphore_creates_once():
    sem1 = get_llm_semaphore()
    sem2 = get_llm_semaphore()
    assert sem1 is sem2
    assert isinstance(sem1, asyncio.Semaphore)


@pytest.mark.asyncio
async def test_get_git_semaphore_creates_once():
    sem1 = get_git_semaphore()
    sem2 = get_git_semaphore()
    assert sem1 is sem2
    assert isinstance(sem1, asyncio.Semaphore)


@pytest.mark.asyncio
async def test_semaphores_are_independent():
    llm = get_llm_semaphore()
    git = get_git_semaphore()
    assert llm is not git


# ---------------------------------------------------------------------------
# _get_encoder
# ---------------------------------------------------------------------------


def test_get_encoder_valid():
    enc = _get_encoder("cl100k_base")
    assert enc is not None
    assert isinstance(enc, tiktoken.Encoding)


def test_get_encoder_invalid_falls_back():
    enc = _get_encoder("nonexistent_encoding_xyz")
    # Should fall back to cl100k_base
    expected = tiktoken.get_encoding("cl100k_base")
    assert enc.name == expected.name


def test_get_encoder_caches():
    enc1 = _get_encoder("cl100k_base")
    enc2 = _get_encoder("cl100k_base")
    assert enc1 is enc2


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------


def test_count_tokens_empty_list():
    assert count_tokens([]) == 0


def test_count_tokens_single_message():
    msgs = [{"role": "user", "content": "hi"}]
    result = count_tokens(msgs)
    # 4 overhead + tokens for "user" + tokens for "hi"
    assert result > 0


def test_count_tokens_multiple_messages(sample_messages):
    result = count_tokens(sample_messages)
    assert result > 0


def test_count_tokens_missing_keys():
    """Messages with missing role/content should still work (defaults to '')."""
    msgs = [{}]
    result = count_tokens(msgs)
    # 4 overhead + 0 for empty role + 0 for empty content
    assert result == 4


def test_count_tokens_custom_encoding():
    msgs = [{"role": "user", "content": "test"}]
    result = count_tokens(msgs, encoding="cl100k_base")
    assert result > 0


# ---------------------------------------------------------------------------
# trim_messages_to_budget
# ---------------------------------------------------------------------------


def test_trim_empty_messages():
    result = trim_messages_to_budget([], budget=100)
    assert result == []


def test_trim_under_budget(sample_messages):
    """Messages that fit within budget should be returned as-is."""
    result = trim_messages_to_budget(sample_messages, budget=99999)
    assert result == sample_messages


def test_trim_over_budget():
    """When over budget, the last user message content should be truncated."""
    long_content = "word " * 5000  # Very long message
    msgs = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": long_content},
    ]
    budget = 100
    result = trim_messages_to_budget(msgs, budget=budget)
    assert len(result) == 2
    assert result[1]["role"] == "user"
    assert "[... truncated to fit token budget]" in result[1]["content"]
    # The trimmed result should be shorter
    assert len(result[1]["content"]) < len(long_content)


def test_trim_no_user_message():
    """If there's no user message, the loop breaks without trimming."""
    msgs = [
        {"role": "system", "content": "x " * 5000},
    ]
    # Over budget but no user message to trim — loop finishes without finding one.
    result = trim_messages_to_budget(msgs, budget=10)
    # Returns the list unchanged since no user message was found
    assert len(result) == 1


def test_trim_trims_last_user_message():
    """When multiple user messages exist, only the last one is trimmed."""
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "word " * 5000},
    ]
    result = trim_messages_to_budget(msgs, budget=100)
    # First user message untouched
    assert result[0]["content"] == "first"
    # Last user message trimmed
    assert "[... truncated to fit token budget]" in result[2]["content"]


def test_trim_very_tight_budget():
    """When budget is so tight that allowed <= 0, content is not re-encoded."""
    msgs = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "hello world"},
    ]
    # Budget of 1 is less than overhead alone, so allowed will be <= 0
    result = trim_messages_to_budget(msgs, budget=1)
    # The function still returns a list; the user message won't get the
    # truncated text appended because the `if allowed > 0` guard prevents it.
    assert len(result) == 2


def test_trim_preserves_extra_keys_in_message():
    """Extra keys in the user message dict should be preserved after trimming."""
    msgs = [
        {"role": "user", "content": "word " * 5000, "name": "test_user"},
    ]
    result = trim_messages_to_budget(msgs, budget=50)
    assert result[0].get("name") == "test_user"


# ---------------------------------------------------------------------------
# LLMClient — context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_client_context_manager():
    client = LLMClient()
    async with client:
        assert client._client is not None
    # After exiting, aclose should have been called (no error)


@pytest.mark.asyncio
async def test_llm_client_aexit_without_client():
    """__aexit__ should be safe even if _client is None."""
    client = LLMClient()
    await client.__aexit__(None, None, None)  # Should not raise


# ---------------------------------------------------------------------------
# LLMClient.is_healthy — vllm engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_healthy_vllm_healthy(mock_httpx_client):
    resp = MagicMock()
    resp.status_code = 200
    mock_httpx_client.get = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        client._client = mock_httpx_client
        assert await client.is_healthy() is True
        mock_httpx_client.get.assert_awaited_once_with("/v1/models")


@pytest.mark.asyncio
async def test_is_healthy_vllm_unhealthy(mock_httpx_client):
    resp = MagicMock()
    resp.status_code = 500
    mock_httpx_client.get = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        client._client = mock_httpx_client
        assert await client.is_healthy() is False


@pytest.mark.asyncio
async def test_is_healthy_vllm_exception(mock_httpx_client):
    mock_httpx_client.get = AsyncMock(side_effect=httpx.ConnectError("down"))

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        client._client = mock_httpx_client
        assert await client.is_healthy() is False


# ---------------------------------------------------------------------------
# LLMClient.is_healthy — ollama engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_healthy_ollama_healthy(mock_httpx_client):
    resp = MagicMock()
    resp.status_code = 200
    mock_httpx_client.get = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "ollama"), \
         patch.object(llm_module, "OLLAMA_URL", "http://ollama:11434"):
        client = LLMClient()
        client._client = mock_httpx_client
        assert await client.is_healthy() is True
        mock_httpx_client.get.assert_awaited_once_with("/api/tags")


@pytest.mark.asyncio
async def test_is_healthy_ollama_unhealthy(mock_httpx_client):
    resp = MagicMock()
    resp.status_code = 503
    mock_httpx_client.get = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "ollama"), \
         patch.object(llm_module, "OLLAMA_URL", "http://ollama:11434"):
        client = LLMClient()
        client._client = mock_httpx_client
        assert await client.is_healthy() is False


@pytest.mark.asyncio
async def test_is_healthy_ollama_exception(mock_httpx_client):
    mock_httpx_client.get = AsyncMock(side_effect=Exception("network error"))

    with patch.object(llm_module, "INFERENCE_ENGINE", "ollama"), \
         patch.object(llm_module, "OLLAMA_URL", "http://ollama:11434"):
        client = LLMClient()
        client._client = mock_httpx_client
        assert await client.is_healthy() is False


# ---------------------------------------------------------------------------
# LLMClient.list_models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_vllm(mock_httpx_client):
    models_data = {"data": [{"id": "model-1"}, {"id": "model-2"}]}
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = models_data
    resp.raise_for_status = MagicMock()
    mock_httpx_client.get = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        client._client = mock_httpx_client
        result = await client.list_models()
        assert len(result) == 2
        assert result[0]["id"] == "model-1"
        mock_httpx_client.get.assert_awaited_once_with("/v1/models")


@pytest.mark.asyncio
async def test_list_models_ollama(mock_httpx_client):
    models_data = {"models": [{"name": "llama3"}]}
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = models_data
    resp.raise_for_status = MagicMock()
    mock_httpx_client.get = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "ollama"), \
         patch.object(llm_module, "OLLAMA_URL", "http://ollama:11434"):
        client = LLMClient()
        client._client = mock_httpx_client
        result = await client.list_models()
        assert len(result) == 1
        assert result[0]["name"] == "llama3"
        mock_httpx_client.get.assert_awaited_once_with("/api/tags")


@pytest.mark.asyncio
async def test_list_models_empty_response(mock_httpx_client):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {}
    resp.raise_for_status = MagicMock()
    mock_httpx_client.get = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        client._client = mock_httpx_client
        result = await client.list_models()
        assert result == []


# ---------------------------------------------------------------------------
# LLMClient.chat_completion — vllm engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_vllm(mock_httpx_client, sample_messages):
    vllm_response = {
        "choices": [{"message": {"role": "assistant", "content": "Hi!"}}]
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = vllm_response
    resp.raise_for_status = MagicMock()
    mock_httpx_client.post = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        client._client = mock_httpx_client
        result = await client.chat_completion(sample_messages, model="test-model")

    assert result == vllm_response
    mock_httpx_client.post.assert_awaited_once()
    call_kwargs = mock_httpx_client.post.call_args
    assert call_kwargs[0][0] == "/v1/chat/completions"
    assert call_kwargs[1]["json"]["model"] == "test-model"
    assert call_kwargs[1]["json"]["temperature"] == 0.1


@pytest.mark.asyncio
async def test_chat_completion_vllm_default_model(mock_httpx_client, sample_messages):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": []}
    resp.raise_for_status = MagicMock()
    mock_httpx_client.post = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"), \
         patch.dict("os.environ", {"VLLM_MODEL": "my-vllm-model"}, clear=False):
        client = LLMClient()
        client._client = mock_httpx_client
        await client.chat_completion(sample_messages)

    call_json = mock_httpx_client.post.call_args[1]["json"]
    assert call_json["model"] == "my-vllm-model"


# ---------------------------------------------------------------------------
# LLMClient.chat_completion — ollama engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_ollama(mock_httpx_client, sample_messages):
    ollama_response = {
        "message": {"role": "assistant", "content": "Hello!"}
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = ollama_response
    resp.raise_for_status = MagicMock()
    mock_httpx_client.post = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "ollama"), \
         patch.object(llm_module, "OLLAMA_URL", "http://ollama:11434"):
        client = LLMClient()
        client._client = mock_httpx_client
        result = await client.chat_completion(
            sample_messages, model="llama3", temperature=0.5
        )

    # Should be normalized to OpenAI format
    assert "choices" in result
    assert result["choices"][0]["message"]["content"] == "Hello!"
    assert result["choices"][0]["message"]["role"] == "assistant"

    call_kwargs = mock_httpx_client.post.call_args
    assert call_kwargs[0][0] == "/api/chat"
    assert call_kwargs[1]["json"]["stream"] is False
    assert call_kwargs[1]["json"]["options"]["temperature"] == 0.5


@pytest.mark.asyncio
async def test_chat_completion_ollama_default_model(mock_httpx_client, sample_messages):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"message": {"content": "ok"}}
    resp.raise_for_status = MagicMock()
    mock_httpx_client.post = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "ollama"), \
         patch.object(llm_module, "OLLAMA_URL", "http://ollama:11434"), \
         patch.dict("os.environ", {"OLLAMA_MODEL": "my-ollama-model"}, clear=False):
        client = LLMClient()
        client._client = mock_httpx_client
        await client.chat_completion(sample_messages)

    call_json = mock_httpx_client.post.call_args[1]["json"]
    assert call_json["model"] == "my-ollama-model"


@pytest.mark.asyncio
async def test_chat_completion_ollama_empty_message(mock_httpx_client, sample_messages):
    """When ollama response has no message key, content defaults to ''."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {}  # no "message" key
    resp.raise_for_status = MagicMock()
    mock_httpx_client.post = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "ollama"), \
         patch.object(llm_module, "OLLAMA_URL", "http://ollama:11434"):
        client = LLMClient()
        client._client = mock_httpx_client
        result = await client.chat_completion(sample_messages, model="m")

    assert result["choices"][0]["message"]["content"] == ""


# ---------------------------------------------------------------------------
# LLMClient.chat_completion — retry on TransportError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_retries_on_transport_error(mock_httpx_client, sample_messages):
    """TransportError should be retried (up to 3 attempts)."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    resp.raise_for_status = MagicMock()

    # Fail twice, succeed on third attempt
    mock_httpx_client.post = AsyncMock(
        side_effect=[
            httpx.ConnectError("fail1"),
            httpx.ConnectError("fail2"),
            resp,
        ]
    )

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        client._client = mock_httpx_client
        # Patch tenacity wait to avoid actual delays
        client.chat_completion.retry.wait = lambda *a, **kw: 0  # type: ignore[attr-defined]
        result = await client.chat_completion(sample_messages, model="m")

    assert result["choices"][0]["message"]["content"] == "ok"
    assert mock_httpx_client.post.await_count == 3


@pytest.mark.asyncio
async def test_chat_completion_transport_error_exhausted(mock_httpx_client, sample_messages):
    """After 3 transport errors, the exception should propagate."""
    mock_httpx_client.post = AsyncMock(
        side_effect=httpx.ConnectError("always fails")
    )

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        client._client = mock_httpx_client
        client.chat_completion.retry.wait = lambda *a, **kw: 0  # type: ignore[attr-defined]
        with pytest.raises(RetryError):
            await client.chat_completion(sample_messages, model="m")


# ---------------------------------------------------------------------------
# LLMClient.chat_completion — non-transport errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_non_transport_error_not_retried(mock_httpx_client, sample_messages):
    """Non-transport errors (e.g. HTTPStatusError) should not be retried."""
    request = httpx.Request("POST", "http://test")
    response = httpx.Response(500, request=request)
    mock_httpx_client.post = AsyncMock(
        side_effect=httpx.HTTPStatusError("500", request=request, response=response)
    )

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        client._client = mock_httpx_client
        client.chat_completion.retry.wait = lambda *a, **kw: 0  # type: ignore[attr-defined]
        with pytest.raises(httpx.HTTPStatusError):
            await client.chat_completion(sample_messages, model="m")

    # Should only be called once — no retry for HTTPStatusError
    assert mock_httpx_client.post.await_count == 1


# ---------------------------------------------------------------------------
# LLMClient.chat_completion — token budget trimming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_with_token_budget_under(mock_httpx_client, sample_messages):
    """When messages are under budget, they pass through unchanged."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    resp.raise_for_status = MagicMock()
    mock_httpx_client.post = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        client._client = mock_httpx_client
        await client.chat_completion(sample_messages, model="m", token_budget=99999)

    sent_messages = mock_httpx_client.post.call_args[1]["json"]["messages"]
    assert sent_messages == sample_messages


@pytest.mark.asyncio
async def test_chat_completion_with_token_budget_over(mock_httpx_client):
    """When messages exceed token budget, they should be trimmed."""
    long_msgs = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "word " * 5000},
    ]
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    resp.raise_for_status = MagicMock()
    mock_httpx_client.post = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        client._client = mock_httpx_client
        await client.chat_completion(long_msgs, model="m", token_budget=100)

    sent_messages = mock_httpx_client.post.call_args[1]["json"]["messages"]
    assert "[... truncated to fit token budget]" in sent_messages[1]["content"]


@pytest.mark.asyncio
async def test_chat_completion_no_token_budget(mock_httpx_client, sample_messages):
    """When token_budget is None, no trimming occurs."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    resp.raise_for_status = MagicMock()
    mock_httpx_client.post = AsyncMock(return_value=resp)

    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"), \
         patch("gateway.services.llm.trim_messages_to_budget") as mock_trim:
        client = LLMClient()
        client._client = mock_httpx_client
        await client.chat_completion(sample_messages, model="m", token_budget=None)

    mock_trim.assert_not_called()


# ---------------------------------------------------------------------------
# LLMClient.__init__ — engine selection
# ---------------------------------------------------------------------------


def test_llm_client_selects_vllm():
    with patch.object(llm_module, "INFERENCE_ENGINE", "vllm"), \
         patch.object(llm_module, "VLLM_URL", "http://vllm:8000"):
        client = LLMClient()
        assert client.engine == "vllm"
        assert client._base_url == "http://vllm:8000"


def test_llm_client_selects_ollama():
    with patch.object(llm_module, "INFERENCE_ENGINE", "ollama"), \
         patch.object(llm_module, "OLLAMA_URL", "http://ollama:11434"):
        client = LLMClient()
        assert client.engine == "ollama"
        assert client._base_url == "http://ollama:11434"
