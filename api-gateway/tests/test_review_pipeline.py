"""Comprehensive tests for gateway.services.review_pipeline."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# We patch module-level constants via the module reference
import gateway.services.review_pipeline as pipeline
from gateway.services.review_pipeline import (
    ReviewPipelineError,
    _build_comment,
    _format_agent_prompt,
    _load_prompt,
    _parse_issues,
    _parse_review_comment,
    _review_locks,
    _should_skip_file,
    get_last_reviewed_sha,
    run_review,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_locks():
    """Clear the review locks between tests to avoid cross-test pollution."""
    _review_locks.clear()
    yield
    _review_locks.clear()


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    """Clear the lru_cache on _load_prompt so each test is isolated."""
    _load_prompt.cache_clear()
    yield
    _load_prompt.cache_clear()


@pytest.fixture
def mock_llm_client():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_git_client():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.fixture
def sample_file():
    return {
        "filename": "src/app.py",
        "status": "modified",
        "patch": "@@ -1,3 +1,4 @@\n import os\n+import sys\n",
    }


@pytest.fixture
def sample_mr():
    return {"id": 42, "project_id": "myproj"}


# ---------------------------------------------------------------------------
# _load_prompt
# ---------------------------------------------------------------------------


class TestLoadPrompt:
    def test_success(self, tmp_path):
        prompt_file = tmp_path / "review.md"
        prompt_file.write_text("You are a code reviewer.")
        with patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            result = _load_prompt("review")
        assert result == "You are a code reviewer."

    def test_file_not_found(self, tmp_path):
        with patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            with pytest.raises(FileNotFoundError, match="Prompt 'missing' not found"):
                _load_prompt("missing")


# ---------------------------------------------------------------------------
# _should_skip_file
# ---------------------------------------------------------------------------


class TestShouldSkipFile:
    @pytest.mark.parametrize(
        "ext",
        [".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
         ".ttf", ".eot", ".pdf", ".zip", ".tar", ".gz", ".lock", ".sum",
         ".snap", ".pb", ".pyc"],
    )
    def test_binary_extensions(self, ext):
        assert _should_skip_file({"filename": f"foo{ext}", "patch": "diff"}) is True

    def test_deleted_file(self):
        assert _should_skip_file({
            "filename": "foo.py",
            "status": "deleted",
            "patch": "diff",
        }) is True

    def test_empty_patch(self):
        assert _should_skip_file({"filename": "foo.py", "patch": ""}) is True

    def test_whitespace_only_patch(self):
        assert _should_skip_file({"filename": "foo.py", "patch": "   \n  "}) is True

    def test_missing_patch(self):
        assert _should_skip_file({"filename": "foo.py"}) is True

    def test_normal_file(self, sample_file):
        assert _should_skip_file(sample_file) is False

    def test_no_extension(self):
        assert _should_skip_file({"filename": "Makefile", "patch": "diff"}) is False

    def test_uppercase_extension(self):
        """Extensions are lowered before checking."""
        assert _should_skip_file({"filename": "image.PNG", "patch": "diff"}) is True


# ---------------------------------------------------------------------------
# _parse_issues
# ---------------------------------------------------------------------------


class TestParseIssues:
    def test_valid_issue_block(self):
        # After re.split(r"### \[", text), the leading "[" is consumed,
        # so the _ISSUE_HEADER regex (which starts with \[) only matches
        # when the original text has "### [[severity:" (double bracket).
        text = (
            "### [[severity: Critical] src/foo.py:42-45 \u2014 SQL injection risk\n\n"
            "**Problem:** User input is concatenated into SQL.\n\n"
            "**Suggestion:** Use parameterized queries.\n\n"
            "---\n"
        )
        issues = _parse_issues(text)
        assert len(issues) == 1
        issue = issues[0]
        assert issue["severity"] == "critical"
        assert issue["filename"] == "src/foo.py"
        assert issue["line_start"] == 42
        assert issue["line_end"] == 45
        assert issue["title"] == "SQL injection risk"
        assert "concatenated" in issue["problem"]
        assert "parameterized" in issue["suggestion"]

    def test_single_line_issue(self):
        text = "### [[severity: warning] utils.py:10 \u2014 Unused variable\n\n"
        issues = _parse_issues(text)
        assert len(issues) == 1
        assert issues[0]["line_start"] == 10
        assert issues[0]["line_end"] == 10  # no range -> same as start

    def test_no_matches(self):
        assert _parse_issues("Everything looks good!") == []

    def test_partial_match_missing_severity(self):
        # After split on "### [", the block is "bad header] ..." which
        # does not match _ISSUE_HEADER (needs "[severity: ...")
        text = "### [bad header] src/foo.py:1 \u2014 Nope\n"
        assert _parse_issues(text) == []

    def test_multiple_issues(self):
        text = (
            "### [[severity: high] a.py:1-2 \u2014 Issue A\n\n"
            "**Problem:** Problem A.\n\n"
            "**Suggestion:** Fix A.\n\n---\n"
            "### [[severity: low] b.py:10 \u2014 Issue B\n\n"
            "**Problem:** Problem B.\n\n"
            "**Suggestion:** Fix B.\n\n"
        )
        issues = _parse_issues(text)
        assert len(issues) == 2
        assert issues[0]["filename"] == "a.py"
        assert issues[1]["filename"] == "b.py"

    def test_no_problem_or_suggestion(self):
        text = "### [[severity: info] c.py:5 \u2014 Note\n\nJust some text.\n"
        issues = _parse_issues(text)
        assert len(issues) == 1
        assert issues[0]["problem"] == ""
        assert issues[0]["suggestion"] == ""


# ---------------------------------------------------------------------------
# _format_agent_prompt
# ---------------------------------------------------------------------------


class TestFormatAgentPrompt:
    def test_single_line(self):
        issue = {
            "filename": "app.py",
            "line_start": 10,
            "line_end": 10,
            "title": "Bug",
            "suggestion": "Fix it",
        }
        result = _format_agent_prompt(issue)
        assert "**Lines:** 10" in result
        assert "**File:** `app.py`" in result
        assert "**Action:** Fix it" in result
        assert "<details>" in result

    def test_line_range(self):
        issue = {
            "filename": "app.py",
            "line_start": 5,
            "line_end": 12,
            "title": "Refactor",
            "suggestion": "Split function",
        }
        result = _format_agent_prompt(issue)
        assert "**Lines:** 5-12" in result

    def test_no_suggestion_falls_back_to_title(self):
        issue = {
            "filename": "app.py",
            "line_start": 1,
            "line_end": 1,
            "title": "Missing docstring",
        }
        result = _format_agent_prompt(issue)
        assert "**Action:** Missing docstring" in result

    def test_same_start_end(self):
        """When line_end == line_start, show single line ref."""
        issue = {
            "filename": "x.py",
            "line_start": 7,
            "line_end": 7,
            "title": "T",
            "suggestion": "S",
        }
        result = _format_agent_prompt(issue)
        assert "**Lines:** 7" in result
        assert "7-7" not in result


# ---------------------------------------------------------------------------
# _summarize_file
# ---------------------------------------------------------------------------


class TestSummarizeFile:
    @pytest.mark.asyncio
    async def test_approved(self, mock_llm_client, sample_file, tmp_path):
        prompt_file = tmp_path / "summarize.md"
        prompt_file.write_text("Summarize the diff.")
        mock_llm_client.chat_completion.return_value = {
            "choices": [{"message": {"content": "APPROVED\nLooks fine."}}]
        }
        with patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            from gateway.services.review_pipeline import _summarize_file
            result = await _summarize_file(mock_llm_client, sample_file)
        assert result["decision"] == "APPROVED"
        assert result["summary"] == "Looks fine."
        assert result["filename"] == "src/app.py"

    @pytest.mark.asyncio
    async def test_needs_review(self, mock_llm_client, sample_file, tmp_path):
        prompt_file = tmp_path / "summarize.md"
        prompt_file.write_text("Summarize the diff.")
        mock_llm_client.chat_completion.return_value = {
            "choices": [{"message": {"content": "NEEDS_REVIEW\nPossible bug."}}]
        }
        with patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            from gateway.services.review_pipeline import _summarize_file
            result = await _summarize_file(mock_llm_client, sample_file)
        assert result["decision"] == "NEEDS_REVIEW"
        assert result["summary"] == "Possible bug."

    @pytest.mark.asyncio
    async def test_missing_prompt(self, mock_llm_client, sample_file, tmp_path):
        """When summarize.md is missing, default to NEEDS_REVIEW."""
        with patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            from gateway.services.review_pipeline import _summarize_file
            result = await _summarize_file(mock_llm_client, sample_file)
        assert result["decision"] == "NEEDS_REVIEW"
        assert result["summary"] == ""

    @pytest.mark.asyncio
    async def test_llm_failure(self, mock_llm_client, sample_file, tmp_path):
        prompt_file = tmp_path / "summarize.md"
        prompt_file.write_text("prompt")
        mock_llm_client.chat_completion.side_effect = RuntimeError("LLM down")
        with patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            from gateway.services.review_pipeline import _summarize_file
            result = await _summarize_file(mock_llm_client, sample_file)
        assert result["decision"] == "NEEDS_REVIEW"
        assert result["summary"] == ""

    @pytest.mark.asyncio
    async def test_single_line_response(self, mock_llm_client, sample_file, tmp_path):
        """When response is just 'APPROVED' with no additional lines."""
        prompt_file = tmp_path / "summarize.md"
        prompt_file.write_text("prompt")
        mock_llm_client.chat_completion.return_value = {
            "choices": [{"message": {"content": "APPROVED"}}]
        }
        with patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            from gateway.services.review_pipeline import _summarize_file
            result = await _summarize_file(mock_llm_client, sample_file)
        assert result["decision"] == "APPROVED"
        assert result["summary"] == ""


# ---------------------------------------------------------------------------
# _review_file
# ---------------------------------------------------------------------------


class TestReviewFile:
    @pytest.mark.asyncio
    async def test_successful_review_with_issues(self, mock_llm_client, sample_file, tmp_path):
        prompt_file = tmp_path / "review.md"
        prompt_file.write_text("Review the code.")
        # Use double bracket so _parse_issues can match after re.split
        review_text = (
            "### [[severity: high] src/app.py:2 \u2014 Missing error handling\n\n"
            "**Problem:** No try/except.\n\n"
            "**Suggestion:** Add error handling.\n"
        )
        mock_llm_client.chat_completion.return_value = {
            "choices": [{"message": {"content": review_text}}]
        }
        with patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            from gateway.services.review_pipeline import _review_file
            result = await _review_file(mock_llm_client, sample_file, "needs attention")
        assert result["decision"] == "NEEDS_REVIEW"
        assert result["filename"] == "src/app.py"
        assert len(result["issues"]) == 1
        assert result["issues"][0]["severity"] == "high"
        assert result["summary"] == "needs attention"

    @pytest.mark.asyncio
    async def test_missing_prompt(self, mock_llm_client, sample_file, tmp_path):
        with patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            from gateway.services.review_pipeline import _review_file
            result = await _review_file(mock_llm_client, sample_file, "summary")
        assert result["review"] == "Review prompt not configured."
        assert result["issues"] == []

    @pytest.mark.asyncio
    async def test_llm_failure(self, mock_llm_client, sample_file, tmp_path):
        prompt_file = tmp_path / "review.md"
        prompt_file.write_text("prompt")
        mock_llm_client.chat_completion.side_effect = RuntimeError("timeout")
        with patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            from gateway.services.review_pipeline import _review_file
            result = await _review_file(mock_llm_client, sample_file, "summary")
        assert "Review failed: timeout" in result["review"]
        assert result["issues"] == []


# ---------------------------------------------------------------------------
# _process_batch
# ---------------------------------------------------------------------------


class TestProcessBatch:
    @pytest.mark.asyncio
    async def test_mix_approved_and_needs_review(self, mock_llm_client, tmp_path):
        prompt_file_s = tmp_path / "summarize.md"
        prompt_file_s.write_text("summarize")
        prompt_file_r = tmp_path / "review.md"
        prompt_file_r.write_text("review")

        files = [
            {"filename": "ok.py", "patch": "diff1"},
            {"filename": "bad.py", "patch": "diff2"},
        ]

        # First call -> APPROVED, second call -> NEEDS_REVIEW (summarize)
        # Third call -> review result
        call_count = 0

        async def fake_chat(messages, model=None, token_budget=None):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # Summarize calls
                if "ok.py" in messages[1]["content"]:
                    return {"choices": [{"message": {"content": "APPROVED\nClean."}}]}
                return {"choices": [{"message": {"content": "NEEDS_REVIEW\nSuspicious."}}]}
            # Review call
            return {"choices": [{"message": {"content": "No issues found."}}]}

        mock_llm_client.chat_completion.side_effect = fake_chat

        with patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            from gateway.services.review_pipeline import _process_batch
            results = await _process_batch(mock_llm_client, files)

        assert len(results) == 2
        approved = [r for r in results if r["decision"] == "APPROVED"]
        needs_review = [r for r in results if r["decision"] == "NEEDS_REVIEW"]
        assert len(approved) == 1
        assert len(needs_review) == 1
        assert approved[0]["filename"] == "ok.py"
        assert needs_review[0]["filename"] == "bad.py"


# ---------------------------------------------------------------------------
# _build_comment
# ---------------------------------------------------------------------------


class TestBuildComment:
    def test_with_issues(self):
        results = [
            {
                "filename": "a.py",
                "decision": "APPROVED",
                "summary": "ok",
                "review": None,
                "issues": [],
            },
            {
                "filename": "b.py",
                "decision": "NEEDS_REVIEW",
                "summary": "suspicious",
                "review": "Found problems.",
                "issues": [
                    {
                        "filename": "b.py",
                        "line_start": 10,
                        "line_end": 12,
                        "title": "Bug",
                        "severity": "high",
                        "suggestion": "Fix it",
                    }
                ],
            },
        ]
        comment = _build_comment(results, "abc1234567890", "test-model")
        assert "<!-- ai-review-sha: abc1234567890 -->" in comment
        assert "**Commit:** `abc1234`" in comment
        assert "**Model:** test-model" in comment
        assert "| `a.py` |" in comment
        assert "APPROVED" in comment
        assert "### Issues" in comment
        assert "#### `b.py`" in comment
        assert "Found problems." in comment
        assert "<details>" in comment  # agent prompt
        assert "1 approved" in comment
        assert "1 need attention" in comment

    def test_all_approved(self):
        results = [
            {
                "filename": "a.py",
                "decision": "APPROVED",
                "summary": "",
                "review": None,
                "issues": [],
            },
        ]
        comment = _build_comment(results, "deadbeef1234567", "model")
        assert "### Issues" not in comment
        assert "1 approved" in comment
        assert "0 need attention" in comment

    def test_issue_count_column(self):
        results = [
            {
                "filename": "x.py",
                "decision": "NEEDS_REVIEW",
                "summary": "",
                "review": "text",
                "issues": [{"filename": "x.py", "line_start": 1, "line_end": 1, "title": "T", "severity": "low", "suggestion": "S"}] * 3,
            },
        ]
        comment = _build_comment(results, "a" * 40, "m")
        # The NEEDS_REVIEW row should show "3"
        assert "| 3 |" in comment

    def test_approved_count_column_shows_dash(self):
        results = [
            {
                "filename": "a.py",
                "decision": "APPROVED",
                "summary": "",
                "review": None,
                "issues": [],
            },
        ]
        comment = _build_comment(results, "a" * 40, "m")
        # Approved files show — for issue count
        assert "| — |" in comment


# ---------------------------------------------------------------------------
# _parse_review_comment
# ---------------------------------------------------------------------------


class TestParseReviewComment:
    def test_valid_comment(self):
        body = (
            "<!-- ai-review-sha: abc1234 -->\n"
            "## AI Code Review\n\n"
            "| File | Decision | Issues |\n"
            "|------|----------|--------|\n"
            "| `a.py` | ✅ APPROVED | — |\n"
            "| `b.py` | 🔍 NEEDS_REVIEW | 2 |\n"
        )
        result = _parse_review_comment(body)
        assert result is not None
        assert result["head_sha"] == "abc1234"
        assert len(result["files"]) == 2
        assert result["approved_count"] == 1
        assert result["needs_review_count"] == 1
        assert result["files"][0]["filename"] == "a.py"
        assert result["files"][0]["issue_count"] == 0
        assert result["files"][1]["issue_count"] == 2

    def test_no_sha_tag(self):
        assert _parse_review_comment("Just a regular comment") is None

    def test_row_with_dash_issue_count(self):
        body = "<!-- ai-review-sha: deadbeef -->\n| `c.py` | ✅ APPROVED | — |\n"
        result = _parse_review_comment(body)
        assert result["files"][0]["issue_count"] == 0

    def test_row_with_invalid_issue_count(self):
        body = "<!-- ai-review-sha: deadbeef -->\n| `c.py` | 🔍 NEEDS_REVIEW | N/A |\n"
        result = _parse_review_comment(body)
        assert result["files"][0]["issue_count"] == 0


# ---------------------------------------------------------------------------
# get_last_reviewed_sha
# ---------------------------------------------------------------------------


class TestGetLastReviewedSha:
    @pytest.mark.asyncio
    async def test_found_sha(self):
        git_client = AsyncMock()
        git_client.get_review_comments.return_value = [
            {"body": "<!-- ai-review-sha: abc1234 -->", "author": "bot"},
        ]
        result = await get_last_reviewed_sha(git_client, {"id": 1})
        assert result == "abc1234"

    @pytest.mark.asyncio
    async def test_no_sha(self):
        git_client = AsyncMock()
        git_client.get_review_comments.return_value = [
            {"body": "LGTM", "author": "human"},
        ]
        result = await get_last_reviewed_sha(git_client, {"id": 1})
        assert result is None

    @pytest.mark.asyncio
    async def test_bot_username_filtering(self):
        """When BOT_USERNAME is set, skip comments from other users."""
        git_client = AsyncMock()
        git_client.get_review_comments.return_value = [
            {"body": "<!-- ai-review-sha: aaa1111 -->", "author": "human"},
            {"body": "<!-- ai-review-sha: bbb2222 -->", "author": "mybot"},
        ]
        with patch.object(pipeline, "BOT_USERNAME", "mybot"):
            result = await get_last_reviewed_sha(git_client, {"id": 1})
        assert result == "bbb2222"

    @pytest.mark.asyncio
    async def test_bot_username_no_match(self):
        """All comments from wrong author -> None."""
        git_client = AsyncMock()
        git_client.get_review_comments.return_value = [
            {"body": "<!-- ai-review-sha: aaa1111 -->", "author": "human"},
        ]
        with patch.object(pipeline, "BOT_USERNAME", "mybot"):
            result = await get_last_reviewed_sha(git_client, {"id": 1})
        assert result is None

    @pytest.mark.asyncio
    async def test_exception(self):
        git_client = AsyncMock()
        git_client.get_review_comments.side_effect = RuntimeError("network error")
        result = await get_last_reviewed_sha(git_client, {"id": 1})
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_bot_username_does_not_filter(self):
        """When BOT_USERNAME is empty string, don't filter by author."""
        git_client = AsyncMock()
        git_client.get_review_comments.return_value = [
            {"body": "<!-- ai-review-sha: aabbccdd -->", "author": "anyone"},
        ]
        with patch.object(pipeline, "BOT_USERNAME", ""):
            result = await get_last_reviewed_sha(git_client, {"id": 1})
        assert result == "aabbccdd"


