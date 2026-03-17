import os

import httpx


class DefectDojoClient:
    def __init__(self):
        self.base_url = os.getenv("DEFECTDOJO_URL", "http://defectdojo-web:8080")
        self.token = os.getenv("DEFECTDOJO_API_TOKEN", "")
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Token {self.token}"},
            timeout=15,
        )
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    async def get_findings(
        self, limit: int = 20, offset: int = 0, severity: str | None = None
    ) -> dict:
        params: dict = {"limit": limit, "offset": offset}
        if severity:
            params["severity"] = severity
        resp = await self._client.get("/api/v2/findings/", params=params)
        resp.raise_for_status()
        return resp.json()
