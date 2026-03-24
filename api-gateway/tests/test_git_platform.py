"""Tests for git platform clients."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from gateway.services.git_platform import (
    GiteaClient,
    GitLabClient,
    _finalize_file,
    _parse_unified_diff,
    create_git_client,
)


def make_response(status_code: int, json_data):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


@pytest.mark.asyncio
async def test_gitea_get_review_comments_returns_normalized():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 42, "owner": "myorg", "repo_name": "myrepo"}

    client._client.get.side_effect = [
        # reviews endpoint
        make_response(200, [
            {"id": 1, "body": "Looks good", "user": {"login": "reviewer"}, "submitted_at": "2024-01-01T00:00:00Z"}
        ]),
        # issue comments endpoint
        make_response(200, [
            {"id": 2, "body": "Please fix this", "user": {"login": "author"}, "created": "2024-01-02T00:00:00Z"}
        ]),
    ]

    comments = await client.get_review_comments(pr)

    assert len(comments) == 2
    assert comments[0]["body"] == "Looks good"
    assert comments[0]["author"] == "reviewer"
    assert comments[1]["body"] == "Please fix this"
    assert comments[1]["author"] == "author"


@pytest.mark.asyncio
async def test_gitea_get_review_comments_missing_context():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 42}  # no owner/repo_name

    comments = await client.get_review_comments(pr)

    assert comments == []
    client._client.get.assert_not_called()


@pytest.mark.asyncio
async def test_gitea_get_review_comments_api_error():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 42, "owner": "myorg", "repo_name": "myrepo"}

    client._client.get.side_effect = [
        make_response(404, {}),
        make_response(404, {}),
    ]

    comments = await client.get_review_comments(pr)
    assert comments == []


@pytest.mark.asyncio
async def test_gitea_list_merge_requests_includes_owner_repo_name():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    client._client.get.side_effect = [
        # repos/search
        make_response(200, {"data": [{"owner": {"login": "myorg"}, "name": "myrepo"}]}),
        # pulls
        make_response(200, [
            {
                "number": 7,
                "title": "My PR",
                "user": {"login": "alice"},
                "state": "open",
                "html_url": "http://gitea.example.com/myorg/myrepo/pulls/7",
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]),
    ]

    prs = await client.list_merge_requests(limit=10)

    assert len(prs) == 1
    pr = prs[0]
    assert pr["owner"] == "myorg"
    assert pr["repo_name"] == "myrepo"
    assert pr["repo"] == "myorg/myrepo"
    assert pr["id"] == 7


@pytest.mark.asyncio
async def test_gitlab_get_review_comments_uses_project_id():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": 99}

    client._client.get.return_value = make_response(200, [
        {"id": 1, "body": "Nice work", "author": {"username": "bob"}, "created_at": "2024-01-01T00:00:00Z"}
    ])

    comments = await client.get_review_comments(mr)

    assert len(comments) == 1
    assert comments[0]["body"] == "Nice work"
    client._client.get.assert_called_once_with(
        "/api/v4/projects/99/merge_requests/5/notes"
    )


# ---------------------------------------------------------------------------
# _parse_unified_diff
# ---------------------------------------------------------------------------


def test_parse_unified_diff_basic():
    diff_text = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,3 +1,4 @@\n"
        " import os\n"
        "+import sys\n"
        " \n"
        " def main():\n"
    )
    files = _parse_unified_diff(diff_text)
    assert len(files) == 1
    assert files[0]["filename"] == "src/main.py"
    assert files[0]["status"] == "modified"
    assert files[0]["additions"] == 1
    assert files[0]["deletions"] == 0


def test_parse_unified_diff_new_file():
    diff_text = (
        "diff --git a/newfile.py b/newfile.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/newfile.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+line1\n"
        "+line2\n"
    )
    files = _parse_unified_diff(diff_text)
    assert len(files) == 1
    assert files[0]["status"] == "added"
    assert files[0]["additions"] == 2


def test_parse_unified_diff_deleted_file():
    """Deleted files have +++ /dev/null, so filename is empty and filtered out."""
    diff_text = (
        "diff --git a/old.py b/old.py\n"
        "deleted file mode 100644\n"
        "--- a/old.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-line1\n"
        "-line2\n"
    )
    files = _parse_unified_diff(diff_text)
    # Deleted files end up with empty filename (no +++ b/...) and get filtered
    assert len(files) == 0


def test_parse_unified_diff_deleted_file_status():
    """Verify the deleted status is set via 'deleted file mode' line."""
    diff_text = (
        "diff --git a/old.py b/old.py\n"
        "deleted file mode 100644\n"
        "--- a/old.py\n"
        "+++ b/old.py\n"
        "@@ -1,2 +0,0 @@\n"
        "-line1\n"
        "-line2\n"
    )
    files = _parse_unified_diff(diff_text)
    assert len(files) == 1
    assert files[0]["status"] == "deleted"
    assert files[0]["deletions"] == 2


def test_parse_unified_diff_multiple_files():
    diff_text = (
        "diff --git a/a.py b/a.py\n"
        "+++ b/a.py\n"
        "+added\n"
        "diff --git a/b.py b/b.py\n"
        "+++ b/b.py\n"
        "-removed\n"
    )
    files = _parse_unified_diff(diff_text)
    assert len(files) == 2
    assert files[0]["filename"] == "a.py"
    assert files[1]["filename"] == "b.py"


def test_parse_unified_diff_empty():
    files = _parse_unified_diff("")
    assert files == []


def test_parse_unified_diff_no_filename():
    """Files without +++ b/ line should be filtered out (empty filename)."""
    diff_text = "diff --git a/x b/x\nsome random line\n"
    files = _parse_unified_diff(diff_text)
    assert files == []


# ---------------------------------------------------------------------------
# _finalize_file
# ---------------------------------------------------------------------------


def test_finalize_file():
    f = {"filename": "test.py", "status": "modified", "additions": 0, "deletions": 0, "patch": ""}
    lines = ["+added line", "--- a/test.py", "+++ b/test.py", "-removed line", " context"]
    _finalize_file(f, lines)
    assert f["additions"] == 1
    assert f["deletions"] == 1
    assert "+added line" in f["patch"]


# ---------------------------------------------------------------------------
# GitLabClient.get_diff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitlab_get_diff_success():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    diff_items = [
        {
            "new_file": True,
            "deleted_file": False,
            "renamed_file": False,
            "new_path": "src/new.py",
            "old_path": "src/new.py",
            "diff": "+new line\n",
        }
    ]
    client._client.get.return_value = make_response(200, diff_items)

    files = await client.get_diff(mr)
    assert len(files) == 1
    assert files[0]["status"] == "added"
    assert files[0]["filename"] == "src/new.py"
    assert files[0]["additions"] == 1


@pytest.mark.asyncio
async def test_gitlab_get_diff_deleted_file():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    diff_items = [
        {
            "new_file": False,
            "deleted_file": True,
            "renamed_file": False,
            "new_path": "",
            "old_path": "src/old.py",
            "diff": "-old line\n",
        }
    ]
    client._client.get.return_value = make_response(200, diff_items)

    files = await client.get_diff(mr)
    assert len(files) == 1
    assert files[0]["status"] == "deleted"
    assert files[0]["filename"] == "src/old.py"


@pytest.mark.asyncio
async def test_gitlab_get_diff_renamed_file():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    diff_items = [
        {
            "new_file": False,
            "deleted_file": False,
            "renamed_file": True,
            "new_path": "src/renamed.py",
            "old_path": "src/original.py",
            "diff": "",
        }
    ]
    client._client.get.return_value = make_response(200, diff_items)

    files = await client.get_diff(mr)
    assert len(files) == 1
    assert files[0]["status"] == "renamed"


@pytest.mark.asyncio
async def test_gitlab_get_diff_modified_file():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    diff_items = [
        {
            "new_file": False,
            "deleted_file": False,
            "renamed_file": False,
            "new_path": "src/mod.py",
            "old_path": "src/mod.py",
            "diff": "+added\n-removed\n",
        }
    ]
    client._client.get.return_value = make_response(200, diff_items)

    files = await client.get_diff(mr)
    assert files[0]["status"] == "modified"
    assert files[0]["additions"] == 1
    assert files[0]["deletions"] == 1


@pytest.mark.asyncio
async def test_gitlab_get_diff_http_error():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    client._client.get.return_value = make_response(500, {})

    files = await client.get_diff(mr)
    assert files == []


@pytest.mark.asyncio
async def test_gitlab_get_diff_empty_response():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    client._client.get.return_value = make_response(200, [])

    files = await client.get_diff(mr)
    assert files == []


@pytest.mark.asyncio
async def test_gitlab_get_diff_pagination():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}

    # First page: 100 items (full page), second page: 1 item (partial)
    page1 = [
        {"new_file": False, "deleted_file": False, "renamed_file": False,
         "new_path": f"file{i}.py", "old_path": f"file{i}.py", "diff": "+x\n"}
        for i in range(100)
    ]
    page2 = [
        {"new_file": False, "deleted_file": False, "renamed_file": False,
         "new_path": "last.py", "old_path": "last.py", "diff": "+y\n"}
    ]
    client._client.get.side_effect = [
        make_response(200, page1),
        make_response(200, page2),
    ]

    files = await client.get_diff(mr)
    assert len(files) == 101


@pytest.mark.asyncio
async def test_gitlab_get_diff_non_list_response():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    client._client.get.return_value = make_response(200, {"error": "unexpected"})

    files = await client.get_diff(mr)
    assert files == []


# ---------------------------------------------------------------------------
# GitLabClient.post_comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitlab_post_comment_success():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    resp = make_response(201, {})
    resp.raise_for_status = MagicMock()
    client._client.post.return_value = resp

    await client.post_comment(mr, "Great work!")
    client._client.post.assert_awaited_once_with(
        "/api/v4/projects/99/merge_requests/5/notes",
        json={"body": "Great work!"},
    )


@pytest.mark.asyncio
async def test_gitlab_post_comment_failure():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    resp = make_response(403, {})
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "403", request=MagicMock(), response=MagicMock()
    )
    client._client.post.return_value = resp

    with pytest.raises(httpx.HTTPStatusError):
        await client.post_comment(mr, "comment")


# ---------------------------------------------------------------------------
# GitLabClient.get_head_sha
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitlab_get_head_sha():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    resp = make_response(200, {"sha": "abc1234"})
    resp.raise_for_status = MagicMock()
    client._client.get.return_value = resp

    sha = await client.get_head_sha(mr)
    assert sha == "abc1234"
    client._client.get.assert_awaited_once_with(
        "/api/v4/projects/99/merge_requests/5"
    )


@pytest.mark.asyncio
async def test_gitlab_get_head_sha_missing():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    resp = make_response(200, {})
    resp.raise_for_status = MagicMock()
    client._client.get.return_value = resp

    sha = await client.get_head_sha(mr)
    assert sha == ""


# ---------------------------------------------------------------------------
# GitLabClient.list_merge_requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitlab_list_merge_requests():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    resp_data = [
        {
            "iid": 10,
            "project_id": 42,
            "title": "Fix bug",
            "author": {"username": "alice"},
            "state": "merged",
            "web_url": "http://gitlab.example.com/mr/10",
            "created_at": "2024-06-01T00:00:00Z",
        }
    ]
    resp = make_response(200, resp_data)
    resp.raise_for_status = MagicMock()
    client._client.get.return_value = resp

    mrs = await client.list_merge_requests(limit=20, offset=0)
    assert len(mrs) == 1
    assert mrs[0]["id"] == 10
    assert mrs[0]["project_id"] == "42"
    assert mrs[0]["author"] == "alice"


# ---------------------------------------------------------------------------
# GitLabClient.get_review_comments without project_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitlab_get_review_comments_no_project_id():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5}  # no project_id
    client._client.get.return_value = make_response(200, [
        {"id": 1, "body": "Note", "author": {"username": "bob"}, "created_at": "2024-01-01"}
    ])

    comments = await client.get_review_comments(mr)
    assert len(comments) == 1
    client._client.get.assert_called_once_with(
        "/api/v4/merge_requests/5/notes"
    )


@pytest.mark.asyncio
async def test_gitlab_get_review_comments_error():
    client = GitLabClient("http://gitlab.example.com", "token123")
    client._client = AsyncMock()

    mr = {"id": 5, "project_id": "99"}
    client._client.get.return_value = make_response(500, {})

    comments = await client.get_review_comments(mr)
    assert comments == []


# ---------------------------------------------------------------------------
# GiteaClient.get_diff — /files success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitea_get_diff_files_endpoint():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 7, "owner": "myorg", "repo_name": "myrepo"}
    files_data = [
        {
            "filename": "src/app.py",
            "status": "modified",
            "additions": 3,
            "deletions": 1,
            "patch": "+added\n-removed\n",
        }
    ]
    client._client.get.return_value = make_response(200, files_data)

    files = await client.get_diff(pr)
    assert len(files) == 1
    assert files[0]["filename"] == "src/app.py"
    assert files[0]["additions"] == 3


# ---------------------------------------------------------------------------
# GiteaClient.get_diff — fallback to raw diff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitea_get_diff_fallback():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 7, "owner": "myorg", "repo_name": "myrepo"}

    diff_text = (
        "diff --git a/main.py b/main.py\n"
        "+++ b/main.py\n"
        "+new line\n"
    )
    files_resp = make_response(404, {})
    pr_resp = make_response(200, {
        "base": {"sha": "aaa"},
        "head": {"sha": "bbb"},
    })
    diff_resp = make_response(200, {})
    diff_resp.text = diff_text
    diff_resp.status_code = 200

    client._client.get.side_effect = [files_resp, pr_resp, diff_resp]

    files = await client.get_diff(pr)
    assert len(files) == 1
    assert files[0]["filename"] == "main.py"


@pytest.mark.asyncio
async def test_gitea_get_diff_fallback_pr_metadata_fail():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 7, "owner": "myorg", "repo_name": "myrepo"}
    client._client.get.side_effect = [
        make_response(404, {}),  # /files
        make_response(500, {}),  # PR metadata
    ]

    files = await client.get_diff(pr)
    assert files == []


@pytest.mark.asyncio
async def test_gitea_get_diff_fallback_no_shas():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 7, "owner": "myorg", "repo_name": "myrepo"}
    client._client.get.side_effect = [
        make_response(404, {}),  # /files
        make_response(200, {"base": {}, "head": {}}),  # PR metadata, no shas
    ]

    files = await client.get_diff(pr)
    assert files == []


@pytest.mark.asyncio
async def test_gitea_get_diff_fallback_diff_api_error():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 7, "owner": "myorg", "repo_name": "myrepo"}
    client._client.get.side_effect = [
        make_response(404, {}),  # /files
        make_response(200, {"base": {"sha": "aaa"}, "head": {"sha": "bbb"}}),
        make_response(500, {}),  # diff endpoint
    ]

    files = await client.get_diff(pr)
    assert files == []


@pytest.mark.asyncio
async def test_gitea_get_diff_transport_error():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 7, "owner": "myorg", "repo_name": "myrepo"}
    client._client.get.side_effect = httpx.TransportError("connection reset")

    files = await client.get_diff(pr)
    assert files == []


# ---------------------------------------------------------------------------
# GiteaClient.post_comment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitea_post_comment_success():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 7, "owner": "myorg", "repo_name": "myrepo"}
    resp = make_response(201, {})
    resp.raise_for_status = MagicMock()
    client._client.post.return_value = resp

    await client.post_comment(pr, "Comment body")
    client._client.post.assert_awaited_once_with(
        "/api/v1/repos/myorg/myrepo/issues/7/comments",
        json={"body": "Comment body"},
    )


@pytest.mark.asyncio
async def test_gitea_post_comment_failure():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 7, "owner": "myorg", "repo_name": "myrepo"}
    resp = make_response(403, {})
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "403", request=MagicMock(), response=MagicMock()
    )
    client._client.post.return_value = resp

    with pytest.raises(httpx.HTTPStatusError):
        await client.post_comment(pr, "comment")


# ---------------------------------------------------------------------------
# GiteaClient.get_head_sha
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitea_get_head_sha():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 7, "owner": "myorg", "repo_name": "myrepo"}
    resp = make_response(200, {"head": {"sha": "def5678"}})
    resp.raise_for_status = MagicMock()
    client._client.get.return_value = resp

    sha = await client.get_head_sha(pr)
    assert sha == "def5678"


@pytest.mark.asyncio
async def test_gitea_get_head_sha_missing():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    pr = {"id": 7, "owner": "myorg", "repo_name": "myrepo"}
    resp = make_response(200, {})
    resp.raise_for_status = MagicMock()
    client._client.get.return_value = resp

    sha = await client.get_head_sha(pr)
    assert sha == ""


# ---------------------------------------------------------------------------
# GiteaClient.list_merge_requests — pulls API error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitea_list_merge_requests_pulls_error():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    client._client.get.side_effect = [
        make_response(200, {"data": [{"owner": {"login": "org"}, "name": "repo"}]}),
        make_response(500, []),  # pulls endpoint fails
    ]

    prs = await client.list_merge_requests(limit=10)
    assert prs == []


# ---------------------------------------------------------------------------
# create_git_client factory
# ---------------------------------------------------------------------------


def test_create_git_client_gitlab():
    with patch.dict("os.environ", {"GIT_PLATFORM": "gitlab", "GIT_BASE_URL": "http://gitlab:3000", "GIT_TOKEN": "tok"}):
        client = create_git_client()
        assert isinstance(client, GitLabClient)


def test_create_git_client_gitea():
    with patch.dict("os.environ", {"GIT_PLATFORM": "gitea", "GIT_BASE_URL": "http://gitea:3000", "GIT_TOKEN": "tok"}):
        client = create_git_client()
        assert isinstance(client, GiteaClient)


def test_create_git_client_default_is_gitlab():
    with patch.dict("os.environ", {"GIT_PLATFORM": "unknown", "GIT_BASE_URL": "http://x", "GIT_TOKEN": "tok"}):
        client = create_git_client()
        assert isinstance(client, GitLabClient)


# ---------------------------------------------------------------------------
# GitClient base class — __aenter__ / __aexit__
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_git_client_aenter_aexit():
    client = GitLabClient("http://gitlab.example.com", "tok")
    async with client:
        assert client._client is not None


@pytest.mark.asyncio
async def test_git_client_aexit_no_client():
    client = GitLabClient("http://gitlab.example.com", "tok")
    client._client = None
    await client.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# GitLabClient._auth_headers / GiteaClient._auth_headers
# ---------------------------------------------------------------------------


def test_gitlab_auth_headers():
    client = GitLabClient("http://gitlab.example.com", "mytoken")
    assert client._auth_headers() == {"PRIVATE-TOKEN": "mytoken"}


def test_gitea_auth_headers():
    client = GiteaClient("http://gitea.example.com", "mytoken")
    assert client._auth_headers() == {"Authorization": "token mytoken"}


# ---------------------------------------------------------------------------
# GitClient warning on empty token
# ---------------------------------------------------------------------------


def test_git_client_empty_token_logs_warning():
    # Should not raise, just log warning
    client = GitLabClient("http://gitlab.example.com", "")
    assert client.token == ""


# ---------------------------------------------------------------------------
# GiteaClient.list_merge_requests with offset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitea_list_merge_requests_with_offset():
    client = GiteaClient("http://gitea.example.com", "token123")
    client._client = AsyncMock()

    prs_data = [
        {
            "number": i,
            "title": f"PR {i}",
            "user": {"login": "alice"},
            "state": "open",
            "html_url": f"http://gitea/pulls/{i}",
            "created_at": "2024-01-01T00:00:00Z",
        }
        for i in range(5)
    ]
    client._client.get.side_effect = [
        make_response(200, {"data": [{"owner": {"login": "org"}, "name": "repo"}]}),
        make_response(200, prs_data),
    ]

    prs = await client.list_merge_requests(limit=2, offset=2)
    assert len(prs) == 2
    assert prs[0]["id"] == 2
    assert prs[1]["id"] == 3
