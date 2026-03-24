#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Check .env exists
if [ ! -f .env ]; then
    info "Creating .env from .env.example..."
    cp .env.example .env
    warn "Edit .env with your actual configuration before proceeding."
    exit 1
fi

# shellcheck source=/dev/null
source .env

# Check Docker
if ! command -v docker &>/dev/null; then
    error "Docker is not installed. Please install Docker first."
    exit 1
fi

# Check GPU availability
GPU_AVAILABLE=false
if command -v nvidia-smi &>/dev/null; then
    if nvidia-smi &>/dev/null; then
        GPU_AVAILABLE=true
        GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
        info "GPU detected with ${GPU_MEM}MB VRAM"
        if [ "${GPU_MEM:-0}" -lt 20000 ]; then
            warn "GPU has less than 20GB VRAM. Recommending 7B model instead of 32B."
            warn "Set OLLAMA_MODEL=qwen2.5-coder:7b in .env"
        fi
    fi
fi

if [ "$GPU_AVAILABLE" = false ]; then
    warn "No NVIDIA GPU detected. LLM will run on CPU (very slow)."
    warn "Strongly recommend using a smaller model in .env"
fi

# Generate htpasswd for nginx basic auth
info "Generating nginx basic auth..."
HTPASSWD_FILE="$PROJECT_DIR/config/nginx/.htpasswd"
if command -v htpasswd &>/dev/null; then
    htpasswd -cb "$HTPASSWD_FILE" "${BASIC_AUTH_USER:-admin}" "${BASIC_AUTH_PASSWORD:-changeme}"
else
    # Fallback: use openssl
    HASH=$(openssl passwd -apr1 "${BASIC_AUTH_PASSWORD:-changeme}")
    echo "${BASIC_AUTH_USER:-admin}:${HASH}" > "$HTPASSWD_FILE"
fi

ENGINE="${INFERENCE_ENGINE:-ollama}"
COMPOSE_PROFILES=""

# Step 1: Start LLM engine
if [ "$ENGINE" = "vllm" ]; then
    info "Starting vLLM inference engine..."
    COMPOSE_PROFILES="--profile vllm"
    docker compose $COMPOSE_PROFILES up -d vllm
    info "Waiting for vLLM to load model (this may take several minutes)..."
    until docker compose exec vllm curl -sf http://localhost:8000/v1/models &>/dev/null; do
        sleep 5
    done
    info "vLLM is ready."
else
    info "Starting Ollama..."
    docker compose up -d ollama
    info "Waiting for Ollama to be ready..."
    until docker compose exec ollama curl -sf http://localhost:11434/api/tags &>/dev/null; do
        sleep 2
    done
    info "Ollama is ready."

    # Pull model
    MODEL="${OLLAMA_MODEL:-qwen2.5-coder:32b}"
    info "Pulling model: $MODEL (this may take a while)..."
    docker compose exec ollama ollama pull "$MODEL"

    # Verify model
    info "Verifying model is loaded..."
    if docker compose exec ollama curl -sf http://localhost:11434/api/tags | grep -q "$MODEL"; then
        info "Model $MODEL is ready."
    else
        error "Model $MODEL not found after pull."
        exit 1
    fi
fi

# Step 2: Optional TabbyML
if [ "${ENABLE_TABBY:-false}" = "true" ]; then
    info "Starting TabbyML for code intelligence..."
    COMPOSE_PROFILES="${COMPOSE_PROFILES} --profile tabby"
    docker compose --profile tabby up -d tabby
    info "Waiting for TabbyML to be ready..."
    RETRIES=0
    until docker compose exec tabby curl -sf http://localhost:8080/v1/health &>/dev/null || [ $RETRIES -eq 30 ]; do
        sleep 5
        RETRIES=$((RETRIES + 1))
    done
    if [ $RETRIES -eq 30 ]; then
        warn "TabbyML may still be initializing. Check: docker compose logs tabby"
    else
        info "TabbyML is ready."
    fi
fi

# Step 3: Start all services
info "Starting all services..."
docker compose $COMPOSE_PROFILES up -d

# Step 4: Wait for DefectDojo
info "Waiting for DefectDojo to initialize (this takes 1-2 minutes)..."
RETRIES=0
until docker compose exec defectdojo-web curl -sf http://localhost:8081/api/v2/ &>/dev/null || [ $RETRIES -eq 30 ]; do
    sleep 5
    RETRIES=$((RETRIES + 1))
done

if [ $RETRIES -eq 30 ]; then
    warn "DefectDojo may still be initializing. Check: docker compose logs defectdojo-web"
else
    info "DefectDojo is ready at http://localhost:8080"
fi

info ""
info "=== Setup Complete ==="
info "Engine:      ${ENGINE}"
info "Dashboard:   http://localhost:3102        (via nginx proxy)"
info "API Gateway: http://localhost:8000         (direct)"
info "DefectDojo:  http://localhost:3102/defectdojo/  (admin / ${DEFECTDOJO_ADMIN_PASSWORD:-changeme})"
if [ "$ENGINE" = "vllm" ]; then
    info "vLLM:        http://localhost:8001"
else
    info "Ollama:      http://localhost:11434"
fi
if [ "${ENABLE_TABBY:-false}" = "true" ]; then
    info "TabbyML:     http://localhost:8082"
fi
info "Grafana:     http://localhost:3001         (admin / ${GRAFANA_ADMIN_PASSWORD:-admin})"
info "Prometheus:  http://localhost:9090"
info ""
info "Next steps:"
info "  1. Log into DefectDojo, create an API token, add it to .env as DEFECTDOJO_API_TOKEN"
info "  2. Restart: docker compose restart api-gateway"
info "  3. Configure your git platform webhook to point to http://<this-host>:3102/api/webhook"
info "  4. Create a DefectDojo product and engagement for your project"
info ""
info "To verify everything is healthy:"
info "  python3 scripts/healthcheck.py"
