import asyncio
import os

import httpx
from fastapi import APIRouter

from gateway.services.ollama import OllamaClient

router = APIRouter()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
DEFECTDOJO_URL = os.getenv("DEFECTDOJO_URL", "http://defectdojo-web:8080")
PR_AGENT_URL = os.getenv("PR_AGENT_URL", "http://pr-agent:3000")


async def _check_simple(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            return {"status": "healthy" if resp.status_code < 400 else "unhealthy"}
    except Exception:
        return {"status": "unreachable"}


async def _check_ollama() -> dict:
    try:
        async with OllamaClient() as client:
            models = await client.list_models()
            model_name = models[0]["name"] if models else None
            return {"status": "healthy", "model": model_name}
    except Exception:
        return {"status": "unreachable", "model": None}


@router.get("/health")
async def health():
    ollama_result, pr_agent_result, defectdojo_result = await asyncio.gather(
        _check_ollama(),
        _check_simple(f"{PR_AGENT_URL}/"),
        _check_simple(f"{DEFECTDOJO_URL}/api/v2/"),
    )
    services = {
        "ollama": ollama_result,
        "pr_agent": pr_agent_result,
        "defectdojo": defectdojo_result,
    }
    all_healthy = all(s["status"] == "healthy" for s in services.values())
    return {"status": "ok" if all_healthy else "degraded", "services": services}


@router.get("/models")
async def list_models():
    async with OllamaClient() as client:
        models = await client.list_models()
    return {"models": models}
