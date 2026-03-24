import os
from abc import ABC, abstractmethod

import httpx
from loguru import logger


class GitClient(ABC):
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token
        self._client: httpx.AsyncClient | None = None
        if not token:
            logger.warning("Git token is not set; API calls may fail")

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url, headers=self._auth_headers(), timeout=30
        )
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    @abstractmethod
    def _auth_headers(self) -> dict: ...

    @abstractmethod
    async def list_merge_requests(self, limit: int = 20, offset: int = 0) -> list[dict]: ...

    @abstractmethod
    async def get_review_comments(self, mr: dict) -> list[dict]: ...

    @abstractmethod
    async def get_diff(self, mr: dict) -> list[dict]: ...

    @abstractmethod
    async def post_comment(self, mr: dict, body: str) -> None: ...

    @abstractmethod
    async def get_head_sha(self, mr: dict) -> str: ...


def _parse_unified_diff(text: str) -> list[dict]:
    """Parse a unified diff string into per-file chunks."""
    files: list[dict] = []
    current: dict | None = None
    patch_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("diff --git "):
            if current is not None:
                _finalize_file(current, patch_lines)
                files.append(current)
            current = {"filename": "", "status": "modified", "additions": 0, "deletions": 0, "patch": ""}
            patch_lines = []
        elif current is not None:
            if line.startswith("new file mode"):
                current["status"] = "added"
            elif line.startswith("deleted file mode"):
                current["status"] = "deleted"
            elif line.startswith("+++ b/"):
                current["filename"] = line[6:]
            elif line.startswith("+++ /dev/null"):
                current["status"] = "deleted"
            patch_lines.append(line)

    if current is not None:
        _finalize_file(current, patch_lines)
        files.append(current)

    return [f for f in files if f["filename"]]


def _finalize_file(file: dict, patch_lines: list[str]) -> None:
    patch = "\n".join(patch_lines)
    file["patch"] = patch
    file["additions"] = sum(
        1 for l in patch_lines if l.startswith("+") and not l.startswith("+++")
    )
    file["deletions"] = sum(
        1 for l in patch_lines if l.startswith("-") and not l.startswith("---")
    )


class GitLabClient(GitClient):
    def _auth_headers(self) -> dict:
        return {"PRIVATE-TOKEN": self.token}

    async def list_merge_requests(self, limit: int = 20, offset: int = 0) -> list[dict]:
        page = (offset // limit) + 1
        resp = await self._client.get(
            "/api/v4/merge_requests",
            params={"state": "all", "per_page": limit, "page": page, "scope": "all"},
        )
        resp.raise_for_status()
        return [
            {
                "id": mr["iid"],
                "project_id": str(mr["project_id"]),
                "title": mr["title"],
                "author": mr["author"]["username"],
                "state": mr["state"],
                "url": mr["web_url"],
                "created_at": mr["created_at"],
            }
            for mr in resp.json()
        ]

    async def get_review_comments(self, mr: dict) -> list[dict]:
        project_id = mr.get("project_id")
        mr_iid = mr.get("id")
        if project_id:
            resp = await self._client.get(
                f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes",
            )
        else:
            resp = await self._client.get(
                f"/api/v4/merge_requests/{mr_iid}/notes",
            )
        if resp.status_code != 200:
            logger.error(
                "GitLab notes API returned HTTP {} for MR {}", resp.status_code, mr_iid
            )
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

    async def get_diff(self, mr: dict) -> list[dict]:
        project_id = mr.get("project_id")
        mr_iid = mr.get("id")
        all_files: list[dict] = []
        page = 1

        while True:
            resp = await self._client.get(
                f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/diffs",
                params={"access_raw_diffs": "true", "per_page": 100, "page": page},
            )
            if resp.status_code != 200:
                logger.error(
                    "GitLab diffs API returned HTTP {} for MR {}", resp.status_code, mr_iid
                )
                break

            items = resp.json()
            if not isinstance(items, list) or not items:
                break

            for item in items:
                if item.get("new_file"):
                    status = "added"
                elif item.get("deleted_file"):
                    status = "deleted"
                elif item.get("renamed_file"):
                    status = "renamed"
                else:
                    status = "modified"

                patch = item.get("diff", "")
                patch_lines = patch.splitlines()
                additions = sum(1 for l in patch_lines if l.startswith("+") and not l.startswith("+++"))
                deletions = sum(1 for l in patch_lines if l.startswith("-") and not l.startswith("---"))

                all_files.append({
                    "filename": item.get("new_path") or item.get("old_path", ""),
                    "status": status,
                    "additions": additions,
                    "deletions": deletions,
                    "patch": patch,
                })

            if len(items) < 100:
                break
            page += 1

        return all_files

    async def post_comment(self, mr: dict, body: str) -> None:
        project_id = mr.get("project_id")
        mr_iid = mr.get("id")
        resp = await self._client.post(
            f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes",
            json={"body": body},
        )
        if resp.status_code not in (200, 201):
            logger.error(
                "GitLab post comment returned HTTP {} for MR {}", resp.status_code, mr_iid
            )
            resp.raise_for_status()

    async def get_head_sha(self, mr: dict) -> str:
        project_id = mr.get("project_id")
        mr_iid = mr.get("id")
        resp = await self._client.get(
            f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}",
        )
        resp.raise_for_status()
        return resp.json().get("sha", "")


