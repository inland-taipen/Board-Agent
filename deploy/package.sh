#!/usr/bin/env bash
# Package the source for transfer to a server.
#
# The project is not in git, and the source is only ~1.5 MB, so a tarball over
# scp is simpler than setting up a repository — and keeps board-pack material
# and secrets off any hosting platform, since both are excluded below.
set -euo pipefail

cd "$(dirname "$0")/.."
OUT="${1:-/tmp/boardlens-deploy.tar.gz}"

tar czf "$OUT" \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='.venv' \
    --exclude='dist' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='.ruff_cache' \
    --exclude='storage' \
    --exclude='out' \
    --exclude='sample_pack' \
    --exclude='.env' \
    --exclude='deploy/.env' \
    backend frontend deploy docs Dockerfile docker-compose.yml Makefile README.md .env.example

echo "Packaged: $OUT  ($(du -h "$OUT" | cut -f1))"
echo
echo "Excluded deliberately: .env (secrets), storage/ (uploaded packs), out/ (exports)."
echo "You will create a fresh .env on the server from deploy/.env.prod.example."
echo
echo "Copy it up with:"
echo "  scp -i <your-key.key> $OUT ubuntu@<SERVER_IP>:~/"
