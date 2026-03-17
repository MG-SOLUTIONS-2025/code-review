# Building a fully self-hosted CodeRabbit replacement

**A complete, air-gapped cybersecurity audit pipeline is achievable today using open-source tools, and it pays for itself within 10 months for teams of 50+ developers.** The core stack—PR-Agent for AI code review, Qwen2.5-Coder-32B as the LLM, Semgrep for SAST, Trivy for dependency scanning, Gitleaks for secrets, and DefectDojo for aggregation—covers every major CodeRabbit feature while keeping all code and data on your network. The main tradeoff: CodeRabbit's adaptive learning system and multi-model orchestration are genuinely hard to replicate, but the raw review quality gap has narrowed dramatically as open-source code models now match GPT-4o on standard benchmarks.

---

## The recommended stack at a glance

Before diving into details, here is the complete architecture. Every component is self-hostable, and no outbound internet traffic is required after initial setup.

| Layer | Tool | License | Replaces |
|-------|------|---------|----------|
| AI code review | **PR-Agent v0.31** (Qodo) | Apache 2.0 | CodeRabbit PR summaries, line-by-line review, descriptions |
| LLM inference | **vLLM** or **Ollama** | Apache 2.0 / MIT | CodeRabbit's cloud LLM backend |
| Code model | **Qwen2.5-Coder-32B-Instruct** | Apache 2.0 | GPT-4o/Claude used by CodeRabbit |
| SAST | **Semgrep CE** + **SonarQube Community** | LGPL 2.1 / LGPL | CodeRabbit's security scanning |
| Secret detection | **Gitleaks** + **TruffleHog v3** | MIT / AGPL-3.0 | CodeRabbit's secret detection |
| Dependency scanning | **Trivy** | Apache 2.0 | Dependency vulnerability alerts |
| SBOM generation | **Syft** | Apache 2.0 | Software bill of materials |
| Dependency updates | **Renovate Bot** | AGPL-3.0 | Dependabot-like auto-PRs |
| Finding aggregation | **DefectDojo** | BSD 3-Clause | Security dashboard and tracking |
| CI/CD | **GitLab CI** or **Gitea Actions** | — | Pipeline orchestration |

```
┌──────────────┐    webhook     ┌──────────────┐    API call     ┌─────────────────┐
│  GitLab /    │ ─────────────→ │  PR-Agent    │ ──────────────→ │  vLLM / Ollama  │
│  Gitea       │ ←───────────── │  (Docker)    │ ←────────────── │  Qwen2.5-Coder  │
│              │  MR comments   │              │   LLM response  │  32B-Instruct   │
└──────┬───────┘                └──────────────┘                 └────────┬────────┘
       │ CI pipeline                                                      │
       ▼                                                            ┌─────┴─────┐
┌──────────────────────────────────────────┐                       │ GPU Server │
│  Parallel scan jobs:                      │                       │ L40S 48GB  │
│  Semgrep │ Gitleaks │ Trivy │ SonarQube  │                       └───────────┘
└──────────────────────┬───────────────────┘
                       │ upload results
                       ▼
              ┌──────────────────┐
              │   DefectDojo     │
              │   Dashboard      │
              └──────────────────┘
```

---

## AI-powered code review with PR-Agent and self-hosted LLMs

PR-Agent by Qodo (formerly CodiumAI) is the strongest open-source alternative to CodeRabbit's AI review engine. Released under **Apache 2.0**, it provides commands that map directly to CodeRabbit features: `/describe` generates PR summaries and walkthroughs, `/review` performs adjustable-depth code analysis with security and bug detection, `/improve` delivers line-level code suggestions, and `/ask` enables free-form Q&A about any PR. Each command makes a single LLM call, typically completing in **~30 seconds**.

The critical design choice that makes PR-Agent viable for air-gapped deployments is its use of **LiteLLM** as an abstraction layer. This means it can target Ollama, vLLM, or any OpenAI-compatible API endpoint without code modifications. Configuration is straightforward:

```toml
[config]
model = "ollama/qwen2.5-coder:32b"
fallback_models = ["ollama/qwen2.5-coder:32b"]
custom_model_max_tokens = 128000

[ollama]
api_base = "http://your-llm-server:11434"
```

