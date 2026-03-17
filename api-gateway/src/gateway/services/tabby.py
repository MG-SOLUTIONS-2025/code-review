import os

import httpx

TABBY_URL = os.getenv("TABBY_URL", "")


class TabbyClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._base_url = TABBY_URL

    async def __aenter__(self):
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=30)
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    async def is_healthy(self) -> bool:
        if not self._base_url:
            return False
        try:
            resp = await self._client.get("/v1/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def search_code(self, query: str, language: str | None = None, limit: int = 5) -> list[dict]:
        params = {"q": query, "limit": limit}
        if language:
            params["language"] = language
        resp = await self._client.get("/v1beta/search", params=params)
        resp.raise_for_status()
        return resp.json().get("hits", [])

    async def get_context_for_file(
        self, filepath: str, line_start: int, line_end: int
    ) -> list[dict]:
        results = await self.search_code(f"{filepath}:{line_start}-{line_end}")
        return results
