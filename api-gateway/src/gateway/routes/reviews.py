from fastapi import APIRouter, Query

from gateway.services.git_platform import create_git_client

router = APIRouter()


@router.get("/reviews")
async def get_reviews(limit: int = Query(20)):
    async with create_git_client() as client:
        mrs = await client.list_merge_requests(limit=limit)
        results = []
        for mr in mrs:
            comments = await client.get_review_comments(mr["id"])
            results.append({**mr, "review_comments": comments})
        return {"reviews": results}
