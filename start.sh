#!/usr/bin/env bash
# INTERCEPT - Production Startup Script
#
# Starts INTERCEPT with gunicorn + gevent for production use.
# Falls back to Flask dev server if gunicorn is not installed.
#
# Requires sudo for SDR, WiFi monitor mode, and Bluetooth access.
#
# Usage:
#   sudo ./start.sh                  # Default: 0.0.0.0:5050
#   sudo ./start.sh -p 8080          # Custom port
#   sudo ./start.sh --https          # HTTPS with self-signed cert
#   sudo ./start.sh --debug          # Debug mode (Flask dev server)
#   sudo ./start.sh --check-deps     # Check dependencies and exit

set -euo pipefail

# ── Resolve Python from venv or system ───────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$SCRIPT_DIR/venv/bin/python" ]]; then
    PYTHON="$SCRIPT_DIR/venv/bin/python"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
    PYTHON="$VIRTUAL_ENV/bin/python"
else
    PYTHON="$(command -v python3 || command -v python)"
fi

# ── Defaults (can be overridden by env vars or CLI flags) ────────────────────
HOST="${INTERCEPT_HOST:-0.0.0.0}"
PORT="${INTERCEPT_PORT:-5050}"
DEBUG=0
HTTPS=0
CHECK_DEPS=0

# ── Parse CLI arguments ─────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -H|--host)
            HOST="$2"
            shift 2
            ;;
        -d|--debug)
            DEBUG=1
            shift
            ;;
        --https)
            HTTPS=1
            shift
            ;;
        --check-deps)
            CHECK_DEPS=1
            shift
            ;;
        -h|--help)
            echo "Usage: start.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -p, --port PORT    Port to listen on (default: 5050)"
            echo "  -H, --host HOST    Host to bind to (default: 0.0.0.0)"
            echo "  -d, --debug        Run in debug mode (Flask dev server)"
            echo "  --https            Enable HTTPS with self-signed certificate"
            echo "  --check-deps       Check dependencies and exit"
            echo "  -h, --help         Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# ── Export for config.py ─────────────────────────────────────────────────────
export INTERCEPT_HOST="$HOST"
export INTERCEPT_PORT="$PORT"

# ── Dependency check (delegate to intercept.py) ─────────────────────────────
if [[ "$CHECK_DEPS" -eq 1 ]]; then
    exec "$PYTHON" intercept.py --check-deps
fi

# ── Debug mode always uses Flask dev server ──────────────────────────────────
if [[ "$DEBUG" -eq 1 ]]; then
    echo "[INTERCEPT] Starting in debug mode (Flask dev server)..."
    export INTERCEPT_DEBUG=1
    exec "$PYTHON" intercept.py --host "$HOST" --port "$PORT" --debug
fi

# ── HTTPS certificate generation ────────────────────────────────────────────
CERT_DIR="certs"
CERT_FILE="$CERT_DIR/intercept.crt"
KEY_FILE="$CERT_DIR/intercept.key"

if [[ "$HTTPS" -eq 1 ]]; then
    if [[ ! -f "$CERT_FILE" || ! -f "$KEY_FILE" ]]; then
        echo "[INTERCEPT] Generating self-signed SSL certificate..."
        mkdir -p "$CERT_DIR"
        openssl req -x509 -newkey rsa:2048 \
            -keyout "$KEY_FILE" -out "$CERT_FILE" \
            -days 365 -nodes \
            -subj '/CN=intercept/O=INTERCEPT/C=US' 2>/dev/null
        echo "[INTERCEPT] SSL certificate generated: $CERT_FILE"
    else
        echo "[INTERCEPT] Using existing SSL certificate: $CERT_FILE"
    fi
fi

# ── Detect gunicorn + gevent ─────────────────────────────────────────────────
HAS_GUNICORN=0
HAS_GEVENT=0

if "$PYTHON" -c "import gunicorn" 2>/dev/null; then
    HAS_GUNICORN=1
fi
if "$PYTHON" -c "import gevent" 2>/dev/null; then
    HAS_GEVENT=1
fi

# ── Start the server ─────────────────────────────────────────────────────────
if [[ "$HAS_GUNICORN" -eq 1 && "$HAS_GEVENT" -eq 1 ]]; then
    echo "[INTERCEPT] Starting production server (gunicorn + gevent)..."
    echo "[INTERCEPT] Listening on ${HOST}:${PORT}"

    GUNICORN_ARGS=(
        -c "$SCRIPT_DIR/gunicorn.conf.py"
        -k gevent
        -w 1
        --timeout 300
        --graceful-timeout 5
        --worker-connections 1000
        --bind "${HOST}:${PORT}"
        --access-logfile -
        --error-logfile -
    )

    if [[ "$HTTPS" -eq 1 ]]; then
        GUNICORN_ARGS+=(--certfile "$CERT_FILE" --keyfile "$KEY_FILE")
        echo "[INTERCEPT] HTTPS enabled"
    fi

    exec "$PYTHON" -m gunicorn "${GUNICORN_ARGS[@]}" app:app
else
    if [[ "$HAS_GUNICORN" -eq 0 ]]; then
        echo "[INTERCEPT] gunicorn not found — falling back to Flask dev server"
    fi
    if [[ "$HAS_GEVENT" -eq 0 ]]; then
        echo "[INTERCEPT] gevent not found — falling back to Flask dev server"
    fi
    echo "[INTERCEPT] Install with: pip install gunicorn gevent"
    echo ""

    FLASK_ARGS=(--host "$HOST" --port "$PORT")
    if [[ "$HTTPS" -eq 1 ]]; then
        FLASK_ARGS+=(--https)
    fi

    exec "$PYTHON" intercept.py "${FLASK_ARGS[@]}"
fi
