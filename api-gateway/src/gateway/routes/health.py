import asyncio
import os

import httpx
from fastapi import APIRouter
from loguru import logger

from gateway.services.llm import LLMClient

router = APIRouter()

DEFECTDOJO_URL = os.getenv("DEFECTDOJO_URL", "http://defectdojo-web:8081")
PR_AGENT_URL = os.getenv("PR_AGENT_URL", "http://pr-agent:3000")
TABBY_URL = os.getenv("TABBY_URL", "")


async def _check_simple(name: str, url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            if 200 <= resp.status_code < 300:
                return {"status": "healthy"}
            logger.warning("{} health check failed: HTTP {}", name, resp.status_code)
            return {"status": "unhealthy"}
    except httpx.TimeoutException:
        logger.error("{} health check timed out (url={})", name, url)
        return {"status": "unreachable"}
    except httpx.ConnectError:
        logger.error("{} health check connection refused (url={})", name, url)
        return {"status": "unreachable"}
    except Exception as e:
        logger.error("{} health check error: {}", name, e)
        return {"status": "unreachable"}


async def _check_llm() -> dict:
    from gateway.services.llm import INFERENCE_ENGINE
    try:
        async with LLMClient() as client:
            models = await client.list_models()
            if client.engine == "vllm":
                model_name = models[0]["id"] if models else None
            else:
                model_name = models[0]["name"] if models else None
            return {"engine": client.engine, "status": "healthy", "model": model_name}
    except httpx.TimeoutException:
        logger.error("LLM health check timed out")
    except httpx.ConnectError:
        logger.error("LLM health check connection refused")
    except Exception as e:
        logger.error("LLM health check error: {}", e)
    return {"engine": INFERENCE_ENGINE, "status": "unreachable", "model": None}


async def _check_tabby() -> dict | None:
    if not TABBY_URL:
        return None
    return await _check_simple("Tabby", f"{TABBY_URL}/v1/health")


@router.get("/health")
async def health():
    llm_result, pr_agent_result, defectdojo_result, tabby_result = await asyncio.gather(
        _check_llm(),
        _check_simple("PR-Agent", f"{PR_AGENT_URL}/"),
        _check_simple("DefectDojo", f"{DEFECTDOJO_URL}/api/v2/"),
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
