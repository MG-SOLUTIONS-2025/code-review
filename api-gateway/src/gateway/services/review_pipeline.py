"""
AI review pipeline.

Pipeline flow per MR/PR:
  1. Fetch diff (all changed files)
  2. Skip binary / empty / deleted files
  3. Batch remaining files in groups of REVIEW_BATCH_SIZE
  4. Per batch:
     a. Cheap model summarizes each file → NEEDS_REVIEW | APPROVED  (triage gate)
     b. Expensive model reviews NEEDS_REVIEW files → structured issues
  5. Build aggregated comment with per-file breakdown + agent-actionable prompts
  6. Post comment to the MR/PR (unless SHA unchanged and force=False)
"""

import asyncio
import functools
import os
import re
from pathlib import Path

from loguru import logger

from gateway.services.git_platform import create_git_client
from gateway.services.llm import (
    TOKEN_BUDGET_REVIEW,
    TOKEN_BUDGET_SUMMARIZE,
    LLMClient,
)
from gateway.utils.sanitize import sanitize_prompt_input

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHEAP_MODEL: str | None = os.getenv("REVIEW_CHEAP_MODEL") or None
EXPENSIVE_MODEL: str | None = os.getenv("REVIEW_EXPENSIVE_MODEL") or None
REVIEW_BATCH_SIZE = int(os.getenv("REVIEW_BATCH_SIZE", "6"))
MAX_PATCH_CHARS = int(os.getenv("MAX_PATCH_CHARS", "8000"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
PROMPTS_DIR = Path(os.getenv("PROMPTS_DIR", "/app/config/prompts"))

SKIP_EXTENSIONS = frozenset(
    os.getenv(
        "SKIP_EXTENSIONS",
        ".png,.jpg,.jpeg,.gif,.svg,.ico,.woff,.woff2,.ttf,.eot,.pdf,"
        ".zip,.tar,.gz,.lock,.sum,.snap,.pb,.pyc",
    ).split(",")
)

# ---------------------------------------------------------------------------
# Constants / patterns
# ---------------------------------------------------------------------------

_MAX_REVIEW_LOCKS = 100
_review_locks: dict[str, asyncio.Lock] = {}
_REVIEW_SHA_TAG = "ai-review-sha"
_SHA_PATTERN = re.compile(r"<!-- ai-review-sha: ([a-f0-9]{7,40}) -->")
# Matches: ### [severity: critical] src/foo.py:42-45 — Short title
_ISSUE_HEADER = re.compile(
    r"\[severity: (\w+)\] ([^:\n]+):(\d+)(?:-(\d+))? — (.+)"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReviewPipelineError(Exception):
    pass


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=16)
def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt '{name}' not found at {path}")
    return path.read_text()


# ---------------------------------------------------------------------------
# File filtering
# ---------------------------------------------------------------------------


def _should_skip_file(file: dict) -> bool:
    filename = file.get("filename", "")
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
        if ext in SKIP_EXTENSIONS:
            return True
    if file.get("status") == "deleted":
        return True
    patch = file.get("patch", "")
    if not patch or not patch.strip():
        return True
    return False


# ---------------------------------------------------------------------------
# Issue parsing & agent prompt formatting
# ---------------------------------------------------------------------------


def _parse_issues(review_text: str) -> list[dict]:
    """Extract structured issue dicts from the LLM review output."""
    issues: list[dict] = []
    # Split on ### [ so we can handle each issue block
    blocks = re.split(r"### \[", review_text)
    for block in blocks[1:]:
        m = _ISSUE_HEADER.match(block)
        if not m:
            continue
        severity, filename, line_start, line_end, title = m.groups()

        problem_m = re.search(
            r"\*\*Problem:\*\*\s*(.+?)(?=\*\*Suggestion:\*\*|^---|\Z)",
            block,
            re.DOTALL | re.MULTILINE,
        )
        suggestion_m = re.search(
            r"\*\*Suggestion:\*\*\s*(.+?)(?=^---|^### \[|\Z)",
            block,
            re.DOTALL | re.MULTILINE,
        )
        issues.append(
            {
                "severity": severity.lower(),
                "filename": filename.strip(),
                "line_start": int(line_start),
                "line_end": int(line_end) if line_end else int(line_start),
                "title": title.strip(),
                "problem": problem_m.group(1).strip() if problem_m else "",
                "suggestion": suggestion_m.group(1).strip() if suggestion_m else "",
            }
        )
    return issues


def _format_agent_prompt(issue: dict) -> str:
    """Render a collapsible agent-actionable block for one issue."""
    line_ref = str(issue["line_start"])
    if issue.get("line_end") and issue["line_end"] != issue["line_start"]:
        line_ref = f"{issue['line_start']}-{issue['line_end']}"
    suggestion = issue.get("suggestion") or issue.get("title", "")
    return (
        "\n<details>\n"
        "<summary>🤖 Prompt for AI Agents</summary>\n\n"
        f"**File:** `{issue['filename']}`  "
        f"**Lines:** {line_ref}  "
        f"**Issue:** {issue['title']}\n\n"
        f"**Action:** {suggestion}\n\n"
        f"**Acceptance criteria:** The issue described above ({issue['title']!r}) "
        f"no longer exists in `{issue['filename']}`.\n\n"
        "</details>\n"
    )


# ---------------------------------------------------------------------------
# Per-file LLM steps
# ---------------------------------------------------------------------------


async def _summarize_file(client: LLMClient, file: dict) -> dict:
    """Cheap model: classify the diff as NEEDS_REVIEW or APPROVED."""
    try:
        prompt = _load_prompt("summarize")
    except FileNotFoundError:
        return {"filename": file["filename"], "decision": "NEEDS_REVIEW", "summary": ""}

    patch = sanitize_prompt_input(file.get("patch", "")[:MAX_PATCH_CHARS])
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"File: {file['filename']}\n\nDiff:\n{patch}"},
    ]
    try:
        result = await client.chat_completion(
            messages, model=CHEAP_MODEL, token_budget=TOKEN_BUDGET_SUMMARIZE
        )
        content = result["choices"][0]["message"]["content"].strip()
        lines = content.splitlines()
        first = lines[0].strip().upper() if lines else ""
        decision = "APPROVED" if "APPROVED" in first else "NEEDS_REVIEW"
        summary = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        return {"filename": file["filename"], "decision": decision, "summary": summary}
    except Exception as e:
        logger.warning(
            "Summarize failed for {} ({}); defaulting to NEEDS_REVIEW", file["filename"], e
        )
        return {"filename": file["filename"], "decision": "NEEDS_REVIEW", "summary": ""}


