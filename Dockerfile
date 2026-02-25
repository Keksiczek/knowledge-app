# ── Stage 1: Python dependencies ─────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for document processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libmagic1 \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim

LABEL maintainer="Knowledge App"
LABEL description="Offline document intelligence with local LLM"

# Runtime system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy backend source
COPY backend/ ./backend/

# Copy frontend (served by FastAPI as static files)
COPY frontend/ ./frontend/

# Copy config
COPY config.yaml ./

# Directories that will be bind-mounted or used as volumes
RUN mkdir -p backend/uploads backend/data

# Non-root user
RUN useradd -m -u 1000 knowledge && chown -R knowledge:knowledge /app
USER knowledge

EXPOSE 8000

# Change into backend dir so relative paths in config.yaml resolve correctly
WORKDIR /app/backend

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
