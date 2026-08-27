#!/usr/bin/env bash
# Build and start BoardLens. Run from ~/BoardAgent/deploy on the server.
#
# Checks the things that produce confusing failures later - a missing secret, a
# hostname that does not resolve to this machine - before spending five minutes
# on a build.
set -euo pipefail

cd "$(dirname "$0")"

red()   { printf '\033[31m%s\033[0m\n' "$1"; }
green() { printf '\033[32m%s\033[0m\n' "$1"; }
info()  { printf '\033[36m==> %s\033[0m\n' "$1"; }

if [ ! -f .env ]; then
    red "No .env here. Create one first:"
    echo "  cp .env.prod.example .env && nano .env"
    exit 1
fi

set -a; . ./.env; set +a

info "Checking configuration"
MISSING=0
for var in BOARDLENS_HOSTNAME BOARDLENS_ENCRYPTION_KEY BOARDLENS_JWT_SECRET \
           BOARDLENS_BOOTSTRAP_EMAIL BOARDLENS_BOOTSTRAP_PASSWORD; do
    if [ -z "${!var:-}" ]; then
        red "    $var is empty in .env"
        MISSING=1
    fi
done

# A provider key is required, and a leftover placeholder is worse than nothing:
# the app ignores it and then reports having no credentials at all.
if [ -z "${GEMINI_API_KEY:-}${ANTHROPIC_API_KEY:-}${GROQ_API_KEY:-}" ]; then
    red "    No model provider key set (GEMINI_API_KEY, ANTHROPIC_API_KEY or GROQ_API_KEY)"
    MISSING=1
fi
[ "$MISSING" = "1" ] && { echo; red "Fix .env, then run this again."; exit 1; }
green "    all required values present"

info "Checking DNS for $BOARDLENS_HOSTNAME"
PUBLIC_IP=$(curl -fsS --max-time 10 https://api.ipify.org || echo "")
RESOLVED=$(getent hosts "$BOARDLENS_HOSTNAME" | awk '{print $1}' | head -1 || echo "")
if [ -z "$RESOLVED" ]; then
    red "    $BOARDLENS_HOSTNAME does not resolve yet."
    echo "    Point an A record at ${PUBLIC_IP:-the public IP of this server} and wait a few minutes."
    echo "    Continuing anyway - but the HTTPS certificate will fail until DNS is right."
elif [ -n "$PUBLIC_IP" ] && [ "$RESOLVED" != "$PUBLIC_IP" ]; then
    red "    $BOARDLENS_HOSTNAME resolves to $RESOLVED, but this server is $PUBLIC_IP."
    echo "    The certificate will fail until the A record points here."
    echo "    Continuing anyway."
else
    green "    resolves to this server ($RESOLVED)"
fi

info "Building (first run takes 3-6 minutes)"
docker compose -f docker-compose.prod.yml build

info "Starting"
docker compose -f docker-compose.prod.yml up -d

info "Waiting for the application"
for i in $(seq 1 60); do
    if docker compose -f docker-compose.prod.yml exec -T boardlens \
        python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" \
        >/dev/null 2>&1; then
        green "    up"
        break
    fi
    sleep 2
done

echo
docker compose -f docker-compose.prod.yml logs boardlens 2>&1 | grep -E "provider=|ready" | tail -2 || true
echo
green "BoardLens is running at https://$BOARDLENS_HOSTNAME"
echo
echo "Sign in as: $BOARDLENS_BOOTSTRAP_EMAIL"
echo
echo "The certificate is issued on the first request, so the very first page"
echo "load can take a few seconds. If it does not come up, check:"
echo "  docker compose -f docker-compose.prod.yml logs caddy | tail -30"