async def _review_file(client: LLMClient, file: dict, summary: str) -> dict:
    """Expensive model: full review of a file that needs attention."""
    try:
        prompt = _load_prompt("review")
    except FileNotFoundError:
        logger.error("review.md prompt not found")
        return {
            "filename": file["filename"],
            "decision": "NEEDS_REVIEW",
            "summary": summary,
            "review": "Review prompt not configured.",
            "issues": [],
        }

    patch = sanitize_prompt_input(file.get("patch", "")[:MAX_PATCH_CHARS])
    user_content = (
        f"File: {file['filename']}\n\n"
        f"Preliminary classification: {summary}\n\n"
        f"Diff:\n{patch}"
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_content},
    ]
    try:
        result = await client.chat_completion(
            messages, model=EXPENSIVE_MODEL, token_budget=TOKEN_BUDGET_REVIEW
        )
        review_text = result["choices"][0]["message"]["content"].strip()
        issues = _parse_issues(review_text)
        return {
            "filename": file["filename"],
            "decision": "NEEDS_REVIEW",
            "summary": summary,
            "review": review_text,
            "issues": issues,
        }
    except Exception as e:
        logger.error("Review failed for {}: {}", file["filename"], e)
        return {
            "filename": file["filename"],
            "decision": "NEEDS_REVIEW",
            "summary": summary,
            "review": f"Review failed: {e}",
            "issues": [],
        }


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------