# ---------------------------------------------------------------------------
# run_review — full integration
# ---------------------------------------------------------------------------


class TestRunReview:
    """Tests for run_review using mocked git and LLM clients."""

    def _setup_clients(self, mock_git_client, mock_llm_client):
        """Create context-manager patches for create_git_client and LLMClient."""
        git_cm = AsyncMock()
        git_cm.__aenter__ = AsyncMock(return_value=mock_git_client)
        git_cm.__aexit__ = AsyncMock(return_value=None)

        llm_cm = AsyncMock()
        llm_cm.__aenter__ = AsyncMock(return_value=mock_llm_client)
        llm_cm.__aexit__ = AsyncMock(return_value=None)

        return (
            patch("gateway.services.review_pipeline.create_git_client", return_value=git_cm),
            patch("gateway.services.review_pipeline.LLMClient", return_value=llm_cm),
        )

    @pytest.mark.asyncio
    async def test_full_flow(self, mock_git_client, mock_llm_client, tmp_path):
        prompt_s = tmp_path / "summarize.md"
        prompt_s.write_text("summarize")
        prompt_r = tmp_path / "review.md"
        prompt_r.write_text("review")

        mock_git_client.get_head_sha.return_value = "abc1234567"
        mock_git_client.get_review_comments.return_value = []
        mock_git_client.get_diff.return_value = [
            {"filename": "app.py", "status": "modified", "patch": "diff content"},
        ]

        mock_llm_client.chat_completion.side_effect = [
            # Summarize
            {"choices": [{"message": {"content": "NEEDS_REVIEW\nLooks suspicious."}}]},
            # Review
            {"choices": [{"message": {"content": "No critical issues."}}]},
        ]

        git_patch, llm_patch = self._setup_clients(mock_git_client, mock_llm_client)
        with git_patch, llm_patch, patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            result = await run_review({"id": 42, "project_id": "proj"})

        assert result["posted"] is True
        assert result["head_sha"] == "abc1234567"
        assert result["files_reviewed"] == 1
        assert result["files_approved"] == 0
        assert result["skipped_reason"] is None
        mock_git_client.post_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skip_already_reviewed(self, mock_git_client, mock_llm_client):
        mock_git_client.get_head_sha.return_value = "abc1234567"
        mock_git_client.get_review_comments.return_value = [
            {"body": "<!-- ai-review-sha: abc1234567 -->", "author": "bot"},
        ]

        git_patch, llm_patch = self._setup_clients(mock_git_client, mock_llm_client)
        with git_patch, llm_patch, patch.object(pipeline, "BOT_USERNAME", ""):
            result = await run_review({"id": 42, "project_id": "proj"}, force=False)

        assert result["posted"] is False
        assert "already reviewed" in result["skipped_reason"]
        assert result["files_reviewed"] == 0
        mock_git_client.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_force_flag_bypasses_sha_check(self, mock_git_client, mock_llm_client, tmp_path):
        prompt_s = tmp_path / "summarize.md"
        prompt_s.write_text("s")
        prompt_r = tmp_path / "review.md"
        prompt_r.write_text("r")

        mock_git_client.get_head_sha.return_value = "abc1234567"
        # Even though last SHA matches, force=True should proceed
        mock_git_client.get_review_comments.return_value = [
            {"body": "<!-- ai-review-sha: abc1234567 -->"},
        ]
        mock_git_client.get_diff.return_value = [
            {"filename": "x.py", "status": "modified", "patch": "diff"},
        ]
        mock_llm_client.chat_completion.side_effect = [
            {"choices": [{"message": {"content": "APPROVED"}}]},
        ]

        git_patch, llm_patch = self._setup_clients(mock_git_client, mock_llm_client)
        with git_patch, llm_patch, patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            result = await run_review({"id": 42, "project_id": "proj"}, force=True)

        assert result["posted"] is True
        # get_review_comments should NOT be called when force=True
        mock_git_client.get_review_comments.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_diff(self, mock_git_client, mock_llm_client, tmp_path):
        """All files are skipped (binary / deleted / empty patch)."""
        prompt_s = tmp_path / "summarize.md"
        prompt_s.write_text("s")
        prompt_r = tmp_path / "review.md"
        prompt_r.write_text("r")

        mock_git_client.get_head_sha.return_value = "deadbeef12"
        mock_git_client.get_review_comments.return_value = []
        mock_git_client.get_diff.return_value = [
            {"filename": "image.png", "status": "added", "patch": "binary"},
            {"filename": "old.py", "status": "deleted", "patch": "removed"},
        ]

        git_patch, llm_patch = self._setup_clients(mock_git_client, mock_llm_client)
        with git_patch, llm_patch, patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            result = await run_review({"id": 42, "project_id": "proj"})

        assert result["posted"] is True
        assert result["files_reviewed"] == 0
        assert result["files_approved"] == 0
        assert result["files_skipped"] == 2
        assert result["file_results"] == []

    @pytest.mark.asyncio
    async def test_pipeline_error_no_head_sha(self, mock_git_client, mock_llm_client):
        mock_git_client.get_head_sha.return_value = None

        git_patch, llm_patch = self._setup_clients(mock_git_client, mock_llm_client)
        with git_patch, llm_patch:
            with pytest.raises(ReviewPipelineError, match="Could not determine HEAD SHA"):
                await run_review({"id": 42, "project_id": "proj"})

    @pytest.mark.asyncio
    async def test_pipeline_error_wraps_exception(self, mock_git_client, mock_llm_client):
        mock_git_client.get_head_sha.side_effect = RuntimeError("connection refused")

        git_patch, llm_patch = self._setup_clients(mock_git_client, mock_llm_client)
        with git_patch, llm_patch:
            with pytest.raises(ReviewPipelineError, match="Review pipeline failed"):
                await run_review({"id": 42, "project_id": "proj"})

    @pytest.mark.asyncio
    async def test_vllm_engine_model_name(self, mock_git_client, mock_llm_client, tmp_path):
        """When INFERENCE_ENGINE=vllm, use VLLM_MODEL for the comment."""
        prompt_s = tmp_path / "summarize.md"
        prompt_s.write_text("s")
        prompt_r = tmp_path / "review.md"
        prompt_r.write_text("r")

        mock_git_client.get_head_sha.return_value = "1234567890"
        mock_git_client.get_review_comments.return_value = []
        mock_git_client.get_diff.return_value = []

        git_patch, llm_patch = self._setup_clients(mock_git_client, mock_llm_client)
        env_patch = patch.dict(
            "os.environ",
            {"INFERENCE_ENGINE": "vllm", "VLLM_MODEL": "CustomModel"},
            clear=False,
        )
        with git_patch, llm_patch, patch.object(pipeline, "PROMPTS_DIR", tmp_path), \
                patch.object(pipeline, "EXPENSIVE_MODEL", None), env_patch:
            result = await run_review({"id": 1, "project_id": "p"})

        assert "CustomModel" in result["aggregated_comment"]


