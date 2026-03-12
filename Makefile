.PHONY: run dev prod stop logs clean setup check-deps

# ─── Defaults ──────────────────────────────────────────────────────────────────
APP_PORT       ?= 8000
FRONTEND_PORT  ?= 8080
OLLAMA_PORT    ?= 11434
OLLAMA_MODEL   ?= qwen2.5:latest
VENV           := backend/.venv
PYTHON         := $(VENV)/bin/python
PIP            := $(VENV)/bin/pip
UVICORN        := $(VENV)/bin/uvicorn
LOG            := knowledge-app.log

# ─── Primary targets ───────────────────────────────────────────────────────────

## run / dev: start everything in dev mode (auto-reload)
run dev:
	@./run-app.sh dev

## prod: start everything in production mode (no auto-reload)
prod:
	@./run-app.sh prod

## stop: kill backend, frontend, and (optionally) ollama
stop:
	@echo "Stopping services…"
	@pkill -f "uvicorn app.main:app"            2>/dev/null || true
	@pkill -f "python.*http.server.*$(FRONTEND_PORT)" 2>/dev/null || true
	@rm -f .backend.pid .frontend.pid .ollama.pid
	@echo "Done."

## logs: tail the combined log file
logs:
	@tail -f $(LOG)

# ─── Setup / install ───────────────────────────────────────────────────────────

## setup: create venv and install Python deps (no server started)
setup: $(VENV)
	@$(PIP) install --quiet --upgrade pip
	@$(PIP) install -r backend/requirements.txt
	@echo "✔ Python deps installed"

$(VENV):
	python3 -m venv $(VENV)

## check-deps: verify required tools are installed
check-deps:
	@command -v python3  >/dev/null || (echo "✖ python3 missing" && exit 1)
	@command -v ollama   >/dev/null || (echo "✖ ollama missing – see https://ollama.com" && exit 1)
	@command -v curl     >/dev/null || (echo "✖ curl missing" && exit 1)
	@echo "✔ All dependencies present"

# ─── Convenience ──────────────────────────────────────────────────────────────

## pull-model: ensure the default Ollama model is downloaded
pull-model:
	ollama pull $(OLLAMA_MODEL)

## clean: remove venv, pycache, logs, pid files
clean:
	rm -rf $(VENV) backend/__pycache__ backend/app/__pycache__
	find . -name "*.pyc" -delete
	rm -f $(LOG) .backend.pid .frontend.pid .ollama.pid
	@echo "✔ Clean"

## help: list all targets
help:
	@grep -E '^## ' Makefile | sed 's/## /  make /'
