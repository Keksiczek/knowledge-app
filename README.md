# Knowledge App

Offline-first document intelligence powered by a **local LLM** (Ollama, LM Studio, or text-generation-webui).

Upload PDFs, DOCX, TXT, Markdown, or PPTX files and get:

| Feature | Endpoint |
|---|---|
| Summarise (paragraph / bullets / executive) | `POST /api/v1/summarize` |
| Key concepts, sentences & topics | `POST /api/v1/highlights` |
| Presentation outline (Markdown or PPTX) | `POST /api/v1/presentation` |
| RAG Q&A – ask anything about the doc | `POST /api/v1/ask` |
| Ingest raw text directly | `POST /api/v1/ingest_text` |

All processing runs **100 % locally** — no data ever leaves your machine.

---

## Project structure

```
knowledge-app/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Typed settings (reads config.yaml)
│   │   ├── database.py          # SQLite helpers & schema
│   │   ├── routers/
│   │   │   ├── upload.py        # File upload, document management, ingest_text
│   │   │   ├── summarize.py     # /api/v1/summarize
│   │   │   ├── highlights.py    # /api/v1/highlights
│   │   │   ├── presentation.py  # /api/v1/presentation
│   │   │   ├── ask.py           # /api/v1/ask  (RAG)
│   │   │   └── models.py        # /api/v1/models (Ollama model management)
│   │   ├── services/
│   │   │   ├── text_extraction.py  # PDF / DOCX / PPTX -> plain text
│   │   │   ├── llm_service.py      # Unified LLM client + prompt templates
│   │   │   └── rag_service.py      # Chunking, embedding, cosine retrieval
│   │   └── utils/
│   │       └── token_counter.py    # Lightweight token estimation
│   └── requirements.txt
├── frontend/
│   ├── index.html               # Single-page application
│   ├── style.css                # Dark-mode UI styles
│   └── app.js                   # Vanilla JS – no build step needed
├── config.yaml                  # LLM backend, DB, and RAG settings
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Quick start (local development)

### Prerequisites

| Tool | Purpose |
|---|---|
| Python 3.10+ | Backend runtime |
| Ollama (https://ollama.com) | Local LLM inference |
| (Optional) Tesseract OCR | Scanned PDF extraction |

### 1 – Start Ollama and pull a model

```bash
ollama serve                        # start the Ollama daemon
ollama pull llama3.2                # or mistral, phi3, gemma2, etc.
```

### 2 – Configure the app

Edit `config.yaml` at the repo root:

```yaml
llm:
  backend: "ollama"
  ollama:
    model: "llama3.2"         # must match what you pulled
```

### 3 – Install Python dependencies

```bash
cd backend
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4 – Run the backend

```bash
# from the backend/ directory
uvicorn app.main:app --reload --port 8000
```

### 5 – Open the frontend

Open `frontend/index.html` directly in your browser **or** serve it with any static server:

```bash
# from the frontend/ directory
python -m http.server 8080
# then visit http://localhost:8080
```

> **Tip:** When running the frontend on a different port, make sure `http://localhost:8080`
> is listed under `app.cors_origins` in `config.yaml`.

---

## Docker (all-in-one)

```bash
# Build and start
docker-compose up --build

# The app is now available at http://localhost:8000
```

> Ollama must be running on your **host** machine (not inside Docker).
> The compose file adds `host.docker.internal` automatically.

---

## LLM backend options

### Ollama (default)
```yaml
llm:
  backend: "ollama"
  ollama:
    base_url: "http://localhost:11434"
    model: "llama3.2"
```

### LM Studio
```yaml
llm:
  backend: "lmstudio"
  lmstudio:
    base_url: "http://localhost:1234/v1"
    model: "local-model"
```

### text-generation-webui
```yaml
llm:
  backend: "textgen"
  textgen:
    base_url: "http://localhost:5000"
```

---

## API reference

All endpoints are under `/api/v1/` and accept/return JSON unless noted.
Interactive Swagger docs: `http://localhost:8000/api/docs`.

### Upload files
```
POST /api/v1/upload
Content-Type: multipart/form-data
Body: files[] (one or more; PDF, DOCX, TXT, MD, PPTX; max 50 MB each)

Response 202:
{ "documents": [ { "id": "...", "status": "pending", "original_name": "...", ... } ] }
```

### Ingest raw text
```
POST /api/v1/ingest_text
{
  "text": "...",
  "title": "optional title",
  "external_id": "optional-ref",
  "source": "hub|teams|email|...",
  "language": "cs|en|auto"
}

Response 200:
{
  "id": "...",
  "status": "ready",
  "title": "...",
  "external_id": "...",
  "source": "...",
  "language": "..."
}
```

### List / get / delete documents
```
GET    /api/v1/documents
GET    /api/v1/documents/{id}
DELETE /api/v1/documents/{id}
```

Document objects include: `id`, `original_name`, `file_format`, `file_size`,
`status` (`pending|processing|ready|error`), `text_length`, `token_count`,
`external_id`, `source`, `tags`, `language`, `uploaded_at`.

