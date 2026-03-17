#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${1:-$PROJECT_DIR/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

echo "Backing up DefectDojo database..."
docker compose -f "$PROJECT_DIR/docker-compose.yml" exec -T defectdojo-db \
    pg_dump -U defectdojo defectdojo \
    | gzip > "$BACKUP_DIR/defectdojo_${TIMESTAMP}.sql.gz"

echo "Backup saved: $BACKUP_DIR/defectdojo_${TIMESTAMP}.sql.gz"

# Prune backups older than 30 days
find "$BACKUP_DIR" -name "defectdojo_*.sql.gz" -mtime +30 -delete 2>/dev/null || true
echo "Pruned backups older than 30 days."
