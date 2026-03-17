import os
from pathlib import Path

import toml
from fastapi import APIRouter, HTTPException

router = APIRouter()

CONFIG_PATH = Path(
    os.getenv("PR_AGENT_CONFIG_PATH", "/app/config/pr-agent/configuration.toml")
)


@router.get("/config")
async def get_config():
    if not CONFIG_PATH.exists():
        raise HTTPException(404, "Config file not found")
    return {"config": toml.loads(CONFIG_PATH.read_text())}


@router.put("/config")
async def put_config(body: dict):
    config_data = body.get("config", body)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(toml.dumps(config_data))
    return {"status": "saved"}