async def _process_batch(client: LLMClient, files: list[dict]) -> list[dict]:
    """Summarize all files; then run full review only on NEEDS_REVIEW ones."""
    triage = await asyncio.gather(*[_summarize_file(client, f) for f in files])

    review_tasks = []
    review_indices: list[int] = []
    results: list[dict | None] = [None] * len(files)

    for i, (file, t) in enumerate(zip(files, triage)):
        if t["decision"] == "APPROVED":
            results[i] = {
                "filename": file["filename"],
                "decision": "APPROVED",
                "summary": t["summary"],
                "review": None,
                "issues": [],
            }
        else:
            review_tasks.append(_review_file(client, file, t["summary"]))
            review_indices.append(i)

    reviewed = await asyncio.gather(*review_tasks)
    for i, result in zip(review_indices, reviewed):
        results[i] = result

    return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# Comment building
# ---------------------------------------------------------------------------


def _build_comment(file_results: list[dict], head_sha: str, model: str) -> str:
    sha_short = head_sha[:7]
    approved = [f for f in file_results if f["decision"] == "APPROVED"]
    needs_review = [f for f in file_results if f["decision"] == "NEEDS_REVIEW"]

    lines: list[str] = [
        f"<!-- {_REVIEW_SHA_TAG}: {head_sha} -->",
        "## AI Code Review",
        "",
        f"**Commit:** `{sha_short}` &middot; **Model:** {model}",
        "",
        "### Summary",
        "",
        "| File | Decision | Issues |",
        "|------|----------|--------|",
    ]

    for f in file_results:
        icon = "✅" if f["decision"] == "APPROVED" else "🔍"
        count = str(len(f.get("issues", []))) if f["decision"] == "NEEDS_REVIEW" else "—"
        lines.append(f"| `{f['filename']}` | {icon} {f['decision']} | {count} |")

    if needs_review:
        lines += ["", "### Issues"]
        for f in needs_review:
            lines += ["", f"#### `{f['filename']}`", ""]
            if f.get("review"):
                lines.append(f["review"])
            for issue in f.get("issues", []):
                lines.append(_format_agent_prompt(issue))

    lines += [
        "",
        (
            f"---\n*Reviewed {len(file_results)} files"
            f" &middot; {len(approved)} approved"
            f" &middot; {len(needs_review)} need attention"
            f" &middot; Powered by {model}*"
        ),
    ]
    return "\n".join(lines)


def parse_review_comment(body: str) -> dict | None:
    """Parse a previously posted AI review comment into a structured summary."""
    sha_m = _SHA_PATTERN.search(body)
    if not sha_m:
        return None
    head_sha = sha_m.group(1)

    files: list[dict] = []
    row_re = re.compile(r"\| `([^`]+)` \| [✅🔍] (\w+) \| ([^|]+) \|")
    for m in row_re.finditer(body):
        filename, decision, count_str = m.groups()
        count_str = count_str.strip()
        issue_count = 0
        if count_str != "—":
            try:
                issue_count = int(count_str)
            except ValueError:
                pass
        files.append({"filename": filename, "decision": decision, "issue_count": issue_count})

    return {
        "head_sha": head_sha,
        "files": files,
        "approved_count": sum(1 for f in files if f["decision"] == "APPROVED"),
        "needs_review_count": sum(1 for f in files if f["decision"] == "NEEDS_REVIEW"),
    }


# ---------------------------------------------------------------------------
# Incremental SHA tracking
# ---------------------------------------------------------------------------


