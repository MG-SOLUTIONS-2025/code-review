import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from gateway.services.git_platform import create_git_client
from gateway.services.review_pipeline import (
    ReviewPipelineError,
    _parse_review_comment,
    get_last_reviewed_sha,
    run_review,
)
from gateway.utils.auth import verify_gateway_token
from gateway.utils.sanitize import sanitize_prompt_input

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

_GIT_PLATFORM = os.getenv("GIT_PLATFORM", "gitlab").lower()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mr_dict(project_id: str, mr_id: int) -> dict:
    """Build the minimal mr dict expected by git platform methods."""
    if _GIT_PLATFORM == "gitea":
        parts = project_id.split("/", 1)
        owner = parts[0]
        repo_name = parts[1] if len(parts) > 1 else ""
        return {"id": mr_id, "owner": owner, "repo_name": repo_name, "project_id": project_id}
    return {"id": mr_id, "project_id": project_id}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class RunReviewRequest(BaseModel):
    platform: str = _GIT_PLATFORM
    project_id: str
    mr_id: int
    force: bool = False


class PostCommentRequest(BaseModel):
    platform: str = _GIT_PLATFORM
    project_id: str
    mr_id: int
    body: str


# ---------------------------------------------------------------------------
# Existing: list reviews
# ---------------------------------------------------------------------------


@router.get("/reviews")
async def get_reviews(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    try:
        async with create_git_client() as client:
            mrs = await client.list_merge_requests(limit=limit, offset=offset)
            results = []
            for mr in mrs:
                comments = await client.get_review_comments(mr)
                # Normalize project_id for Gitea (owner/repo) to match trigger API
                if _GIT_PLATFORM == "gitea" and "project_id" not in mr:
                    mr["project_id"] = f"{mr.get('owner', '')}/{mr.get('repo_name', '')}"
                results.append({**mr, "platform": _GIT_PLATFORM, "review_comments": comments})
            return {"reviews": results}
    except Exception as e:
        logger.error("Failed to fetch reviews: {}", e)
        raise HTTPException(status_code=502, detail="Failed to fetch reviews from git platform")


# ---------------------------------------------------------------------------
# New: trigger AI review
# ---------------------------------------------------------------------------


@router.post("/reviews/run")
@limiter.limit("5/minute")
async def trigger_review(
    req: RunReviewRequest,
    request: Request,
    _: None = Depends(verify_gateway_token),
):
    mr = _make_mr_dict(req.project_id, req.mr_id)
    try:
        result = await run_review(mr, force=req.force)
        return result
    except ReviewPipelineError as e:
        logger.error("Review pipeline error for project={} mr={}: {}", req.project_id, req.mr_id, e)
        raise HTTPException(status_code=502, detail=str(e))


# ---------------------------------------------------------------------------
# New: get existing review result
# ---------------------------------------------------------------------------


@router.get("/reviews/result")
async def get_review_result(
    project_id: str = Query(...),
    mr_id: int = Query(...),
):
    mr = _make_mr_dict(project_id, mr_id)
    try:
        async with create_git_client() as client:
            comments = await client.get_review_comments(mr)
        for comment in comments:
            body = comment.get("body", "")
            parsed = _parse_review_comment(body)
            if parsed:
                parsed["posted_at"] = comment.get("created_at", "")
                return parsed
        return {"head_sha": None, "files": [], "approved_count": 0, "needs_review_count": 0, "posted_at": None}
    except Exception as e:
        logger.error("Failed to fetch review result for project={} mr={}: {}", project_id, mr_id, e)
        raise HTTPException(status_code=502, detail="Failed to fetch review result")


# ---------------------------------------------------------------------------
# New: post a comment (used by autofix skill)
# ---------------------------------------------------------------------------


@router.post("/reviews/comment")
@limiter.limit("20/minute")
async def post_review_comment(
    req: PostCommentRequest,
    request: Request,
    _: None = Depends(verify_gateway_token),
):
    body = sanitize_prompt_input(req.body)
    if not body:
        raise HTTPException(status_code=422, detail="Comment body is empty after sanitization")
    mr = _make_mr_dict(req.project_id, req.mr_id)
    try:
        async with create_git_client() as client:
            await client.post_comment(mr, body)
        return {"status": "posted"}
    except Exception as e:
        logger.error("Failed to post comment for project={} mr={}: {}", req.project_id, req.mr_id, e)
        raise HTTPException(status_code=502, detail="Failed to post comment")
