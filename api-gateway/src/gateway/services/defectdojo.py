import os

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class DefectDojoClient:
    def __init__(self):
        self.base_url = os.getenv("DEFECTDOJO_URL", "http://defectdojo-web:8081")
        self.token = os.getenv("DEFECTDOJO_API_TOKEN", "")
        self._client: httpx.AsyncClient | None = None
        if not self.token:
            logger.warning("DEFECTDOJO_API_TOKEN is not set; API calls may fail")

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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def get_findings(
        self, limit: int = 20, offset: int = 0, severity: str | None = None, scan_type: str | None = None
    ) -> dict:
        params: dict = {"limit": limit, "offset": offset}
        if severity:
            params["severity"] = severity
        if scan_type:
            params["test__test_type__name"] = scan_type
        try:
            resp = await self._client.get("/api/v2/findings/", params=params)
            if resp.status_code != 200:
                logger.error(
                    "DefectDojo API returned HTTP {} for findings request", resp.status_code
                )
            resp.raise_for_status()
        except httpx.TransportError as e:
            logger.error("DefectDojo transport error (will retry): {}", e)
            raise
        return resp.json()
