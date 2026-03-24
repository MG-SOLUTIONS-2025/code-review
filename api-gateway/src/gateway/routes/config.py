import os
from pathlib import Path

import toml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from gateway.utils.ratelimit import limiter
from gateway.utils.sanitize import sanitize_prompt_input

router = APIRouter()

CONFIG_PATH = Path(
    os.getenv("PR_AGENT_CONFIG_PATH", "/app/config/pr-agent/configuration.toml")
)


class ConfigUpdate(BaseModel):
    config: dict


@router.get("/config")
async def get_config():
    if not CONFIG_PATH.exists():
        raise HTTPException(404, "Config file not found")
    return {"config": toml.loads(CONFIG_PATH.read_text())}


@router.put("/config")
@limiter.limit("10/minute")
async def put_config(body: ConfigUpdate, request: Request):
    config_data = body.config

    # Sanitize custom_instructions if present
    if "config" in config_data and "custom_instructions" in config_data["config"]:
        config_data["config"]["custom_instructions"] = sanitize_prompt_input(
            config_data["config"]["custom_instructions"]
        )

    # Validate TOML round-trip
    try:
        serialized = toml.dumps(config_data)
        toml.loads(serialized)  # Verify it parses back
    except Exception as e:
        raise HTTPException(422, f"Invalid configuration: {e}")

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(serialized)
    return {"status": "saved"}
