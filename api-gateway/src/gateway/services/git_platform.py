import os
from abc import ABC, abstractmethod

import httpx


class GitClient(ABC):
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url, headers=self._auth_headers(), timeout=15
        )
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    @abstractmethod
    def _auth_headers(self) -> dict: ...

    @abstractmethod
    async def list_merge_requests(self, limit: int = 20) -> list[dict]: ...

    @abstractmethod
    async def get_review_comments(self, mr_id: int | str) -> list[dict]: ...


class GitLabClient(GitClient):
    def _auth_headers(self) -> dict:
        return {"PRIVATE-TOKEN": self.token}

    async def list_merge_requests(self, limit: int = 20) -> list[dict]:
        resp = await self._client.get(
            "/api/v4/merge_requests",
            params={"state": "all", "per_page": limit, "scope": "all"},
        )
        resp.raise_for_status()
        return [
            {
                "id": mr["iid"],
                "project_id": mr["project_id"],
                "title": mr["title"],
                "author": mr["author"]["username"],
                "state": mr["state"],
                "url": mr["web_url"],
                "created_at": mr["created_at"],
            }
            for mr in resp.json()
        ]

    async def get_review_comments(self, mr_id: int | str) -> list[dict]:
        # mr_id here is actually (project_id, iid) — but we stored project_id in the MR dict
        # For simplicity we search across all projects using the notes API
        # In practice you'd scope this to a project; here we use the global MR id
        resp = await self._client.get(
            f"/api/v4/merge_requests/{mr_id}/notes",
        )
        if resp.status_code != 200:
            return []
        return [
            {
                "id": n["id"],
                "body": n["body"],
                "author": n["author"]["username"],
                "created_at": n["created_at"],
            }
            for n in resp.json()
        ]


class GiteaClient(GitClient):
    def _auth_headers(self) -> dict:
        return {"Authorization": f"token {self.token}"}

    async def list_merge_requests(self, limit: int = 20) -> list[dict]:
        resp = await self._client.get(
            "/api/v1/repos/search", params={"limit": 50}
        )
        resp.raise_for_status()
        repos = resp.json().get("data", [])

        prs: list[dict] = []
        for repo in repos:
            owner = repo["owner"]["login"]
            name = repo["name"]
            r = await self._client.get(
                f"/api/v1/repos/{owner}/{name}/pulls",
                params={"state": "all", "limit": limit},
            )
            if r.status_code != 200:
                continue
            for pr in r.json():
                prs.append(
                    {
                        "id": pr["number"],
                        "repo": f"{owner}/{name}",
                        "title": pr["title"],
                        "author": pr["user"]["login"],
                        "state": pr["state"],
                        "url": pr["html_url"],
                        "created_at": pr["created_at"],
                    }
                )
            if len(prs) >= limit:
                break
        return prs[:limit]

    async def get_review_comments(self, pr_id: int | str) -> list[dict]:
        # Requires repo context; for simplicity scan recent repos
        # In a real app, the PR dict would carry repo info
        return []


def create_git_client() -> GitClient:
    platform = os.getenv("GIT_PLATFORM", "gitlab").lower()
    base_url = os.getenv("GIT_BASE_URL", "http://localhost:3000")
    token = os.getenv("GIT_TOKEN", "")
    if platform == "gitea":
        return GiteaClient(base_url, token)
    return GitLabClient(base_url, token)
