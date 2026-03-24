# Autofix Skill

Automatically implement AI code review suggestions from open MR/PR review threads, commit the fixes in one clean commit, and post a summary comment.

## Trigger

Run when a user says: "fix the review comments", "autofix", "apply review suggestions", or `/autofix`.

## Prerequisites

- The MR/PR must have been reviewed by the AI reviewer (comments contain `🤖 Prompt for AI Agents` sections).
- `GATEWAY_URL` environment variable must point to the running API gateway (e.g., `http://localhost:8000`).
- `GATEWAY_API_TOKEN` environment variable must be set if the gateway requires authentication.
- The working tree must be clean (no uncommitted changes) before starting.

## Workflow

### Step 1 — Load repository instructions

Check if `AGENTS.md` exists at the repository root. If it does, read it and follow any overrides or conventions it defines before proceeding.

### Step 2 — Verify working tree is clean

Run `git status --short`. If there are uncommitted changes, stop and ask the user to commit or stash them first.

### Step 3 — Identify the open PR/MR

Run `git branch --show-current` to get the branch name, then:
```bash
gh pr view --json number,headRefName,baseRefName
```
If no open PR exists for this branch, stop and inform the user.

### Step 4 — Fetch unresolved AI review threads

Call the gateway API to get the review result:
```bash
curl -s "${GATEWAY_URL}/api/reviews/result?project_id=<project>&mr_id=<number>"
```

Alternatively, use the GitHub GraphQL API to fetch unresolved review threads (see `github.md` for the exact query).

Filter comments to those containing the `🤖 Prompt for AI Agents` marker. Parse each `<details>` block to extract:
- `File` — path to the file to fix
- `Lines` — line range containing the issue
- `Issue` — short description
- `Action` — concrete fix instruction (this is the directive to execute)
- `Acceptance criteria` — condition to verify after fixing

### Step 5 — Display and confirm

Show the user a table of all found action items:

| # | File | Lines | Issue | Severity |
|---|------|-------|-------|----------|
| 1 | src/foo.py | 42-45 | SQL injection | critical |

Then ask: **Auto-fix all? (y)es / (n)o — manual review / (q)uit**

### Step 6 — Implement fixes

For each action item:
1. Read the file using the Read tool.
2. Apply the fix using the Edit tool, following the `Action` instruction precisely.
3. Re-read the file and verify the `Acceptance criteria` is met.
4. If a fix cannot be applied (e.g., the code has changed since review), skip it and note it.

Process files in order from most critical to least critical severity.

### Step 7 — Commit all fixes in one commit

Stage only the files that were modified:
```bash
git add <file1> <file2> ...
```

Create a single commit:
```bash
git commit -m "fix: apply AI review suggestions (N issues)"
```

Do **not** amend previous commits. Do **not** force-push.

### Step 8 — Validate before pushing

Ask the user: **Run validation before pushing? (build / lint / test / skip)**

If they choose a validation step, run the appropriate command and wait for it to succeed before continuing.

### Step 9 — Post summary comment

Call the gateway to post a summary comment to the MR/PR:
```bash
curl -s -X POST "${GATEWAY_URL}/api/reviews/comment" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${GATEWAY_API_TOKEN}" \
  -d '{
    "project_id": "<project>",
    "mr_id": <number>,
    "body": "## Autofix Summary\n\nApplied N fixes:\n- ...\n\nSkipped M issues (see notes)."
  }'
```

## Error Handling

- If a fix cannot be applied (code changed, conflict, ambiguous location), skip it, note it in the summary, and continue with remaining fixes.
- Never force-push or amend published commits.
- If validation fails after applying fixes, do not push. Ask the user how to proceed.

## Limitations

- Only processes comments containing the `🤖 Prompt for AI Agents` marker written by the AI reviewer.
- Does not handle fixes that require external tooling side effects (e.g., `npm install`, `go mod tidy`). It will note these for the user.
- Does not resolve merge conflicts.
