import asyncio
import os

import httpx
from fastapi import APIRouter

from gateway.services.llm import LLMClient

router = APIRouter()

DEFECTDOJO_URL = os.getenv("DEFECTDOJO_URL", "http://defectdojo-web:8080")
PR_AGENT_URL = os.getenv("PR_AGENT_URL", "http://pr-agent:3000")
TABBY_URL = os.getenv("TABBY_URL", "")


async def _check_simple(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            return {"status": "healthy" if resp.status_code < 400 else "unhealthy"}
    except Exception:
        return {"status": "unreachable"}


async def _check_llm() -> dict:
    try:
        async with LLMClient() as client:
            models = await client.list_models()
            if client.engine == "vllm":
                model_name = models[0]["id"] if models else None
            else:
                model_name = models[0]["name"] if models else None
            return {"engine": client.engine, "status": "healthy", "model": model_name}
    except Exception:
        async with LLMClient() as client:
            return {"engine": client.engine, "status": "unreachable", "model": None}


async def _check_tabby() -> dict | None:
    if not TABBY_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{TABBY_URL}/v1/health")
            return {"status": "healthy" if resp.status_code < 400 else "unhealthy"}
    except Exception:
        return {"status": "unreachable"}


@router.get("/health")
async def health():
    llm_result, pr_agent_result, defectdojo_result, tabby_result = await asyncio.gather(
        _check_llm(),
        _check_simple(f"{PR_AGENT_URL}/"),
        _check_simple(f"{DEFECTDOJO_URL}/api/v2/"),
        _check_tabby(),
    )
    services = {
        "llm": llm_result,
        "pr_agent": pr_agent_result,
        "defectdojo": defectdojo_result,
    }
    if tabby_result is not None:
        services["tabby"] = tabby_result
    all_healthy = all(s["status"] == "healthy" for s in services.values())
    return {"status": "ok" if all_healthy else "degraded", "services": services}


@router.get("/models")
async def list_models():
    async with LLMClient() as client:
        models = await client.list_models()
    return {"models": models}
