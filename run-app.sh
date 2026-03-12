#!/usr/bin/env bash
# run-app.sh – Knowledge App launcher
# Usage: ./run-app.sh [dev|prod]   (default: dev)
set -euo pipefail

# ─── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

# ─── Config (override via .env or env vars) ─────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-dev}"
APP_PORT="${KNOWLEDGE_APP_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:latest}"
LOG_FILE="${SCRIPT_DIR}/knowledge-app.log"
BACKEND_PID_FILE="${SCRIPT_DIR}/.backend.pid"
FRONTEND_PID_FILE="${SCRIPT_DIR}/.frontend.pid"
OLLAMA_PID_FILE="${SCRIPT_DIR}/.ollama.pid"

# ─── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${RESET} $*" | tee -a "$LOG_FILE"; }
ok()   { echo -e "${GREEN}✔${RESET} $*" | tee -a "$LOG_FILE"; }
warn() { echo -e "${YELLOW}⚠${RESET} $*" | tee -a "$LOG_FILE"; }
die()  { echo -e "${RED}✖ ERROR:${RESET} $*" | tee -a "$LOG_FILE"; exit 1; }

wait_for() {
  local url="$1" label="$2" retries="${3:-30}"
  log "Waiting for ${label} at ${url}…"
  for i in $(seq 1 "$retries"); do
    if curl -sf --max-time 2 "$url" > /dev/null 2>&1; then
      ok "${label} is up"
      return 0
    fi
    sleep 1
  done
  die "${label} did not become ready after ${retries}s"
}

kill_pid_file() {
  local pid_file="$1" label="$2"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      log "Stopping ${label} (PID ${pid})…"
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
  fi
}

# ─── Graceful shutdown ─────────────────────────────────────────────────────────
cleanup() {
  echo ""
  log "Shutting down Knowledge App…"
  kill_pid_file "$FRONTEND_PID_FILE" "frontend"
  kill_pid_file "$BACKEND_PID_FILE"  "backend"
  # Only stop Ollama if we started it
  if [[ -f "$OLLAMA_PID_FILE" ]]; then
    kill_pid_file "$OLLAMA_PID_FILE" "ollama"
  fi
  log "Bye 👋"
}
trap cleanup EXIT INT TERM

# ─── Banner ────────────────────────────────────────────────────────────────────
echo "" | tee -a "$LOG_FILE"
echo -e "${BOLD}${CYAN}╔══════════════════════════════════╗${RESET}" | tee -a "$LOG_FILE"
echo -e "${BOLD}${CYAN}║   Knowledge App  [${MODE}]          ║${RESET}" | tee -a "$LOG_FILE"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════╝${RESET}" | tee -a "$LOG_FILE"
log "Log file: ${LOG_FILE}"

# ─── Load .env (optional) ──────────────────────────────────────────────────────
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  log "Loading .env…"
  # Export only simple KEY=VALUE lines; skip comments and blanks
  set -o allexport
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.env"
  set +o allexport
elif [[ -f "${SCRIPT_DIR}/.env.example" ]]; then
  warn ".env not found – using defaults. Copy .env.example to .env to customise."
fi

# ─── Prerequisites check ───────────────────────────────────────────────────────
log "Checking prerequisites…"

command -v python3 >/dev/null 2>&1 || die "python3 is not installed"
command -v pip    >/dev/null 2>&1 || command -v pip3 >/dev/null 2>&1 || die "pip is not installed"
command -v curl   >/dev/null 2>&1 || die "curl is not installed"

if ! command -v ollama >/dev/null 2>&1; then
  die "ollama is not installed. Install from https://ollama.com"
fi
ok "Prerequisites OK"

# ─── Git pull ──────────────────────────────────────────────────────────────────
if [[ "${SKIP_GIT_PULL:-}" != "1" ]]; then
  log "Pulling latest code…"
  git -C "$SCRIPT_DIR" pull --ff-only 2>&1 | tee -a "$LOG_FILE" || warn "git pull failed (continuing with local version)"
fi

# ─── Python venv + deps ────────────────────────────────────────────────────────
VENV_DIR="${SCRIPT_DIR}/backend/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  log "Creating Python virtual environment…"
  python3 -m venv "$VENV_DIR"
fi

log "Installing / verifying Python dependencies…"
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -r "${SCRIPT_DIR}/backend/requirements.txt" 2>&1 | tee -a "$LOG_FILE"
ok "Python deps ready"