PR-Agent supports **GitLab, Gitea (added in v0.30), GitHub, Bitbucket, and Azure DevOps**. For GitLab integration, you deploy it as a persistent webhook server: create a GitLab user with Reporter role, generate a Personal Access Token with `api` scope, run the Docker container (`codiumai/pr-agent:0.31-gitlab_webhook`), and configure a webhook in GitLab Settings pointing to the PR-Agent host. Auto-triggered commands on every MR are configured via:

```toml
[gitlab]
pr_commands = ["/describe", "/review", "/improve"]
handle_push_trigger = true
push_commands = ["/describe", "/review"]
```

Gitea integration follows the same pattern using the `gitea_app` Docker target and Gitea's webhook settings. PR-Agent posts review comments directly via each platform's REST API, creating threaded inline discussions on specific code lines.

**Other notable tools** include Kodus/Kody (model-agnostic, supports plain-language custom review rules) and CodeDog (PR summarization with scoring). However, PR-Agent's combination of broad platform support, LLM flexibility, and active development (v0.31, February 2026) makes it the clear first choice. One caveat: budget significant debugging time for initial setup—several GitHub issues document configuration quirks with hardcoded defaults and ignored environment variables.

### Choosing the right LLM model

**Qwen2.5-Coder-32B-Instruct is the standout recommendation.** It scores **92.7% on HumanEval** (matching GPT-4o), supports a **128K token context window** (essential for large PR diffs), and ships under the fully permissive **Apache 2.0** license. PR-Agent's own documentation specifically recommends this model for local deployments. At Q4_K_M quantization, it requires roughly **18 GB VRAM**, fitting on a single RTX 4090.

For teams with limited hardware, **Qwen2.5-Coder-7B-Instruct** (84.1% HumanEval, runs on 5 GB VRAM) delivers surprisingly strong results. For maximum quality, **Qwen2.5-Coder-14B** outperforms the 22B CodeStral while needing less hardware. Newer 2025 models like **Devstral Small 2** (24B, 68% SWE-Bench Verified, Apache 2.0) are also strong contenders for agentic coding tasks.

Models to avoid for new deployments: **CodeLlama** (released August 2023, surpassed on every benchmark), **StarCoder2** (lower scores, 16K context limit), and **CodeGemma** (8K context is too small for multi-file reviews). **Codestral** performs well but its MNPL license prohibits production use.

### LLM serving: Ollama vs. vLLM

The choice between serving frameworks depends entirely on team size. **Ollama** offers unmatched simplicity—`ollama pull qwen2.5-coder:32b` and you're running—but processes requests sequentially, degrading to ~15 tokens/sec/user at 10 concurrent requests. **vLLM** uses PagedAttention for continuous batching, delivering **~800 tokens/sec aggregate at 10 concurrent users**—a **19× throughput advantage**. Both expose OpenAI-compatible API endpoints, so switching later requires only changing a URL.

Start with Ollama for prototyping and teams under 10 developers. Move to vLLM when concurrent reviews become a bottleneck. Note that HuggingFace's TGI **entered maintenance mode in December 2025**; the project recommends vLLM or SGLang for new deployments.

---

## Static analysis and secret detection form the security backbone

### Semgrep CE is the primary SAST engine

Semgrep Community Edition runs **fully offline** with no cloud connectivity. The CLI (`semgrep/semgrep:latest` Docker image) scans locally, and rules can be downloaded once and cached. Use `semgrep scan` (not `semgrep ci`) with `--metrics=off` to ensure zero telemetry. It supports **30+ languages** and ships with **2,800+ community rules** covering OWASP Top 10, security audit patterns, and secrets.

The critical limitation of CE is **single-function, single-file analysis only**—cross-function taint tracking was moved to the commercial AppSec Platform in December 2024. This prompted the **OpenGrep fork** (January 2025, LGPL 2.1), which restores cross-function taint analysis for 12 languages. For air-gapped deployments needing deeper analysis, OpenGrep is worth evaluating alongside Semgrep CE.

GitLab CI integration produces artifacts in GitLab's SAST format:

```yaml
semgrep:
  stage: security
  image: semgrep/semgrep:latest
  script:
    - semgrep scan . --config="p/default" --config="p/owasp-top-ten"
      --metrics="off" --gitlab-sast -o gl-sast-report.json
  artifacts:
    reports:
      sast: gl-sast-report.json
```

### SonarQube Community has sharp limitations

SonarQube's **Community Build** (free, LGPL) covers 20+ languages but critically lacks **branch analysis, MR decoration, taint analysis, and secrets detection**—all restricted to the Developer Edition ($2,500+/year). The free tier analyzes only the main branch and processes one scan at a time. The community-maintained **Branch Plugin** adds MR analysis but isn't officially supported. For teams that need MR-level feedback without paying for Developer Edition, Semgrep is the better choice.