### Reprocess a failed document
```
POST /api/v1/documents/{id}/reprocess

Response 202: { "id": "...", "status": "pending" }
```

### Summarise
```
POST /api/v1/summarize
{ "document_id": "...", "style": "paragraph|bullets|executive", "language": "en|cs" }

Response: { "document_id": "...", "style": "...", "summary": "...", "truncated": false, "cached": false }
```

### Highlights
```
POST /api/v1/highlights
{ "document_id": "...", "language": "en|cs" }

Response: { "key_concepts": [...], "key_sentences": [...], "topics": [...], "truncated": false, "cached": false }
```

### Presentation
```
POST /api/v1/presentation
{ "document_id": "...", "format": "markdown|pptx", "language": "en|cs" }

Response (markdown): { "markdown": "...", "outline": {...}, "truncated": false, "cached": false }
Response (pptx):     binary .pptx file (Content-Disposition: attachment)
```

### Ask (RAG Q&A)
```
POST /api/v1/ask
{ "document_id": "...", "question": "What is the main finding?" }

Response: { "answer": "...", "sources_used": 5, "cached": false }
```

### Model management (Ollama)
```
GET  /api/v1/models/available   – list locally available models
POST /api/v1/models/switch      – { "model": "phi3:latest" }
GET  /api/v1/models/status      – ping Ollama, return current backend/model
```

### Health check
```
GET /api/v1/health

Response:
{
  "status": "ok",
  "llm_backend": "ollama",
  "llm_model": "qwen2.5:latest",
  "db_engine": "sqlite",
  "embeddings_enabled": true,
  "documents": 42,
  "chunks": 1567,
  "storage_used_mb": 23.4
}
```

### Authentication (optional)

When `security.api_key` is set in `config.yaml`, all `/api/v1/*` endpoints
(except `/api/v1/health`) require the header:

```
X-API-Key: <your-key>
```

A missing or wrong key returns `401 Unauthorized`.

---

## Environment variables

All settings can be overridden via environment variables (highest priority):

| Variable | Overrides | Example |
|---|---|---|
| `KNOWLEDGE_CONFIG` | Path to `config.yaml` | `/etc/knowledge/config.yaml` |
| `KNOWLEDGE_APP_LLM_MODEL` | `llm.ollama.model` | `phi3:latest` |
| `KNOWLEDGE_APP_DB_PATH` | `database.path` | `/data/knowledge.db` |
| `KNOWLEDGE_APP_PORT` | `app.port` | `9000` |

Relative paths in `config.yaml` are resolved from the repository root.

```bash
# Example: use a custom DB location
KNOWLEDGE_APP_DB_PATH=/tmp/test.db docker-compose up
```

---

## Adding new analysis types

1. Create `backend/app/routers/my_analysis.py` with a new `APIRouter`.
2. Add a prompt-builder function in `llm_service.py`.
3. Register the router in `main.py`:
   ```python
   from .routers import my_analysis
   app.include_router(my_analysis.router)
   ```
4. Add a UI tab in `frontend/index.html` and handle it in `app.js`.

The caching layer (`database.py`) works for any task name automatically.

---

## Supported file formats

| Format | Library | Notes |
|---|---|---|
| PDF | pypdf | Text layer; OCR fallback via pytesseract |
| DOCX | python-docx | Paragraphs + tables |
| TXT / MD | built-in | UTF-8 |
| PPTX | python-pptx | Slide text + speaker notes |

---

## Nastavení pro Intel Mac

Intel Mac spouští Ollama na CPU (bez GPU akcelerace). Doporučujeme modely do 7B parametrů.

### Doporučené modely

| Model | Velikost | Poznámka |
|-------|----------|----------|
| qwen2.5:latest | 7B | Výchozí, výborný na češtinu i angličtinu |
| phi3:latest | 3.8B | Nejrychlejší, vhodný pro Mac s 8GB RAM |
| mistral:latest | 7B | Dobrý na strukturovaný výstup |
| llama3.2:3b | 3B | Odlehčený, rychlejší inference |

### Nedoporučujeme na Intel Mac

- Modely 13B+ (příliš pomalé bez GPU)
- qwen2.5:14b, llama3.1:70b, gemma2:27b

### Stažení modelu

```bash
ollama pull qwen2.5:latest
```

### Přepínání modelů za běhu

Modely lze přepínat přímo v UI (záložka **Settings**) bez restartu serveru.
Alternativně přes API:

```bash
curl -X POST http://localhost:8000/api/v1/models/switch \
  -H "Content-Type: application/json" \
  -d '{"model": "phi3:latest"}'
```

### Očekávaná rychlost na Intel Mac (CPU)

- Krátký dokument (< 2 stránky): 3–5 sekund
- Střední dokument (5–10 stránek): 10–30 sekund
- Dlouhý dokument (20+ stránek): 60–180 sekund

---

## License

MIT