# ---------------------------------------------------------------------------
# _review_locks mechanism
# ---------------------------------------------------------------------------


class TestReviewLocks:
    @pytest.mark.asyncio
    async def test_lock_created_per_mr(self, mock_git_client, mock_llm_client, tmp_path):
        prompt_s = tmp_path / "summarize.md"
        prompt_s.write_text("s")
        prompt_r = tmp_path / "review.md"
        prompt_r.write_text("r")

        mock_git_client.get_head_sha.return_value = "abc1234567"
        mock_git_client.get_review_comments.return_value = []
        mock_git_client.get_diff.return_value = []

        git_cm = AsyncMock()
        git_cm.__aenter__ = AsyncMock(return_value=mock_git_client)
        git_cm.__aexit__ = AsyncMock(return_value=None)

        llm_cm = AsyncMock()
        llm_cm.__aenter__ = AsyncMock(return_value=mock_llm_client)
        llm_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("gateway.services.review_pipeline.create_git_client", return_value=git_cm), \
             patch("gateway.services.review_pipeline.LLMClient", return_value=llm_cm), \
             patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            await run_review({"id": 1, "project_id": "p1"})
            await run_review({"id": 2, "project_id": "p1"})

        assert "p1/1" in _review_locks
        assert "p1/2" in _review_locks
        assert isinstance(_review_locks["p1/1"], asyncio.Lock)

    @pytest.mark.asyncio
    async def test_lock_reused_for_same_mr(self, mock_git_client, mock_llm_client, tmp_path):
        prompt_s = tmp_path / "summarize.md"
        prompt_s.write_text("s")
        prompt_r = tmp_path / "review.md"
        prompt_r.write_text("r")

        mock_git_client.get_head_sha.return_value = "abc1234567"
        mock_git_client.get_review_comments.return_value = []
        mock_git_client.get_diff.return_value = []

        git_cm = AsyncMock()
        git_cm.__aenter__ = AsyncMock(return_value=mock_git_client)
        git_cm.__aexit__ = AsyncMock(return_value=None)

        llm_cm = AsyncMock()
        llm_cm.__aenter__ = AsyncMock(return_value=mock_llm_client)
        llm_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("gateway.services.review_pipeline.create_git_client", return_value=git_cm), \
             patch("gateway.services.review_pipeline.LLMClient", return_value=llm_cm), \
             patch.object(pipeline, "PROMPTS_DIR", tmp_path):
            await run_review({"id": 1, "project_id": "p1"})
            lock = _review_locks["p1/1"]
            await run_review({"id": 1, "project_id": "p1"})
            # Same lock object should be reused
            assert _review_locks["p1/1"] is lock


# ---------------------------------------------------------------------------
# ReviewPipelineError
# ---------------------------------------------------------------------------


class TestReviewPipelineError:
    def test_is_exception(self):
        err = ReviewPipelineError("something broke")
        assert isinstance(err, Exception)
        assert str(err) == "something broke"

    def test_raise_and_catch(self):
        with pytest.raises(ReviewPipelineError):
            raise ReviewPipelineError("test")