### CodeQL is off-limits for private codebases

CodeQL's CLI runs anywhere, but its **license restricts free use to open-source codebases or those hosted on GitHub.com**. Using CodeQL on private repos in GitLab CI without a GitHub Advanced Security license violates terms of service. For a fully self-hosted internal pipeline, **avoid CodeQL**.

### Secret detection requires two complementary tools

**Gitleaks** (MIT, v8.25.x) excels in CI/CD: fast Go binary, 100+ regex patterns, SARIF output, pre-commit hook support. **TruffleHog v3** (AGPL-3.0) adds **700+ credential detectors with active API verification**—it can confirm whether a found secret is actually live. Academic research shows these tools find **many non-overlapping secrets**, so running both maximizes coverage.

For air-gapped environments, TruffleHog's verification feature won't work (it needs outbound API access). Use the `--no-verification` flag and rely on its broader detector set for pattern matching alone.

**detect-secrets** (Apache 2.0) takes a unique baseline approach—ideal for legacy codebases where you want to track only *new* secrets rather than triaging hundreds of historical findings.

---

## Dependency scanning and SBOM generation

### Trivy is the all-in-one workhorse

Trivy (Apache 2.0, v0.69.3) covers **container images, filesystem dependencies, IaC misconfigurations, secrets, licenses, and SBOM generation** in a single binary. It pulls vulnerability data from NVD, GitHub Security Advisories, and distro-specific sources. For air-gapped environments, mirror its OCI-format database to an internal registry using ORAS:

```bash
# On internet-connected transfer machine (scheduled cron):
oras cp ghcr.io/aquasecurity/trivy-db:2 internal-registry:5000/trivy-db:2
oras cp ghcr.io/aquasecurity/trivy-java-db:1 internal-registry:5000/trivy-java-db:1
```

Then configure Trivy in CI to point at the internal registry with `--skip-db-update --offline-scan`. The vulnerability database is ~34 MB compressed and rebuilds every 6 hours upstream.

**Grype** (Apache 2.0) pairs with **Syft** for a clean SBOM-first workflow: Syft generates CycloneDX/SPDX SBOMs, Grype scans them for vulnerabilities. This decoupled approach is valuable when SBOMs need to be shared or audited independently. Grype also supports air-gapped operation by hosting its `listing.json` and database tarballs on an internal HTTP server.

**Snyk cannot work air-gapped**—it fundamentally requires cloud connectivity even with its Broker proxy. **Dependabot is impractical outside GitHub.** The self-hosted alternative for automated dependency update PRs is **Renovate Bot** (AGPL-3.0), which natively supports GitLab, Gitea, and 90+ package managers. Deploy it as a scheduled GitLab CI job that runs `renovate --autodiscover=true` against your internal instance.

For SBOM generation, **Syft** (Apache 2.0) produces the highest-fidelity output in both CycloneDX and SPDX formats. Trivy also generates SBOMs as a secondary capability. Store SBOMs in **OWASP Dependency-Track** for continuous vulnerability monitoring across your entire software portfolio.

---

## Tying everything together with DefectDojo and GitLab CI

### DefectDojo as the central nervous system

Without GitLab Ultimate ($99/user/month), you lose the Security Dashboard, MR security widget, and vulnerability management UI. **DefectDojo** (BSD 3-Clause) fills this gap as an open-source vulnerability aggregation platform with **200+ scanner parsers**, including native support for Semgrep, Gitleaks, Trivy, Bandit, Checkov, and generic SARIF.

Deploy it via Docker Compose in minutes. The key integration point is its REST API: after each CI scan job, upload results with a simple `curl` call to `POST /api/v2/import-scan/`. DefectDojo handles deduplication, severity tracking, trend analysis, and dashboard visualization. It also integrates with Jira and Slack for ticketing and notifications.

### The complete GitLab CI pipeline

This pipeline runs all scanners in parallel, then uploads results to DefectDojo:

