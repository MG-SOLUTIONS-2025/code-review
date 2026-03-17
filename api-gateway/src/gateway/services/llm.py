import os

import httpx

INFERENCE_ENGINE = os.getenv("INFERENCE_ENGINE", "ollama")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
VLLM_URL = os.getenv("VLLM_URL", "http://vllm:8000")


class LLMClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self.engine = INFERENCE_ENGINE
        self._base_url = VLLM_URL if self.engine == "vllm" else OLLAMA_URL

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

    async def chat_completion(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.1,
    ) -> dict:
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
        data = resp.json()
        # Normalize response to OpenAI-compatible format
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
