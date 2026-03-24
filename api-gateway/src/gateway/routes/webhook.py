import hashlib
import hmac
import os

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from loguru import logger

router = APIRouter()

PR_AGENT_URL = os.getenv("PR_AGENT_URL", "http://pr-agent:3000")
WEBHOOK_SECRET = os.getenv("PR_AGENT_WEBHOOK_SECRET", "")


@router.post("/webhook")
async def webhook(request: Request):
    body = await request.body()

    if WEBHOOK_SECRET:
        gitlab_token = request.headers.get("X-Gitlab-Token")
        gitea_sig = request.headers.get("X-Gitea-Signature")

        if gitlab_token is not None:
            if not hmac.compare_digest(
                WEBHOOK_SECRET.encode(), gitlab_token.encode()
            ):
                logger.warning("Webhook rejected: invalid X-Gitlab-Token")
                raise HTTPException(status_code=401, detail="Invalid webhook token")
        elif gitea_sig is not None:
            expected = hmac.new(
                WEBHOOK_SECRET.encode(), body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(expected, gitea_sig):
                logger.warning("Webhook rejected: invalid X-Gitea-Signature")
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        else:
            logger.warning("Webhook rejected: missing signature header")
            raise HTTPException(status_code=401, detail="Missing webhook signature header")

    # Proxy validated request to pr-agent
    forward_headers = {
        k: v for k, v in request.headers.items() if k.lower() != "host"
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method=request.method,
                url=f"{PR_AGENT_URL}/webhook",
                headers=forward_headers,
                content=body,
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type"),
        )
    except Exception as e:
        logger.error("Failed to proxy webhook to pr-agent: {}", e)
        raise HTTPException(status_code=502, detail="Failed to forward webhook")
