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
    warn "No NVIDIA GPU detected. Ollama will run on CPU (very slow)."
    warn "Strongly recommend using OLLAMA_MODEL=qwen2.5-coder:7b in .env"
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

# Step 1: Start Ollama
info "Starting Ollama..."
docker compose up -d ollama
info "Waiting for Ollama to be ready..."
until docker compose exec ollama curl -sf http://localhost:11434/api/tags &>/dev/null; do
    sleep 2
done
info "Ollama is ready."

# Step 2: Pull model
MODEL="${OLLAMA_MODEL:-qwen2.5-coder:32b}"
info "Pulling model: $MODEL (this may take a while)..."
docker compose exec ollama ollama pull "$MODEL"

# Step 3: Verify model
info "Verifying model is loaded..."
if docker compose exec ollama curl -sf http://localhost:11434/api/tags | grep -q "$MODEL"; then
    info "Model $MODEL is ready."
else
    error "Model $MODEL not found after pull."
    exit 1
fi

# Step 4: Start all services
info "Starting all services..."
docker compose up -d

# Step 5: Wait for DefectDojo
info "Waiting for DefectDojo to initialize (this takes 1-2 minutes)..."
RETRIES=0
until docker compose exec defectdojo-web curl -sf http://localhost:8080/api/v2/ &>/dev/null || [ $RETRIES -eq 30 ]; do
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
info "Dashboard:   http://localhost:5173"
info "API Gateway: http://localhost:8000"
info "DefectDojo:  http://localhost:8080  (admin / ${DEFECTDOJO_ADMIN_PASSWORD:-changeme})"
info "Ollama:      http://localhost:11434"
info "Nginx Proxy: http://localhost:80"
info ""
info "Next steps:"
info "  1. Log into DefectDojo, create an API token, add it to .env as DEFECTDOJO_API_TOKEN"
info "  2. Configure your git platform webhook to point to http://<this-host>/webhook"
info "  3. Create a DefectDojo product and engagement for your project"