```yaml
stages:
  - security_scan
  - ai_review
  - upload_results

# --- SAST ---
semgrep:
  stage: security_scan
  image: semgrep/semgrep:latest
  script:
    - semgrep scan . --config="p/default" --config="p/owasp-top-ten"
      --metrics="off" --json -o semgrep_report.json
  artifacts:
    paths: [semgrep_report.json]
    when: always

# --- Secrets ---
gitleaks:
  stage: security_scan
  image:
    name: zricethezav/gitleaks:latest
    entrypoint: [""]
  script:
    - gitleaks detect --source . -f json -r gitleaks_report.json --exit-code 1
  artifacts:
    paths: [gitleaks_report.json]
    when: always
  allow_failure: false  # Hard-fail on leaked secrets

# --- Dependencies ---
trivy:
  stage: security_scan
  image:
    name: aquasec/trivy:latest
    entrypoint: [""]
  variables:
    TRIVY_DB_REPOSITORY: "internal-registry:5000/trivy-db"
    TRIVY_OFFLINE_SCAN: "true"
  script:
    - trivy fs --format json --output trivy_report.json --severity HIGH,CRITICAL .
  artifacts:
    paths: [trivy_report.json]
    when: always

# --- AI Review (webhook to PR-Agent) ---
ai_review:
  stage: ai_review
  image: codiumai/pr-agent:0.31-gitlab_webhook
  variables:
    CONFIG__GIT_PROVIDER: "gitlab"
    CONFIG__MODEL: "ollama/qwen2.5-coder:32b"
    OLLAMA__API_BASE: "http://llm-server.internal:11434"
  script:
    - cd /app && python -m pr_agent.cli
      --pr_url="$CI_MERGE_REQUEST_PROJECT_URL/-/merge_requests/$CI_MERGE_REQUEST_IID"
      review
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# --- Upload to DefectDojo ---
upload_results:
  stage: upload_results
  image: python:3.12-slim
  when: always
  script:
    - pip install requests -q
    - |
      python3 -c "
      import requests, os
      url = os.environ['DEFECTDOJO_URL']
      token = os.environ['DEFECTDOJO_TOKEN']
      eid = os.environ['DEFECTDOJO_ENGAGEMENT_ID']
      headers = {'Authorization': f'Token {token}'}
      scans = {'semgrep_report.json': 'Semgrep JSON Report',
               'gitleaks_report.json': 'Gitleaks Scan',
               'trivy_report.json': 'Trivy Scan'}
      for f, t in scans.items():
          if os.path.exists(f):
              r = requests.post(url, headers=headers,
                  data={'scan_type': t, 'engagement': eid,
                        'minimum_severity': 'Info', 'active': 'true'},
                  files={'file': open(f, 'rb')})
              print(f'{f}: HTTP {r.status_code}')
      "
```

For **Gitea**, the equivalent uses Gitea Actions (GitHub Actions-compatible YAML in `.gitea/workflows/`) with the same Docker images. Gitea Actions supports `actions/checkout@v4` and standard marketplace actions. Alternatively, **Woodpecker CI** (Apache 2.0, fork of Drone) offers first-class Gitea support with its own pipeline syntax.

### When to run what

Run **Gitleaks and Semgrep on every push**—they complete in seconds and catch the most critical issues early. Run **Trivy dependency scanning and AI code review on merge request events only**—these are heavier and most valuable during review. Schedule **full container scans, comprehensive history-based secret audits, and DAST (ZAP) nightly or weekly**—these are expensive operations best suited for off-peak hours.

---

## How does this compare to CodeRabbit feature-by-feature?

CodeRabbit's core strengths are **PR summaries, line-by-line suggestions, conversational review, and adaptive learning**. Here's how each maps:

| CodeRabbit feature | Self-hosted equivalent | Parity |
|---|---|---|
| PR summary + walkthrough | PR-Agent `/describe` | ★★★★ High |
| Line-by-line review | PR-Agent `/review` + `/improve` | ★★★ Good |
| Conversational chat in PR | PR-Agent `/ask` (limited multi-turn) | ★★ Partial |
| Security scanning | Semgrep + Trivy + Gitleaks (more thorough) | ★★★★★ Superior |
| Auto PR descriptions | PR-Agent `/describe` | ★★★★ High |
| Docstring generation | PR-Agent `/add_docs` | ★★★★ High |
| Changelog updates | PR-Agent `/update_changelog` | ★★★★ High |
| Adaptive learning | No equivalent (custom build: 4–8 weeks) | ★ Gap |
| Multi-model orchestration | Single model (manual tuning) | ★ Gap |
| One-click committable fixes | Partial via GitHub suggestion format | ★★ Partial |
| Code graph / cross-file analysis | Requires custom AST tooling | ★ Gap |
| 40+ integrated linters | Mega-Linter + individual tools in CI | ★★★ Good |
| Multi-platform support | PR-Agent: GitLab, Gitea, GitHub, Bitbucket, Azure DevOps | ★★★★★ Equal+ |

