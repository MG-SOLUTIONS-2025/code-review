import asyncio
import functools
import os

import httpx
import tiktoken
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

INFERENCE_ENGINE = os.getenv("INFERENCE_ENGINE", "ollama")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
VLLM_URL = os.getenv("VLLM_URL", "http://vllm:8000")

LLM_CONCURRENCY_LIMIT = int(os.getenv("LLM_CONCURRENCY_LIMIT", "6"))
GIT_CONCURRENCY_LIMIT = int(os.getenv("GIT_CONCURRENCY_LIMIT", "10"))
TOKEN_BUDGET_SUMMARIZE = int(os.getenv("TOKEN_BUDGET_SUMMARIZE", "6000"))
TOKEN_BUDGET_REVIEW = int(os.getenv("TOKEN_BUDGET_REVIEW", "24000"))
TIKTOKEN_ENCODING = os.getenv("TIKTOKEN_ENCODING", "cl100k_base")

# Lazy-initialized semaphores — created on first use so they bind to the
# running event loop rather than being created at import time.
_llm_semaphore: asyncio.Semaphore | None = None
_git_semaphore: asyncio.Semaphore | None = None


def get_llm_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(LLM_CONCURRENCY_LIMIT)
    return _llm_semaphore


def get_git_semaphore() -> asyncio.Semaphore:
    global _git_semaphore
    if _git_semaphore is None:
        _git_semaphore = asyncio.Semaphore(GIT_CONCURRENCY_LIMIT)
    return _git_semaphore


@functools.lru_cache(maxsize=4)
def _get_encoder(encoding: str):
    try:
        return tiktoken.get_encoding(encoding)
    except Exception:
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(messages: list[dict], encoding: str = TIKTOKEN_ENCODING) -> int:
    """Count tokens across a list of chat messages using tiktoken."""
    enc = _get_encoder(encoding)
    total = 0
    for msg in messages:
        # 4-token overhead per message (role tag + separators in OpenAI chat format)
        total += 4
        total += len(enc.encode(msg.get("role", "")))
        total += len(enc.encode(msg.get("content", "")))
    return total


def trim_messages_to_budget(
    messages: list[dict], budget: int, encoding: str = TIKTOKEN_ENCODING
) -> list[dict]:
    """Trim the last user message to fit within the token budget."""
    if not messages:
        return messages
    current = count_tokens(messages, encoding)
    if current <= budget:
        return messages

    enc = _get_encoder(encoding)
    trimmed = list(messages)
    for i in range(len(trimmed) - 1, -1, -1):
        if trimmed[i].get("role") == "user":
            content = trimmed[i]["content"]
            overhead = current - len(enc.encode(content))
            allowed = budget - overhead - 10  # small safety margin
            if allowed > 0:
                tokens = enc.encode(content)[:allowed]
                trimmed[i] = {
                    **trimmed[i],
                    "content": enc.decode(tokens) + "\n[... truncated to fit token budget]",
                }
            logger.warning(
                "Trimmed message from {} to ~{} tokens to fit budget {}",
                current,
                allowed,
                budget,
            )
            break
    return trimmed


class LLMClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self.engine = INFERENCE_ENGINE
        self._base_url = VLLM_URL if self.engine == "vllm" else OLLAMA_URL
        logger.info("LLM engine selected: {} at {}", self.engine, self._base_url)

    async def __aenter__(self):
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=120)
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    async def is_healthy(self) -> bool:
        try:
            if self.engine == "vllm":
                resp = await self._client.get("/v1/models")
            else:
                resp = await self._client.get("/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        if self.engine == "vllm":
            resp = await self._client.get("/v1/models")
            resp.raise_for_status()
            return resp.json().get("data", [])
        else:
            resp = await self._client.get("/api/tags")
            resp.raise_for_status()
            return resp.json().get("models", [])

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def chat_completion(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.1,
        token_budget: int | None = None,
    ) -> dict:
        if token_budget is not None:
            if count_tokens(messages) > token_budget:
                messages = trim_messages_to_budget(messages, token_budget)

        async with get_llm_semaphore():
            try:
                if self.engine == "vllm":
                    model = model or os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-Coder-32B-Instruct")
                    resp = await self._client.post(
                        "/v1/chat/completions",
                        json={
                            "model": model,
                            "messages": messages,
                            "temperature": temperature,
                        },
                    )
                else:
                    model = model or os.getenv("OLLAMA_MODEL", "qwen2.5-coder:32b")
                    resp = await self._client.post(
                        "/api/chat",
                        json={
                            "model": model,
                            "messages": messages,
                            "stream": False,
                            "options": {"temperature": temperature},
                        },
                    )
                resp.raise_for_status()
            except httpx.TransportError as e:
                logger.error("LLM transport error (will retry): {}", e)
                raise
            except Exception as e:
                logger.error("LLM request error: {}", e)
                raise

        data = resp.json()
        # Normalize to OpenAI-compatible format
        if self.engine == "vllm":
            return data
        else:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": data.get("message", {}).get("content", ""),
                        }
                    }
                ]
            }
