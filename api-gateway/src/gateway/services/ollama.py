import os

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")


class OllamaClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(base_url=OLLAMA_URL, timeout=10)
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    async def is_healthy(self) -> bool:
        try:
            resp = await self._client.get("/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        resp = await self._client.get("/api/tags")
        resp.raise_for_status()
        return resp.json().get("models", [])
