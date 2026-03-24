import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from gateway.utils.ratelimit import limiter
from gateway.utils.sanitize import sanitize_prompt_input

router = APIRouter()

PROMPTS_DIR = Path(os.getenv("PROMPTS_DIR", "/app/config/prompts"))

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_MAX_CONTENT_LEN = 50_000


class PromptUpdate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if len(v) > _MAX_CONTENT_LEN:
            raise ValueError(f"Content exceeds {_MAX_CONTENT_LEN} characters")
        return v


def _validate_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise HTTPException(422, "Prompt name must be alphanumeric (hyphens/underscores allowed)")


@router.get("/prompts")
async def list_prompts():
    if not PROMPTS_DIR.exists():
        return {"prompts": []}
    return {
        "prompts": [
            {"name": p.stem, "filename": p.name}
            for p in sorted(PROMPTS_DIR.glob("*.md"))
        ]
    }


@router.get("/prompts/{name}")
async def get_prompt(name: str):
    _validate_name(name)
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise HTTPException(404, f"Prompt '{name}' not found")
    return {"name": name, "content": path.read_text()}


@router.put("/prompts/{name}")
@limiter.limit("10/minute")
async def update_prompt(name: str, body: PromptUpdate, request: Request):
    _validate_name(name)
    sanitized_content = sanitize_prompt_input(body.content)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PROMPTS_DIR / f"{name}.md"
    path.write_text(sanitized_content)
    # Invalidate cached prompt in review pipeline
    from gateway.services.review_pipeline import _load_prompt
    _load_prompt.cache_clear()
    return {"status": "saved", "name": name}