# ─── Ollama: start daemon if not running ───────────────────────────────────────
if curl -sf "http://localhost:${OLLAMA_PORT}/api/version" > /dev/null 2>&1; then
  ok "Ollama already running on port ${OLLAMA_PORT}"
else
  log "Starting Ollama daemon…"
  OLLAMA_HOST="0.0.0.0:${OLLAMA_PORT}" ollama serve >> "$LOG_FILE" 2>&1 &
  echo $! > "$OLLAMA_PID_FILE"
  wait_for "http://localhost:${OLLAMA_PORT}/api/version" "Ollama" 30
fi

# ─── Ollama: pull model ────────────────────────────────────────────────────────
log "Ensuring model ${OLLAMA_MODEL} is available…"
if ollama list 2>/dev/null | grep -qF "${OLLAMA_MODEL%:*}"; then
  ok "Model ${OLLAMA_MODEL} already pulled"
else
  log "Pulling ${OLLAMA_MODEL} (this may take a while on first run)…"
  ollama pull "${OLLAMA_MODEL}" 2>&1 | tee -a "$LOG_FILE"
  ok "Model ${OLLAMA_MODEL} ready"
fi

# ─── Kill stale processes ──────────────────────────────────────────────────────
log "Clearing stale processes on ports ${APP_PORT} and ${FRONTEND_PORT}…"
# macOS / Linux compatible
if command -v lsof >/dev/null 2>&1; then
  lsof -ti tcp:"${APP_PORT}"      2>/dev/null | xargs -r kill -9 2>/dev/null || true
  lsof -ti tcp:"${FRONTEND_PORT}" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
fi
# Also kill any stale uvicorn / http.server managed by previous runs
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "python.*http.server.*${FRONTEND_PORT}" 2>/dev/null || true
sleep 0.5

# ─── Start backend ─────────────────────────────────────────────────────────────
log "Starting FastAPI backend (port ${APP_PORT}, mode: ${MODE})…"
cd "${SCRIPT_DIR}/backend"

RELOAD_FLAG=""
[[ "$MODE" == "dev" ]] && RELOAD_FLAG="--reload"

# shellcheck disable=SC2086
"${VENV_DIR}/bin/uvicorn" app.main:app \
  --host 0.0.0.0 \
  --port "${APP_PORT}" \
  ${RELOAD_FLAG} \
  >> "$LOG_FILE" 2>&1 &
echo $! > "$BACKEND_PID_FILE"
cd "$SCRIPT_DIR"

wait_for "http://localhost:${APP_PORT}/api/v1/health" "Backend API" 30

# ─── Start frontend static server ──────────────────────────────────────────────
log "Starting frontend static server (port ${FRONTEND_PORT})…"
cd "${SCRIPT_DIR}/frontend"
python3 -m http.server "${FRONTEND_PORT}" >> "$LOG_FILE" 2>&1 &
echo $! > "$FRONTEND_PID_FILE"
cd "$SCRIPT_DIR"

wait_for "http://localhost:${FRONTEND_PORT}" "Frontend" 15

# ─── Done ──────────────────────────────────────────────────────────────────────
echo "" | tee -a "$LOG_FILE"
echo -e "${GREEN}${BOLD}✅  Knowledge App is ready!${RESET}" | tee -a "$LOG_FILE"
echo -e "   ${BOLD}Frontend:${RESET}  http://localhost:${FRONTEND_PORT}" | tee -a "$LOG_FILE"
echo -e "   ${BOLD}API:${RESET}       http://localhost:${APP_PORT}/api/v1/health" | tee -a "$LOG_FILE"
echo -e "   ${BOLD}Swagger:${RESET}   http://localhost:${APP_PORT}/api/docs" | tee -a "$LOG_FILE"
echo -e "   ${BOLD}Model:${RESET}     ${OLLAMA_MODEL}" | tee -a "$LOG_FILE"
echo -e "   ${BOLD}Logs:${RESET}      ${LOG_FILE}" | tee -a "$LOG_FILE"
echo -e "   ${YELLOW}Press Ctrl+C to stop all services${RESET}" | tee -a "$LOG_FILE"
echo ""

# ─── Wait (keep script alive so trap fires on Ctrl+C) ─────────────────────────
wait
