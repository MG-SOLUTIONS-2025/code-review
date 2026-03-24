import os

from fastapi import Header, HTTPException
from loguru import logger

GATEWAY_API_TOKEN = os.getenv("GATEWAY_API_TOKEN", "")

if not GATEWAY_API_TOKEN:
    logger.warning(
        "GATEWAY_API_TOKEN is not set — auth is DISABLED. "
        "Set GATEWAY_API_TOKEN in production to secure sensitive endpoints."
    )


async def verify_gateway_token(authorization: str = Header(default="")) -> None:
    """Validate bearer token on sensitive endpoints.

    If GATEWAY_API_TOKEN is not configured the check is skipped (dev mode).
    """
    if not GATEWAY_API_TOKEN:
        return
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != GATEWAY_API_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid gateway token")
