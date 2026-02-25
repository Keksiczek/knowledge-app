# Knowledge App

Offline-first document intelligence powered by a **local LLM** (Ollama, LM Studio, or text-generation-webui).

Upload PDFs, DOCX, TXT, Markdown, or PPTX files and get:

| Feature | Endpoint |
|---|---|
| Summarise (paragraph / bullets / executive) | `POST /api/summarize` |
| Key concepts, sentences & topics | `POST /api/highlights` |
| Presentation outline (Markdown or PPTX) | `POST /api/presentation` |
| RAG Q&A – ask anything about the doc | `POST /api/ask` |

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
│   │   │   ├── upload.py        # File upload & document management
│   │   │   ├── summarize.py     # /api/summarize
│   │   │   ├── highlights.py    # /api/highlights
│   │   │   ├── presentation.py  # /api/presentation
│   │   │   └── ask.py           # /api/ask  (RAG)
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

All endpoints accept and return JSON unless otherwise noted.

### Upload files
```
POST /api/upload
Content-Type: multipart/form-data
Body: files[] (one or more)

Response 202: { "documents": [ { "id": "...", "status": "pending", ... } ] }
```

### List / get / delete documents
```
GET    /api/documents
GET    /api/documents/{id}
DELETE /api/documents/{id}
```

### Summarise
```
POST /api/summarize
{ "document_id": "...", "style": "paragraph|bullets|executive" }
```

### Highlights
```
POST /api/highlights
{ "document_id": "..." }
Response: { "key_concepts": [...], "key_sentences": [...], "topics": [...] }
```

### Presentation
```
POST /api/presentation
{ "document_id": "...", "format": "markdown|pptx" }
```

### Ask (RAG Q&A)
```
POST /api/ask
{ "document_id": "...", "question": "What is the main finding?" }
Response: { "answer": "...", "sources_used": 5, "cached": false }
```

### Health check
```
GET /api/health
Response: { "status": "ok", "llm_backend": "ollama", "db_engine": "sqlite" }
```

Interactive API docs are available at `http://localhost:8000/api/docs`.

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
curl -X POST http://localhost:8000/api/models/switch \
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