async def get_last_reviewed_sha(git_client, mr: dict) -> str | None:
    """Scan existing review comments for the last AI-reviewed SHA."""
    try:
        comments = await git_client.get_review_comments(mr)
        for comment in comments:
            body = comment.get("body", "")
            # If BOT_USERNAME is set, only inspect comments from that user
            if BOT_USERNAME and comment.get("author") != BOT_USERNAME:
                continue
            m = _SHA_PATTERN.search(body)
            if m:
                return m.group(1)
    except Exception as e:
        logger.warning("Could not fetch previous review comments: {}", e)
    return None


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


async def run_review(mr: dict, force: bool = False) -> dict:
    """Orchestrate the full review pipeline for one MR/PR."""
    mr_key = f"{mr.get('project_id', '')}/{mr.get('id', '')}"
    if mr_key not in _review_locks:
        if len(_review_locks) >= _MAX_REVIEW_LOCKS:
            oldest = next(iter(_review_locks))
            del _review_locks[oldest]
        _review_locks[mr_key] = asyncio.Lock()
    async with _review_locks[mr_key]:
        try:
            async with create_git_client() as git_client:
                async with LLMClient() as llm_client:
                    head_sha = await git_client.get_head_sha(mr)
                    if not head_sha:
                        raise ReviewPipelineError("Could not determine HEAD SHA for MR")

                    # Incremental guard
                    if not force:
                        last_sha = await get_last_reviewed_sha(git_client, mr)
                        if last_sha and last_sha == head_sha:
                            logger.info("MR {} already reviewed at SHA {}; skipping", mr.get("id"), head_sha)
                            return {
                                "mr_id": mr.get("id"),
                                "head_sha": head_sha,
                                "files_reviewed": 0,
                                "files_approved": 0,
                                "files_skipped": 0,
                                "file_results": [],
                                "aggregated_comment": "",
                                "posted": False,
                                "skipped_reason": f"already reviewed at {head_sha[:7]}",
                            }

                    # Fetch diff
                    all_files = await git_client.get_diff(mr)
                    to_process = [f for f in all_files if not _should_skip_file(f)]
                    skipped = len(all_files) - len(to_process)
                    logger.info(
                        "MR {}: {} files total, {} to review, {} skipped",
                        mr.get("id"),
                        len(all_files),
                        len(to_process),
                        skipped,
                    )

                    # Process in batches
                    all_results: list[dict] = []
                    for i in range(0, len(to_process), REVIEW_BATCH_SIZE):
                        batch = to_process[i : i + REVIEW_BATCH_SIZE]
                        all_results.extend(await _process_batch(llm_client, batch))

                    # Determine model name for the comment footer
                    engine = os.getenv("INFERENCE_ENGINE", "ollama")
                    if engine == "vllm":
                        model_name = EXPENSIVE_MODEL or os.getenv(
                            "VLLM_MODEL", "Qwen/Qwen2.5-Coder-32B-Instruct"
                        )
                    else:
                        model_name = EXPENSIVE_MODEL or os.getenv("OLLAMA_MODEL", "qwen2.5-coder:32b")

                    comment_body = _build_comment(all_results, head_sha, model_name)
                    await git_client.post_comment(mr, comment_body)

                    files_reviewed = sum(1 for f in all_results if f["decision"] == "NEEDS_REVIEW")
                    files_approved = sum(1 for f in all_results if f["decision"] == "APPROVED")

                    return {
                        "mr_id": mr.get("id"),
                        "head_sha": head_sha,
                        "files_reviewed": files_reviewed,
                        "files_approved": files_approved,
                        "files_skipped": skipped,
                        "file_results": all_results,
                        "aggregated_comment": comment_body,
                        "posted": True,
                        "skipped_reason": None,
                    }

        except ReviewPipelineError:
            raise
        except Exception as e:
            logger.error("Review pipeline failed for MR {}: {}", mr.get("id"), e)
            raise ReviewPipelineError(f"Review pipeline failed: {e}") from e
