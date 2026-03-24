# Setup Guide

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- (GPU) NVIDIA GPU with 20+ GB VRAM and [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- (CPU) At least 16 GB RAM — expect slower inference

## 1. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

### Required Settings

| Variable | Description | Example |
|----------|-------------|---------|
| `GIT_PLATFORM` | `gitlab` or `gitea` | `gitlab` |
| `GIT_BASE_URL` | Your git instance URL | `https://gitlab.example.com` |
| `GIT_TOKEN` | Personal access token (see scopes below) | `glpat-xxxx` |
| `DEFECTDOJO_SECRET_KEY` | Random string for Django | `openssl rand -hex 32` |
| `DEFECTDOJO_ADMIN_PASSWORD` | Initial admin password | `securepassword123` |
| `PR_AGENT_WEBHOOK_SECRET` | Shared secret for webhook verification | `openssl rand -hex 16` |

### Token Scopes

**GitLab:** `api` scope, Reporter role (reads MRs, posts comments, no merge access)

**Gitea:** `repo` + `write:issue` scope (reads PRs, posts comments, no merge access)

### Optional Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `INFERENCE_ENGINE` | `ollama` | `ollama` or `vllm` |
| `OLLAMA_MODEL` | `qwen2.5-coder:32b` | Use `:7b` for <20 GB VRAM |
| `GATEWAY_API_TOKEN` | (empty = auth disabled) | Protects `/api/reviews/run` and `/api/reviews/comment` |
| `BOT_USERNAME` | (empty) | Git username of review bot for incremental detection |

See `.env.example` for the full list with descriptions.

## 2. Start Services

### With GPU (recommended)

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

### CPU only

```bash
docker compose up -d
```

The override file (`docker-compose.override.yml`) relaxes the Ollama healthcheck for CPU mode.

### With vLLM (high-throughput)

```bash
# In .env, set:
# INFERENCE_ENGINE=vllm
# VLLM_MODEL=Qwen/Qwen2.5-Coder-32B-Instruct

docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile vllm up -d
```

### With TabbyML (code intelligence)

```bash
# In .env, set:
# ENABLE_TABBY=true
# TABBY_URL=http://tabby:8080

docker compose --profile tabby up -d
```

## 3. Verify Services

```bash
python3 scripts/healthcheck.py
```

Expected output:
```
Ollama:      OK (200)
DefectDojo:  OK (200)
API Gateway: OK (200)
Dashboard:   OK (200)
PR-Agent:    OK (200)
Prometheus:  OK (200)
Grafana:     OK (200)
All services healthy.
```

First startup takes 2-5 minutes (LLM model download, DefectDojo DB migration).

## 4. Access Services

| Service | URL | Credentials |
|---------|-----|-------------|
| Dashboard | http://localhost:3102 | `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` |
| DefectDojo | http://localhost:3102/defectdojo/ | `admin` / `DEFECTDOJO_ADMIN_PASSWORD` |
| Grafana | http://localhost:3001 | `admin` / `GRAFANA_ADMIN_PASSWORD` |
| Prometheus | http://localhost:9090 | — |
| API Gateway (direct) | http://localhost:8000 | — |

## 5. Generate DefectDojo API Token

1. Log in to DefectDojo at http://localhost:3102/defectdojo/
2. Navigate to the user menu (top-right) and select **API v2 Key**
3. Copy the token
4. Add to `.env`:
   ```
   DEFECTDOJO_API_TOKEN=your-token-here
   ```
5. Restart the gateway: `docker compose restart api-gateway`

## 6. Configure Git Webhook

### GitLab

1. Go to your project **Settings > Webhooks**
2. URL: `http://<your-server>:3102/api/webhook`
3. Secret token: value of `PR_AGENT_WEBHOOK_SECRET`
4. Triggers: **Merge request events**
5. Click **Add webhook**

### Gitea

1. Go to your repo **Settings > Webhooks > Add Webhook > Gitea**
2. Target URL: `http://<your-server>:3102/api/webhook`
3. Secret: value of `PR_AGENT_WEBHOOK_SECRET`
4. Trigger: **Pull Request**
5. Click **Add Webhook**

## 7. Set Up CI/CD Pipeline

CI pipelines run SAST scans and push findings to DefectDojo.

### GitLab CI

1. Copy `ci-templates/gitlab-ci.yml` to your project as `.gitlab-ci.yml`
2. Set these CI/CD variables in **Settings > CI/CD > Variables**:

   | Variable | Type | Description |
   |----------|------|-------------|
   | `GATEWAY_URL` | Variable | `http://<your-server>:8000` (or internal docker URL) |
   | `GATEWAY_API_TOKEN` | Secret | Same as `GATEWAY_API_TOKEN` in `.env` |
   | `DEFECTDOJO_URL` | Variable | `http://<your-server>:8081` |
   | `DEFECTDOJO_API_TOKEN` | Secret | Token from step 5 |
   | `DEFECTDOJO_ENGAGEMENT_ID` | Variable | Engagement ID from DefectDojo (see below) |

### Gitea Actions

1. Copy `ci-templates/gitea-actions.yml` to your repo as `.gitea/workflows/review.yml`
2. Set repository secrets in **Settings > Actions > Secrets**:

   | Secret | Description |
   |--------|-------------|
   | `GATEWAY_URL` | `http://<your-server>:8000` |
   | `GATEWAY_API_TOKEN` | Same as `GATEWAY_API_TOKEN` in `.env` |
   | `DEFECTDOJO_URL` | `http://<your-server>:8081` |
   | `DEFECTDOJO_API_TOKEN` | Token from step 5 |
   | `DEFECTDOJO_ENGAGEMENT_ID` | Engagement ID from DefectDojo |

### Getting DefectDojo Engagement ID

1. Log in to DefectDojo
2. Go to **Products > Add Product** (or select existing)
3. Under the product, go to **Engagements > Add Engagement**
4. The engagement ID is in the URL: `/engagement/<ID>/...`

## 8. Customizing Prompts

Edit prompt templates from the dashboard (**Settings > Prompts** tab) or directly in `config/prompts/`:

| Prompt | Purpose |
|--------|---------|
| `review.md` | Full code review (security, performance, correctness) |
| `summarize.md` | Quick classify: APPROVED vs NEEDS_REVIEW |
| `triage.md` | SAST finding triage (true/false positive) |
| `security-audit.md` | Deep security audit with CWE references |

## Updating

```bash
git pull
docker compose pull
docker compose up -d
```

Data is persisted in Docker volumes (`ollama-data`, `defectdojo-db-data`, `prometheus-data`, `grafana-data`).
