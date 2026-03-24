# API Reference

Base URL: `http://localhost:8000/api` (direct) or `http://localhost:3102/api` (via nginx)

Authentication: Endpoints marked with a lock require a `GATEWAY_API_TOKEN` bearer token:
```
Authorization: Bearer <your-token>
```
If `GATEWAY_API_TOKEN` is not set in `.env`, auth is disabled (dev mode).

---

## Health

### GET /api/health

Check status of all backend services.

**Response:**
```json
{
  "status": "ok",
  "services": {
    "llm": { "engine": "ollama", "status": "healthy", "model": "qwen2.5-coder:32b" },
    "pr_agent": { "status": "healthy" },
    "defectdojo": { "status": "healthy" },
    "tabby": { "status": "healthy" }
  }
}
```

Status values: `ok` (all healthy), `degraded` (one or more unhealthy).
Service status values: `healthy`, `unhealthy`, `unreachable`.
`tabby` only appears when `TABBY_URL` is configured.

### GET /api/models

List available LLM models.

**Response:**
```json
{
  "models": [
    { "name": "qwen2.5-coder:32b", "size": 18000000000 }
  ]
}
```

---

## Reviews

### GET /api/reviews

List open merge/pull requests with their review comments.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 20 | 1-100 |
| `offset` | int | 0 | Pagination offset |

**Response:**
```json
{
  "reviews": [
    {
      "id": 42,
      "platform": "gitlab",
      "project_id": "group/project",
      "title": "feat: add user auth",
      "author": "jdoe",
      "created_at": "2025-01-15T10:30:00Z",
      "url": "https://gitlab.example.com/group/project/-/merge_requests/42",
      "review_comments": [
        { "body": "...", "created_at": "..." }
      ]
    }
  ]
}
```

### POST /api/reviews/run (auth required)

Trigger an AI review for a specific MR/PR.

**Rate limit:** 5/minute

**Request:**
```json
{
  "platform": "gitlab",
  "project_id": "group/project",
  "mr_id": 42,
  "force": false
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `platform` | string | from `GIT_PLATFORM` env | `gitlab` or `gitea` |
| `project_id` | string | required | `group/project` (GitLab) or `owner/repo` (Gitea) |
| `mr_id` | int | required | MR/PR number |
| `force` | bool | false | Re-review even if already reviewed at this SHA |

**Response (success):**
```json
{
  "mr_id": 42,
  "head_sha": "abc1234",
  "files_reviewed": 3,
  "files_approved": 5,
  "files_skipped": 2,
  "posted": true,
  "skipped_reason": null
}
```

**Response (already reviewed):**
```json
{
  "mr_id": 42,
  "head_sha": "abc1234",
  "files_reviewed": 0,
  "posted": false,
  "skipped_reason": "already reviewed at abc1234"
}
```

**Errors:**
- `401` — Missing/invalid bearer token
- `429` — Rate limited
- `502` — Pipeline error (LLM or git platform unavailable)

### GET /api/reviews/result

Fetch the parsed result of the most recent AI review comment.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `project_id` | string | Required |
| `mr_id` | int | Required |

**Response:**
```json
{
  "head_sha": "abc1234",
  "files": [
    { "filename": "src/auth.py", "decision": "NEEDS_REVIEW", "issues": 2 }
  ],
  "approved_count": 5,
  "needs_review_count": 3,
  "posted_at": "2025-01-15T10:35:00Z"
}
```

Returns `head_sha: null` if no review comment exists.

### POST /api/reviews/comment (auth required)

Post a comment to an MR/PR. Used by the autofix skill.

**Rate limit:** 20/minute

**Request:**
```json
{
  "platform": "gitlab",
  "project_id": "group/project",
  "mr_id": 42,
  "body": "## Autofix Summary\n..."
}
```

**Response:**
```json
{ "status": "posted" }
```

**Errors:**
- `422` — Comment body is empty after sanitization

---

## Findings (DefectDojo)

### GET /api/findings

Fetch findings from DefectDojo.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 20 | 1-500 |
| `offset` | int | 0 | Pagination offset |
| `severity` | string | — | `Critical`, `High`, `Medium`, `Low`, or `Info` |
| `scan_type` | string | — | Filter by scan type (e.g., `Semgrep JSON Report`) |

**Response:**
```json
{
  "count": 150,
  "results": [
    {
      "id": 1,
      "title": "SQL Injection in login handler",
      "severity": "High",
      "file_path": "src/auth.py",
      "line": 42
    }
  ]
}
```

### GET /api/findings/summary

Aggregate finding counts by severity.

**Response:**
```json
{
  "severity_counts": {
    "Critical": 2,
    "High": 15,
    "Medium": 42,
    "Low": 28,
    "Info": 5
  },
  "total": 92
}
```

---

## Configuration

### GET /api/config

Read PR-Agent configuration (TOML).

**Response:**
```json
{
  "config": {
    "config": { "model": "...", "custom_instructions": "..." },
    "gitlab": { "pr_commands": ["/describe", "/review"] },
    "gitea": { "pr_commands": ["/describe", "/review"] }
  }
}
```

### PUT /api/config (rate limited: 10/min)

Update PR-Agent configuration.

**Request:**
```json
{
  "config": {
    "config": { "model": "ollama/qwen2.5-coder:32b", "custom_instructions": "Focus on security" },
    "gitlab": { "pr_commands": ["/describe", "/review", "/improve"] }
  }
}
```

**Errors:**
- `422` — Invalid TOML structure

---

## Prompts

### GET /api/prompts

List available prompt templates.

**Response:**
```json
{
  "prompts": [
    { "name": "review", "filename": "review.md" },
    { "name": "summarize", "filename": "summarize.md" }
  ]
}
```

### GET /api/prompts/{name}

Read a prompt template.

**Response:**
```json
{
  "name": "review",
  "content": "You are an expert code reviewer..."
}
```

**Errors:**
- `404` — Prompt not found
- `422` — Invalid name (must be alphanumeric with hyphens/underscores)

### PUT /api/prompts/{name} (rate limited: 10/min)

Create or update a prompt template. Content is sanitized (prompt injection patterns stripped).

**Request:**
```json
{
  "content": "You are an expert code reviewer..."
}
```

**Errors:**
- `422` — Content exceeds 50,000 characters or invalid name

---

## Webhook

### POST /api/webhook

Receives git platform webhooks and proxies to PR-Agent. Verifies signatures when `PR_AGENT_WEBHOOK_SECRET` is set.

**Headers (GitLab):**
```
X-Gitlab-Token: <PR_AGENT_WEBHOOK_SECRET>
```

**Headers (Gitea):**
```
X-Gitea-Signature: <HMAC-SHA256 of body>
```

**Errors:**
- `401` — Invalid or missing webhook signature
- `502` — Failed to proxy to PR-Agent

---

## Metrics

### GET /metrics

Prometheus metrics endpoint (provided by `prometheus-fastapi-instrumentator`).

Includes: request count, latency histograms, in-progress requests, response sizes.

---

## Error Format

All errors return:
```json
{
  "error": "Human-readable error message"
}
```

Or for validation errors (FastAPI):
```json
{
  "detail": [
    { "loc": ["body", "mr_id"], "msg": "field required", "type": "value_error.missing" }
  ]
}
```
