# Self-Hosted Code Review

A privacy-first, self-hosted AI code review platform. Drop-in alternative to CodeRabbit that runs entirely on your infrastructure using open-weight LLMs.

**What it does:** Automatically reviews merge/pull requests with Qwen2.5-Coder, runs SAST scans (Semgrep, Gitleaks, Trivy), triages findings with LLM analysis, and aggregates results in DefectDojo — all behind your firewall.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  nginx (reverse proxy + basic auth) :3102                   │
├──────────────────────┬──────────────────────────────────────┤
│  Dashboard (React)   │  API Gateway (FastAPI)               │
│  :5173 (dev)         │  :8000                               │
│  - Browse reviews    │  - /api/reviews/*   (manage reviews) │
│  - View findings     │  - /api/webhook     (git events)     │
│  - Edit prompts      │  - /api/findings/*  (DefectDojo)     │
│  - Settings          │  - /api/config      (PR-Agent conf)  │
│                      │  - /api/prompts/*   (prompt editor)  │
│                      │  - /metrics         (Prometheus)      │
├──────────────────────┴──────────────────────────────────────┤
│  Review Pipeline                                            │
│  1. Fetch diff from GitLab/Gitea                            │
│  2. Classify files (cheap model → APPROVED / NEEDS_REVIEW)  │
│  3. Deep review flagged files (expensive model)             │
│  4. Post structured comment to MR/PR                        │
├─────────────────────────────────────────────────────────────┤
│  LLM Engine          │  SAST / Findings                     │
│  Ollama or vLLM      │  DefectDojo + Semgrep + Gitleaks     │
│  Qwen2.5-Coder-32B  │  + Trivy + LLM triage                │
├──────────────────────┴──────────────────────────────────────┤
│  Observability: Prometheus + Grafana                        │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Clone and configure
git clone <repo-url> && cd selfhosted-code-review
cp .env.example .env
# Edit .env: set GIT_PLATFORM, GIT_BASE_URL, GIT_TOKEN, secrets

# 2. (Optional) Run setup wizard — checks GPU, generates passwords
bash scripts/setup.sh

# 3. Start all services
docker compose up -d

# 4. Wait for services to initialize (~2 min for LLM model pull)
python3 scripts/healthcheck.py

# 5. Access the dashboard
open http://localhost:3102   # login: admin / changeme (set in .env)
```

### GPU vs CPU

| Mode | Command | Model | VRAM | Speed |
|------|---------|-------|------|-------|
| GPU (recommended) | `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d` | `qwen2.5-coder:32b` | 20+ GB | ~10s/review |
| CPU fallback | `docker compose up -d` | `qwen2.5-coder:7b` | — | ~60s/review |

Set `OLLAMA_MODEL` in `.env` to match your hardware.

## Supported Platforms

- **GitLab** (self-hosted or gitlab.com)
- **Gitea** (including Forgejo)

## Key Features

- **AI Code Review** — LLM-powered review with severity, line references, and actionable suggestions
- **Two-stage pipeline** — cheap model classifies, expensive model reviews (saves compute)
- **Incremental reviews** — skips already-reviewed commits (SHA tracking)
- **SAST Integration** — Semgrep, Gitleaks, Trivy via CI/CD templates
- **LLM Triage** — classifies SAST findings as true/false positive
- **DefectDojo** — aggregates and tracks all findings
- **Custom Prompts** — edit review/triage prompts from the dashboard
- **Observability** — Prometheus metrics + Grafana dashboards

## Documentation

| Doc | Description |
|-----|-------------|
| [SETUP.md](SETUP.md) | Full deployment guide (Docker, GPU, CI/CD integration) |
| [API.md](API.md) | Complete API reference with request/response schemas |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common issues and fixes |
| [research.md](research.md) | Tech stack evaluation and design decisions |

## Project Structure

```
api-gateway/         FastAPI backend (review pipeline, git integration, LLM client)
dashboard/           React frontend (Vite + Tailwind + React Query)
config/
  prompts/           LLM prompt templates (review.md, summarize.md, triage.md)
  pr-agent/          PR-Agent configuration (configuration.toml)
  nginx/             Reverse proxy config
  prometheus/        Metrics scraping config
  grafana/           Dashboard provisioning
ci-templates/        GitLab CI and Gitea Actions pipeline examples
scripts/             Setup, healthcheck, triage, and upload utilities
```

## License

[Apache License 2.0](LICENSE)