class GiteaClient(GitClient):
    def _auth_headers(self) -> dict:
        return {"Authorization": f"token {self.token}"}

    async def list_merge_requests(self, limit: int = 20, offset: int = 0) -> list[dict]:
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
                logger.error(
                    "Gitea pulls API returned HTTP {} for {}/{}", r.status_code, owner, name
                )
                continue
            for pr in r.json():
                prs.append(
                    {
                        "id": pr["number"],
                        "repo": f"{owner}/{name}",
                        "project_id": f"{owner}/{name}",
                        "owner": owner,
                        "repo_name": name,
                        "title": pr["title"],
                        "author": pr["user"]["login"],
                        "state": pr["state"],
                        "url": pr["html_url"],
                        "created_at": pr["created_at"],
                    }
                )
            if len(prs) >= limit:
                break
        return prs[offset : offset + limit]

    async def get_review_comments(self, mr: dict) -> list[dict]:
        owner = mr.get("owner")
        repo_name = mr.get("repo_name")
        pr_id = mr.get("id")

        if not owner or not repo_name:
            logger.warning("Gitea get_review_comments called without owner/repo_name context")
            return []

        comments: list[dict] = []

        review_resp = await self._client.get(
            f"/api/v1/repos/{owner}/{repo_name}/pulls/{pr_id}/reviews"
        )
        if review_resp.status_code == 200:
            for review in review_resp.json():
                if review.get("body"):
                    comments.append(
                        {
                            "id": review["id"],
                            "body": review["body"],
                            "author": review.get("user", {}).get("login", "unknown"),
                            "created_at": review.get("submitted_at", ""),
                        }
                    )
        else:
            logger.error(
                "Gitea reviews API returned HTTP {} for {}/{} PR {}",
                review_resp.status_code,
                owner,
                repo_name,
                pr_id,
            )

        issue_resp = await self._client.get(
            f"/api/v1/repos/{owner}/{repo_name}/issues/{pr_id}/comments"
        )
        if issue_resp.status_code == 200:
            for c in issue_resp.json():
                comments.append(
                    {
                        "id": c["id"],
                        "body": c["body"],
                        "author": c.get("user", {}).get("login", "unknown"),
                        "created_at": c.get("created", ""),
                    }
                )
        else:
            logger.error(
                "Gitea issue comments API returned HTTP {} for {}/{} PR {}",
                issue_resp.status_code,
                owner,
                repo_name,
                pr_id,
            )

        return comments

    async def get_diff(self, mr: dict) -> list[dict]:
        owner = mr.get("owner")
        repo_name = mr.get("repo_name")
        pr_id = mr.get("id")

        try:
            # Try Gitea 1.20+ /files endpoint first
            resp = await self._client.get(
                f"/api/v1/repos/{owner}/{repo_name}/pulls/{pr_id}/files"
            )
            if resp.status_code == 200:
                return [
                    {
                        "filename": f.get("filename", ""),
                        "status": f.get("status", "modified"),
                        "additions": f.get("additions", 0),
                        "deletions": f.get("deletions", 0),
                        "patch": f.get("patch", ""),
                    }
                    for f in resp.json()
                ]

            # Fallback: fetch raw diff via git compare
            logger.warning(
                "Gitea /pulls/{}/files returned {}; falling back to raw diff", pr_id, resp.status_code
            )
            pr_resp = await self._client.get(
                f"/api/v1/repos/{owner}/{repo_name}/pulls/{pr_id}"
            )
            if pr_resp.status_code != 200:
                logger.error("Could not fetch PR metadata for diff fallback")
                return []

            pr_data = pr_resp.json()
            base_sha = pr_data.get("base", {}).get("sha", "")
            head_sha = pr_data.get("head", {}).get("sha", "")
            if not base_sha or not head_sha:
                return []

            diff_resp = await self._client.get(
                f"/api/v1/repos/{owner}/{repo_name}/git/diffs/{base_sha}...{head_sha}",
                headers={"Accept": "text/plain"},
            )
            if diff_resp.status_code != 200:
                logger.error("Gitea git diff API returned HTTP {}", diff_resp.status_code)
                return []

            return _parse_unified_diff(diff_resp.text)
        except httpx.TransportError as e:
            logger.error("Gitea diff request failed for {}/{} PR {}: {}", owner, repo_name, pr_id, e)
            return []

    async def post_comment(self, mr: dict, body: str) -> None:
        owner = mr.get("owner")
        repo_name = mr.get("repo_name")
        pr_id = mr.get("id")
        resp = await self._client.post(
            f"/api/v1/repos/{owner}/{repo_name}/issues/{pr_id}/comments",
            json={"body": body},
        )
        if resp.status_code not in (200, 201):
            logger.error(
                "Gitea post comment returned HTTP {} for {}/{} PR {}",
                resp.status_code,
                owner,
                repo_name,
                pr_id,
            )
            resp.raise_for_status()

    async def get_head_sha(self, mr: dict) -> str:
        owner = mr.get("owner")
        repo_name = mr.get("repo_name")
        pr_id = mr.get("id")
        resp = await self._client.get(
            f"/api/v1/repos/{owner}/{repo_name}/pulls/{pr_id}"
        )
        resp.raise_for_status()
        return resp.json().get("head", {}).get("sha", "")


def create_git_client() -> GitClient:
    platform = os.getenv("GIT_PLATFORM", "gitlab").lower()
    base_url = os.getenv("GIT_BASE_URL", "http://localhost:3000")
    token = os.getenv("GIT_TOKEN", "")
    logger.info("Creating git client: platform={} base_url={}", platform, base_url)
    if platform == "gitea":
        return GiteaClient(base_url, token)
    return GitLabClient(base_url, token)