**The hardest features to replicate** are CodeRabbit's adaptive learning system (where the bot remembers team preferences and improves over time) and its multi-model orchestration pipeline (automatic model selection per task, model-specific prompt tuning). Building a learning system requires a feedback capture mechanism, embedding storage, and RAG pipeline—estimated at **4–8 weeks of engineering effort**. Most teams will find this unnecessary initially.

**Where self-hosted is objectively stronger**: dedicated SAST/SCA coverage is far more comprehensive. CodeRabbit runs security checks as a supplement to AI review; a self-hosted pipeline with Semgrep, Trivy, SonarQube, and Gitleaks provides deeper, rule-based analysis with configurable policies and compliance reporting. The AI layer adds contextual intelligence on top.

---

## Hardware requirements and cost for air-gapped LLM deployment

### What you actually need to buy

The **Qwen2.5-Coder-32B at Q4_K_M quantization** requires roughly **18 GB VRAM** for weights plus overhead for the KV cache. At 32K context (sufficient for most PR reviews), total VRAM usage is approximately 20–22 GB.

| Team size | Recommended GPU | Model config | Server total | Monthly power |
|-----------|----------------|--------------|-------------|---------------|
| **≤10 devs** | 1× RTX 4090 (24 GB, ~$1,600) | Qwen2.5-Coder-7B Q8 or 32B Q4 | **~$3,600** | ~$48 |
| **~50 devs** | 1× L40S (48 GB, ~$7,500) | Qwen2.5-Coder-32B Q4_K_M via vLLM | **~$11,500** | ~$40 |
| **~100 devs** | 2× L40S or 1× A100 80GB | Qwen2.5-Coder-32B Q8 via vLLM | **~$21,000** | ~$61 |

**CPU-only inference is not viable** for interactive code review. A 7B model on CPU produces ~2–5 tokens/second—a single review would take 2–4 minutes. GPU acceleration is essential.

### The cost math favors self-hosting quickly

At **50 developers**, CodeRabbit Pro costs **$14,400/year** ($24/user/month annual billing). The self-hosted equivalent costs **~$11,500 one-time** for hardware plus **~$480/year** in electricity. **Break-even occurs at approximately 10 months.** Over three years, the self-hosted TCO is roughly **$13,000 versus $43,200** for CodeRabbit—a **70% cost reduction** that improves as team size grows, since self-hosted costs scale with compute rather than headcount.

### Air-gapped deployment workflow

For environments with no internet access, the deployment process is:

1. **On an internet-connected staging machine**: download the model (`ollama pull qwen2.5-coder:32b` or `huggingface-cli download`), the Trivy vulnerability database (via ORAS), Grype database, and all Docker images
2. **Transfer via approved media** (USB, data diode, or sneakernet) to the air-gapped network
3. **Import**: load Ollama volumes (`podman volume import`), push Docker images to internal registry (Harbor), host Trivy DB in internal OCI registry, host Grype DB on internal Nginx
4. **Deploy**: Docker Compose or Kubernetes with NVIDIA GPU Operator for GPU scheduling

Establish a **weekly or biweekly update cadence** for vulnerability databases and a **quarterly cadence** for model updates, each following the same transfer-and-validate workflow.

---

## Conclusion

The self-hosted CodeRabbit replacement is not a single tool—it's a **composable pipeline** where each component is best-in-class for its function. PR-Agent handles the AI review layer with native support for self-hosted LLMs. Semgrep, Gitleaks, and Trivy provide security scanning that actually exceeds CodeRabbit's built-in capabilities. DefectDojo unifies everything into a manageable dashboard. The Qwen2.5-Coder-32B model, running on commodity GPU hardware via vLLM, delivers review quality that matches frontier cloud models on standardized benchmarks.

The two genuine gaps versus CodeRabbit are the **adaptive learning system** and **multi-model orchestration**—features that require custom engineering to replicate. For most teams, these are nice-to-haves rather than essentials, especially given the decisive advantages in data sovereignty, cost predictability, and security scanning depth. Start with Ollama and the 7B model for a proof of concept in an afternoon, then scale to vLLM and the 32B model for production. The entire stack is open-source, Apache 2.0 or similarly licensed, and proven in air-gapped enterprise environments.