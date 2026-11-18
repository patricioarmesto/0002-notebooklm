# NotebookLM Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a local, single-command RAG prototype where users upload PDF/TXT files, index them into Qdrant with Ollama embeddings, and ask questions answered only from those documents with clickable `[Doc N]` citations over SSE streaming.

**Architecture:** Docker Compose runs Postgres, Qdrant and Ollama as stateful services, two one-shot services (`model-pull`, `seed-docs`) that prepare models and seed the real upload endpoint, a FastAPI backend that owns all ingestion/search/answer logic, and a Vite frontend. The backend is the only component that talks to the databases and the LLM; the frontend consumes four JSON/SSE endpoints.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, qdrant-client, pypdf, httpx, Ollama (`llama3.2:3b`, `nomic-embed-text`), React 18, Vite 5, Tailwind CSS 3, Docker Compose.

**Spec:** `docs/decisiones.md`

## Global Constraints

- Backend IA: Python + FastAPI. Frontend: React + Vite + Tailwind.
- Vector DB: Qdrant para chunks. Base de datos: Postgres para documentos y preguntas.
- LLM: Ollama local en Docker, sin APIs pagas. Modelos `llama3.2:3b` (respuestas) y `nomic-embed-text` (embeddings). `OLLAMA_HOST=http://ollama:11434`.
- Chunks de 500 caracteres con overlap de 50; metadata `{ doc_id, doc_title, chunk_index, page }`.
- Top 4 chunks por pregunta; citas `[Doc N]`; ante ausencia de evidencia, responder exactamente `No lo sé con los documentos disponibles`.
- Streaming token a token con Server-Sent Events.
- Un solo `docker compose up` deja todo andando, con 3 documentos semilla (Bitly, Kafka, System Design).
- No implementar: crawler web, buscador web, fine-tuning, evaluación de RAG, audio overview (podcast), guardrails avanzados.
- Qdrant point IDs must be UUID or unsigned integer: use `uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{chunk_index}")`.

## Review Focus

- PDF with no extractable text → `422` and no chunks/documents persisted. Test: `test_extract_pdf_without_text_raises` in Task 4.
- Question whose answer is absent from the documents → exact `No lo sé con los documentos disponibles`, no invented citation. Test: `test_build_prompt_contains_unknown_rule` in Task 5.
- Re-uploading the same title after a restart → one document row, no duplicated points. Test: `test_document_key_is_normalized` in Task 4.
- Ollama fails mid-stream → SSE `error` event, no half-written answer row. Test: `test_accumulate_answer_is_all_or_nothing` in Task 5.
- Clicking `[Doc 3]` when the citations map has no entry `3` → renders as plain text instead of crashing. Test: `test_split_answer_text_unknown_citation` in Task 6.

---

### Task 1: Compose scaffolding, seed documents and Dockerfiles

**Files:**
- Create: `docker-compose.yml`
- Create: `backend/Dockerfile`, `backend/requirements.txt`
- Create: `frontend/Dockerfile`, `frontend/package.json`, `frontend/index.html`, `frontend/vite.config.ts`, `frontend/tailwind.config.js`, `frontend/postcss.config.js`, `frontend/src/index.css`, `frontend/src/main.tsx`
- Create: `docs/seed/bitly.txt`, `docs/seed/kafka.txt`, `docs/seed/system-design.txt`
- Test: `docker compose config -q`

**Interfaces:**
- Consumes: nothing.
- Produces: `backend` image with `uvicorn main:app`; `frontend` image with `npm run dev -- --host 0.0.0.0`; env vars `DATABASE_URL`, `QDRANT_URL`, `OLLAMA_HOST`, `OLLAMA_LLM_MODEL`, `OLLAMA_EMBED_MODEL`, `COLLECTION_NAME`; seed files at `docs/seed/`.

- [x] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: notebooklm
      POSTGRES_USER: notebooklm
      POSTGRES_PASSWORD: notebooklm
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U notebooklm -d notebooklm"]
      interval: 5s
      timeout: 3s
      retries: 30

  qdrant:
    image: qdrant/qdrant:v1.12.1
    ports:
      - "6333:6333"
    volumes:
      - qdrantdata:/qdrant/storage

  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollamadata:/root/.ollama
    healthcheck:
      test: ["CMD-SHELL", "ollama list > /dev/null 2>&1"]
      interval: 5s
      timeout: 5s
      retries: 30

  model-pull:
    image: ollama/ollama:latest
    environment:
      OLLAMA_HOST: http://ollama:11434
    depends_on:
      ollama:
        condition: service_healthy
    entrypoint: ["/bin/sh", "-c"]
    command: >
      ollama pull nomic-embed-text && ollama pull llama3.2:3b
    restart: "no"

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://notebooklm:notebooklm@postgres:5432/notebooklm
      QDRANT_URL: http://qdrant:6333
      OLLAMA_HOST: http://ollama:11434
      OLLAMA_LLM_MODEL: llama3.2:3b
      OLLAMA_EMBED_MODEL: nomic-embed-text
      COLLECTION_NAME: notebooklm_chunks
    depends_on:
      postgres:
        condition: service_healthy
      qdrant:
        condition: service_started
      model-pull:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD-SHELL", "python -c 'import urllib.request; urllib.request.urlopen(\"http://localhost:8000/health\")'"]
      interval: 5s
      timeout: 3s
      retries: 30

  seed-docs:
    image: curlimages/curl:8.10.1
    volumes:
      - ./docs/seed:/seed:ro
    depends_on:
      backend:
        condition: service_healthy
    entrypoint: ["/bin/sh", "-c"]
    command: >
      for f in /seed/*.txt; do
        echo "Seeding $$f";
        curl --fail --silent --show-error --retry 30 --retry-connrefused --retry-delay 2
          -F "file=@$$f;type=text/plain"
          -F "title=$(basename $$f .txt)"
          http://backend:8000/api/upload > /dev/null || exit 1;
      done
    restart: "no"

  frontend:
    build: ./frontend
    ports:
      - "5173:5173"
    environment:
      VITE_API_URL: http://localhost:8000
    depends_on:
      seed-docs:
        condition: service_completed_successfully

volumes:
  pgdata:
  qdrantdata:
  ollamadata:
```

- [x] **Step 2: Write backend build files**

`backend/requirements.txt`:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
asyncpg==0.30.0
qdrant-client==1.12.1
pypdf==5.1.0
python-multipart==0.0.20
pytest==8.3.4
pytest-asyncio==0.25.0
```

`backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [x] **Step 3: Write frontend build files**

`frontend/package.json`:

```json
{
  "name": "notebooklm-frontend",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build"
  },
  "dependencies": {
    "react": "18.3.1",
    "react-dom": "18.3.1"
  },
  "devDependencies": {
    "@types/react": "18.3.18",
    "@types/react-dom": "18.3.5",
    "@vitejs/plugin-react": "4.3.4",
    "autoprefixer": "10.4.20",
    "postcss": "8.4.49",
    "tailwindcss": "3.4.17",
    "typescript": "5.7.2",
    "vite": "5.4.11"
  }
}
```

`frontend/Dockerfile`:

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="es">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>¿Cómo funciona NotebookLM?</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/vite.config.ts`:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { host: '0.0.0.0', port: 5173 },
})
```

`frontend/tailwind.config.js`:

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: {} },
  plugins: [],
}
```

`frontend/postcss.config.js`:

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

`frontend/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  font-family: ui-sans-serif, system-ui, sans-serif;
}
```

`frontend/src/main.tsx`:

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

- [x] **Step 4: Write the three seed documents**

`docs/seed/bitly.txt`:

```
Bitly: acortador de enlaces

Bitly es un servicio que convierte URLs largas en enlaces cortos. Fue lanzado en 2009 y se usa para compartir enlaces en redes sociales, correos y mensajes donde el espacio es limitado.

Cuando una persona hace clic en un enlace de Bitly, el servicio registra el evento y redirige al usuario a la URL original con un código HTTP 301. Ese registro permite contar clics por día, por país y por referente.

Bitly también ofrece enlaces personalizados con un dominio propio y códigos QR. Los enlaces se pueden editar después de creados sin cambiar la dirección corta, aunque la URL destino sí se puede modificar desde el panel.

El caso de uso típico es una campaña de marketing: se genera un enlace corto por canal y se comparan los clics de cada canal para decidir dónde invertir.
```

`docs/seed/kafka.txt`:

```
Apache Kafka: log de eventos distribuido

Apache Kafka es una plataforma de streaming de eventos. Se originó en LinkedIn y se donó a la Apache Software Foundation. Su unidad central es el topic, un log append-only al que los productores escriben registros y del que los consumidores leen.

Los topics se dividen en particiones. Cada partición es una secuencia ordenada de registros con un offset, y se replica entre brokers para tolerar fallos. El orden está garantizado dentro de una partición, no entre particiones.

Los consumidores se organizan en consumer groups. Kafka reparte las particiones entre los miembros de un grupo, de modo que cada registro se entrega a un solo consumidor por grupo. Para leer el mismo evento varias veces con fines distintos, se usan grupos diferentes.

Kafka se usa para desacoplar productores y consumidores, para construir pipelines de datos y como buffer frente a picos de tráfico. Retiene los mensajes durante un periodo configurable, a diferencia de una cola tradicional que los elimina al consumirlos.
```

`docs/seed/system-design.txt`:

```
System Design: principios para diseñar sistemas a escala

Diseñar un sistema a escala empieza por aclarar los requisitos funcionales y no funcionales: qué debe hacer el sistema, cuántos usuarios tendrá, qué latencia acepta y qué disponibilidad exige.

La primera herramienta es estimar. Calcular órdenes de magnitud de tráfico, almacenamiento y ancho de banda permite decidir entre una sola base de datos y una arquitectura con particionamiento. Una estimación burda bien documentada suele ser más útil que una precisión falsa.

El siguiente paso es separar responsabilidades. Un servicio de lectura con caché, una cola para desacoplar escrituras y un almacenamiento de objetos para archivos grandes son patrones recurrentes. Cada componente debe tener un dueño claro de sus datos.

La disponibilidad se logra con replicación y con degradación controlada: ante la falla de una dependencia externa, el sistema debe seguir respondiendo lo esencial. También hay que medir: sin métricas y trazas, un diseño no se puede operar.

Finalmente, todo diseño es un compromiso. Elegir consistencia fuerte puede aumentar la latencia; elegir consistencia eventual simplifica la escala pero obliga a manejar lecturas obsoletas.
```

- [x] **Step 5: Validate Compose syntax**

Run: `docker compose config -q`
Expected: exit 0. If Docker is not installed in this environment, verify with `python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('docker-compose.yml').read_text())"` and note in the final report that the live smoke test could not be run here.

- [x] **Step 6: Commit**

```bash
git add docker-compose.yml backend frontend docs/seed
git commit -m "feat: add docker compose scaffolding and seed documents"
```

### Task 2: Backend core, database schema and readiness

**Files:**
- Create: `backend/main.py`
- Test: `backend/tests/test_main.py`

**Interfaces:**
- Consumes: env vars from Task 1; `search.py.COLLECTION_NAME` is not imported here to avoid a dependency — `COLLECTION_NAME` is read from env in both modules.
- Produces: `app` (FastAPI), `app.state.pool` (asyncpg.Pool), `app.state.qdrant` (QdrantClient), `app.state.ollama` (str base URL), `app.state.documents` (list of dicts cache used by upload/answer), `GET /health`, `GET /api/ready`, `GET /api/documents`, `GET /api/chunks/{chunk_id}`.

- [x] **Step 1: Write the failing tests**

`backend/tests/test_main.py`:

```python
from fastapi.testclient import TestClient
import main


def test_health_ok():
    client = TestClient(main.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_documents_empty_before_ingest():
    main.app.state.documents = []
    client = TestClient(main.app)
    response = client.get("/api/documents")
    assert response.status_code == 200
    assert response.json() == []


def test_ready_reports_missing_models():
    class FakeQdrant:
        def collection_exists(self, collection_name):
            return True

    class FakePool:
        async def fetchval(self, query):
            return 1

    async def fake_get(url, timeout):
        class R:
            def raise_for_status(self):
                return None

            def json(self):
                return {"models": [{"name": "llama3.2:3b"}]}

        return R()

    main.app.state.pool = FakePool()
    main.app.state.qdrant = FakeQdrant()
    main.httpx_get = fake_get
    client = TestClient(main.app)
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["missing"] == ["model:nomic-embed-text"]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_main.py -q`
Expected: FAIL — `main` module does not exist yet.

- [x] **Step 3: Write `backend/main.py`**

```python
import asyncio
import os
from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://notebooklm:notebooklm@localhost:5432/notebooklm")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "llama3.2:3b")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "notebooklm_chunks")
VECTOR_SIZE = 768

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    source_type TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS questions (
    id SERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS answers (
    id SERIAL PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    text TEXT NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def _connect_with_retry():
    for attempt in range(60):
        try:
            return await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        except Exception:
            if attempt == 59:
                raise
            await asyncio.sleep(1)


async def httpx_get(url, timeout):
    async with httpx.AsyncClient() as client:
        return await client.get(url, timeout=timeout)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await _connect_with_retry()
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
    qdrant = QdrantClient(url=QDRANT_URL, timeout=30)
    if not qdrant.collection_exists(COLLECTION_NAME):
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
    rows = await pool.fetch("SELECT id, title, filename, source_type, chunk_count FROM documents ORDER BY id")
    app.state.pool = pool
    app.state.qdrant = qdrant
    app.state.ollama = OLLAMA_HOST
    app.state.llm_model = LLM_MODEL
    app.state.embed_model = EMBED_MODEL
    app.state.documents = [dict(row) for row in rows]
    yield
    await pool.close()


app = FastAPI(title="NotebookLM local", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/ready")
async def ready():
    missing = []
    try:
        await app.state.pool.fetchval("SELECT 1")
    except Exception:
        missing.append("postgres")
    try:
        if not app.state.qdrant.collection_exists(COLLECTION_NAME):
            missing.append("qdrant:collection")
    except Exception:
        missing.append("qdrant")
    try:
        response = await httpx_get(f"{OLLAMA_HOST}/api/tags", timeout=10)
        response.raise_for_status()
        installed = {m["name"].split(":")[0] for m in response.json().get("models", [])}
        for model in (LLM_MODEL, EMBED_MODEL):
            if model.split(":")[0] not in installed:
                missing.append(f"model:{model}")
    except Exception:
        missing.extend(["ollama", f"model:{LLM_MODEL}", f"model:{EMBED_MODEL}"])
    if missing:
        return JSONResponse(status_code=503, content={"ready": False, "missing": missing})
    return {"ready": True, "missing": []}


@app.get("/api/documents")
def documents():
    return app.state.documents


@app.get("/api/chunks/{chunk_id}")
def chunk(chunk_id: str):
    points = app.state.qdrant.retrieve(
        collection_name=COLLECTION_NAME,
        ids=[chunk_id],
        with_payload=True,
    )
    if not points:
        raise HTTPException(status_code=404, detail="Chunk no encontrado")
    payload = points[0].payload
    return {
        "text": payload["text"],
        "doc_title": payload["doc_title"],
        "doc_id": payload["doc_id"],
        "chunk_index": payload["chunk_index"],
        "page": payload["page"],
    }
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_main.py -q`
Expected: PASS (3 tests).

- [x] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_main.py
git commit -m "feat: add FastAPI core, schema and readiness endpoint"
```

### Task 3: Embeddings and vector search

**Files:**
- Create: `backend/search.py`
- Test: `backend/tests/test_search.py`

**Interfaces:**
- Consumes: `OLLAMA_HOST`, `EMBED_MODEL`, `COLLECTION_NAME` env vars; a `QdrantClient` instance.
- Produces: `embed(text: str) -> list[float]`, `retrieve(question: str, qdrant, limit: int = 4) -> list[dict]`, `point_id(doc_id: int, chunk_index: int) -> str`.

- [x] **Step 1: Write the failing tests**

`backend/tests/test_search.py`:

```python
import asyncio
import uuid
import search


def test_point_id_is_stable_uuid5():
    first = search.point_id(7, 3)
    second = search.point_id(7, 3)
    assert first == second
    assert uuid.UUID(first).version == 5
    assert search.point_id(7, 4) != first


def test_retrieve_returns_only_payloads_and_respects_limit():
    class Point:
        def __init__(self, point_id, payload):
            self.id = point_id
            self.payload = payload

    class FakeQdrant:
        def query_points(self, collection_name, query, limit, with_payload):
            assert collection_name == "notebooklm_chunks"
            assert query == [0.1] * 768
            assert limit == 4
            assert with_payload is True
            points = [Point("u1", {"text": "a"}), Point("u2", {"text": "b"})]
            return type("R", (), {"points": points})()

    async def fake_embed(text):
        return [0.1] * 768

    search.embed = fake_embed
    result = asyncio.run(search.retrieve("qué es Bitly", FakeQdrant()))
    assert result == [{"text": "a", "id": "u1"}, {"text": "b", "id": "u2"}]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_search.py -q`
Expected: FAIL — `search` module does not exist.

- [x] **Step 3: Write `backend/search.py`**

```python
import os
import uuid

import httpx

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "notebooklm_chunks")


def point_id(doc_id: int, chunk_index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{chunk_index}"))


async def embed(text: str) -> list[float]:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["embedding"]


async def retrieve(question: str, qdrant, limit: int = 4) -> list[dict]:
    vector = await embed(question)
    return _query(qdrant, vector, limit)


def _query(qdrant, vector: list[float], limit: int) -> list[dict]:
    result = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=limit,
        with_payload=True,
    )
    payloads = []
    for point in result.points:
        payload = dict(point.payload)
        payload["id"] = point.id
        payloads.append(payload)
    return payloads
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_search.py -q`
Expected: PASS (2 tests).

- [x] **Step 5: Commit**

```bash
git add backend/search.py backend/tests/test_search.py
git commit -m "feat: add Ollama embeddings and Qdrant retrieval"
```

### Task 4: Upload pipeline with chunking and SSE progress

**Files:**
- Create: `backend/upload.py`
- Modify: `backend/main.py` — add `/api/upload` route
- Test: `backend/tests/test_upload.py`

**Interfaces:**
- Consumes: `search.embed`, `search.point_id`, `app.state.pool`, `app.state.qdrant`, `app.state.documents`.
- Produces: `extract_text(filename: str, content: bytes) -> list[tuple[str, int]]`, `chunk_text(text: str, page: int) -> list[dict]`, `document_key(title: str) -> str`, `ingest(chunks, title, filename, qdrant, pool, documents) -> AsyncGenerator[str, None]` yielding SSE frames via `events.sse_frame`.

- [x] **Step 1: Write the failing tests**

`backend/tests/test_upload.py`:

```python
import io
import pytest
import upload


def test_chunk_text_uses_500_chars_and_50_overlap():
    text = "a" * 1200
    chunks = upload.chunk_text(text, page=2)
    assert [len(c["text"]) for c in chunks] == [500, 500, 300]
    assert chunks[0]["text"][-50:] == chunks[1]["text"][:50]
    assert all(c["page"] == 2 for c in chunks)
    assert [c["chunk_index"] for c in chunks] == [0, 1, 2]


def test_chunk_text_skips_whitespace_only_windows():
    assert upload.chunk_text("   ", page=1) == []


def test_extract_txt_assigns_page_one():
    assert upload.extract_text("notas.txt", "hola mundo".encode()) == [("hola mundo", 1)]


def test_extract_pdf_without_text_raises(monkeypatch):
    class FakeReader:
        def __init__(self, stream):
            self.pages = [type("P", (), {"extract_text": lambda self: ""})()]

    monkeypatch.setattr(upload, "PdfReader", FakeReader)
    with pytest.raises(ValueError, match="No se pudo extraer texto"):
        upload.extract_text("vacio.pdf", b"%PDF-fake")


def test_document_key_is_normalized():
    assert upload.document_key("  Bitly  ") == upload.document_key("bitly")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_upload.py -q`
Expected: FAIL — `upload` module does not exist.

- [x] **Step 3: Write `backend/upload.py`**

```python
import io
from typing import AsyncGenerator

from fastapi import UploadFile
from pypdf import PdfReader

from search import embed, point_id

CHUNK_SIZE = 500
OVERLAP = 50
MAX_BYTES = 10 * 1024 * 1024


def document_key(title: str) -> str:
    return " ".join(title.strip().lower().split())


def extract_text(filename: str, content: bytes) -> list[tuple[str, int]]:
    if filename.lower().endswith(".txt"):
        return [(content.decode("utf-8", errors="replace"), 1)]
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append((text, number))
        if not pages:
            raise ValueError("No se pudo extraer texto del PDF")
        return pages
    raise ValueError("Formato no soportado: use PDF o TXT")


def chunk_text(text: str, page: int) -> list[dict]:
    chunks = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        piece = text[start:end]
        if piece.strip():
            chunks.append({"text": piece, "page": page, "chunk_index": index})
            index += 1
        if end == len(text):
            break
        start = end - OVERLAP
    return chunks


def _frame(event: str, data: dict) -> str:
    import json

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def ingest(file: UploadFile, title: str, qdrant, pool, documents: list) -> AsyncGenerator[str, None]:
    filename = file.filename or "documento.txt"
    content = await file.read()
    if len(content) > MAX_BYTES:
        yield _frame("error", {"message": "El archivo supera los 10 MB"})
        return

    key = document_key(title)
    existing = next((d for d in documents if document_key(d["title"]) == key), None)
    if existing:
        yield _frame("done", {"doc_id": existing["id"], "title": existing["title"], "chunk_count": existing["chunk_count"]})
        return

    try:
        pages = extract_text(filename, content)
        all_chunks = []
        for page_number, page_text in pages:
            all_chunks.extend(chunk_text(page_text, page_number))
        if not all_chunks:
            yield _frame("error", {"message": "No se pudo extraer texto del documento"})
            return
    except ValueError as exc:
        yield _frame("error", {"message": str(exc)})
        return

    source_type = "pdf" if filename.lower().endswith(".pdf") else "txt"
    row = await pool.fetchrow(
        "INSERT INTO documents (title, filename, source_type) VALUES ($1, $2, $3) RETURNING id, title",
        key,
        filename,
        source_type,
    )
    doc_id = row["id"]
    stored = []
    try:
        for number, chunk in enumerate(all_chunks):
            vector = await embed(chunk["text"])
            qdrant.upsert(
                collection_name="notebooklm_chunks",
                points=[{
                    "id": point_id(doc_id, number),
                    "vector": vector,
                    "payload": {
                        "doc_id": doc_id,
                        "doc_title": key,
                        "chunk_index": number,
                        "page": chunk["page"],
                        "text": chunk["text"],
                    },
                }],
            )
            stored.append(point_id(doc_id, number))
            yield _frame("progress", {"phase": "indexing", "processed": number + 1, "total": len(all_chunks)})
    except Exception:
        if stored:
            qdrant.delete(collection_name="notebooklm_chunks", points_selector=stored)
        await pool.execute("DELETE FROM documents WHERE id = $1", doc_id)
        yield _frame("error", {"message": "Falló la indexación; no se guardó el documento"})
        return

    await pool.execute("UPDATE documents SET chunk_count = $1 WHERE id = $2", len(all_chunks), doc_id)
    doc = {"id": doc_id, "title": key, "filename": filename, "source_type": source_type, "chunk_count": len(all_chunks)}
    documents.append(doc)
    documents.sort(key=lambda d: d["id"])
    yield _frame("done", {"doc_id": doc_id, "title": key, "chunk_count": len(all_chunks)})
```

- [x] **Step 4: Wire the route into `backend/main.py`**

Add after the imports:

```python
from fastapi import File, Form, UploadFile
from upload import ingest
```

Add after `/api/chunks/{chunk_id}`:

```python
@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...), title: str = Form("")):
    name = title.strip() or (file.filename or "documento").rsplit(".", 1)[0]
    return StreamingResponse(
        ingest(file, name, app.state.qdrant, app.state.pool, app.state.documents),
        media_type="text/event-stream",
    )
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_upload.py -q`
Expected: PASS (5 tests).

- [x] **Step 6: Commit**

```bash
git add backend/upload.py backend/main.py backend/tests/test_upload.py
git commit -m "feat: add upload pipeline with chunking, embeddings and SSE progress"
```

### Task 5: Prompt, Ollama streaming answer and persistence

**Files:**
- Create: `backend/answer.py`
- Modify: `backend/main.py` — add `/api/ask` route
- Test: `backend/tests/test_answer.py`

**Interfaces:**
- Consumes: `search.retrieve`, `app.state.documents`, `app.state.pool`, `app.state.qdrant`, LLM/embed model names.
- Produces: `build_context(chunks, documents) -> tuple[str, list[dict]]`, `build_prompt(context: str, question: str = "") -> str`, `accumulate_answer(tokens: list[str]) -> str`, `has_citation_or_uncertainty(text: str) -> bool`, `answer_question(question, qdrant, pool, documents, llm_model) -> AsyncGenerator[str, None]`. SSE frames come from `events.sse_frame`.

- [x] **Step 1: Write the failing tests**

`backend/tests/test_answer.py`:

```python
import pytest
import answer


DOCS = [
    {"id": 1, "title": "bitly"},
    {"id": 2, "title": "kafka"},
    {"id": 3, "title": "system-design"},
]
CHUNKS = [
    {"doc_id": 3, "doc_title": "system-design", "text": "Kafka se usa en pipelines.", "page": 1, "chunk_index": 0, "id": "u3"},
    {"doc_id": 1, "doc_title": "bitly", "text": "Bitly acorta URLs.", "page": 2, "chunk_index": 4, "id": "u1"},
]


def test_build_context_numbers_docs_by_postgres_id():
    context, citations = answer.build_context(CHUNKS, DOCS)
    assert "[Doc 3]" in context
    assert "[Doc 1]" in context
    assert citations[0]["n"] == 3
    assert citations[0]["doc_id"] == 3
    assert citations[0]["chunk_id"] == "u3"
    assert citations[1]["n"] == 1
    assert citations[1]["chunk_id"] == "u1"


def test_build_prompt_contains_unknown_rule():
    prompt = answer.build_prompt("[Doc 1] texto")
    assert "No lo sé con los documentos disponibles" in prompt
    assert "[Doc 1]" in prompt
    assert "contexto" in prompt.lower()


def test_accumulate_answer_is_all_or_nothing():
    assert answer.accumulate_answer(["Hola", " ", "mundo"]) == "Hola mundo"
    assert answer.accumulate_answer([]) == ""


@pytest.mark.asyncio
async def test_answer_question_deletes_question_on_stream_error(monkeypatch):
    class FakeResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield '{"response":"respuesta parcial"}'
            yield '{"error":"boom"}'

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, *args, **kwargs):
            return FakeResponse()

    class FakePool:
        def __init__(self):
            self.deleted = []

        async def fetchrow(self, query, *args):
            return {"id": 42}

        async def execute(self, query, *args):
            self.deleted.append(args)

    async def fake_retrieve(question, qdrant, limit=4):
        return CHUNKS

    monkeypatch.setattr(answer.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(answer, "retrieve", fake_retrieve)
    pool = FakePool()
    events = [event async for event in answer.answer_question("q", object(), pool, DOCS, "llama3.2:3b")]
    assert any("event: error" in event for event in events)
    assert not any('"answer_id"' in event for event in events)
    assert pool.deleted == [(42,)]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_answer.py -q`
Expected: FAIL — `answer` module does not exist.

- [x] **Step 3: Write `backend/answer.py`**

```python
import json
import os
from typing import AsyncGenerator

import httpx

from search import retrieve

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

UNKNOWN_ANSWER = "No lo sé con los documentos disponibles"
PROMPT_TEMPLATE = """Respondé SOLO con el siguiente contexto. No uses conocimiento externo.
Citá cada afirmación con [Doc N], usando exactamente la numeración indicada.
Si la respuesta no está en el contexto, respondé exactamente: "{unknown}"

Contexto:
{context}

Pregunta: {question}

Respuesta:"""


def build_context(chunks: list[dict], documents: list[dict]) -> tuple[str, list[dict]]:
    number_by_id = {doc["id"]: index + 1 for index, doc in enumerate(sorted(documents, key=lambda d: d["id"]))}
    lines = []
    citations = []
    for chunk in chunks:
        doc_id = chunk["doc_id"]
        number = number_by_id.get(doc_id)
        if number is None:
            continue
        chunk_id = chunk.get("id") or str(chunk.get("chunk_index", 0))
        lines.append(f"[Doc {number}] (pág. {chunk['page']}, chunk {chunk['chunk_index']}) {chunk['text']}")
        citations.append({
            "n": number,
            "doc_id": doc_id,
            "chunk_id": chunk_id,
            "doc_title": chunk["doc_title"],
            "page": chunk["page"],
            "chunk_index": chunk["chunk_index"],
        })
    return "\n\n".join(lines), citations


def build_prompt(context: str, question: str = "") -> str:
    return PROMPT_TEMPLATE.format(unknown=UNKNOWN_ANSWER, context=context, question=question)


def accumulate_answer(tokens: list[str]) -> str:
    return "".join(tokens)


def _frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def answer_question(question: str, qdrant, pool, documents: list[dict], llm_model: str) -> AsyncGenerator[str, None]:
    if not question.strip():
        yield _frame("error", {"message": "La pregunta no puede estar vacía"})
        return
    if not documents:
        yield _frame("error", {"message": "No hay documentos indexados"})
        return

    chunks = await retrieve(question, qdrant, limit=4)
    if not chunks:
        yield _frame("error", {"message": "No hay documentos indexados"})
        return

    context, citations = build_context(chunks, documents)
    yield _frame("citations", {"citations": citations})

    question_row = await pool.fetchrow("INSERT INTO questions (text) VALUES ($1) RETURNING id", question)
    tokens = []
    failed = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_HOST}/api/generate",
                json={
                    "model": llm_model,
                    "prompt": build_prompt(context, question),
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    token = payload.get("response", "")
                    if token:
                        tokens.append(token)
                        yield _frame("token", {"text": token})
                    if payload.get("error"):
                        raise RuntimeError(payload["error"])
    except Exception:
        failed = True
        yield _frame("error", {"message": "Ollama no pudo generar la respuesta"})

    if failed:
        await pool.execute("DELETE FROM questions WHERE id = $1", question_row["id"])
        return

    text = accumulate_answer(tokens)
    answer_row = await pool.fetchrow(
        "INSERT INTO answers (question_id, text, citations) VALUES ($1, $2, $3::jsonb) RETURNING id",
        question_row["id"],
        text,
        json.dumps(citations),
    )
    yield _frame("done", {"answer_id": answer_row["id"], "text": text})
```

- [x] **Step 4: Wire the route into `backend/main.py`**

Add after the imports:

```python
from answer import answer_question
```

Add after `/api/upload`:

```python
@app.post("/api/ask")
async def ask(payload: dict):
    question = payload.get("question", "")
    return StreamingResponse(
        answer_question(question, app.state.qdrant, app.state.pool, app.state.documents, app.state.llm_model),
        media_type="text/event-stream",
    )
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_answer.py -q`
Expected: PASS (3 tests).

- [x] **Step 6: Commit**

```bash
git add backend/answer.py backend/main.py backend/tests/test_answer.py
git commit -m "feat: add cited answer generation with SSE streaming"
```

### Task 6: React UI with SSE, citation buttons and chunk modal

**Files:**
- Modify: `frontend/src/App.tsx` (created in this task)
- Test: `frontend/src/citations.test.ts` (pure helpers exported from `App.tsx`)

**Interfaces:**
- Consumes: `GET /api/documents`, `GET /api/ready`, `POST /api/upload` (SSE), `POST /api/ask` (SSE), `GET /api/chunks/{id}`.
- Produces: `splitAnswerText(text: string, knownDocumentNumbers: number[] = []): Array<{kind:'text'|'citation', value:string}>`, `parseSSE(response: Response): AsyncGenerator<{event:string,data:any}>`, `consumeSSE(response: Response, handlers: Record<string, (data:any) => void|Promise<void>>): Promise<boolean>`, and the `App` default export.

- [x] **Step 1: Write the failing test**

`frontend/src/citations.test.ts` requires a runner; add `vitest` to `frontend/package.json` devDependencies and a `"test": "vitest run"` script, then write:

```ts
import { describe, expect, it } from 'vitest'
import { splitAnswerText } from './App'

describe('splitAnswerText', () => {
  it('turns known citations into citation tokens', () => {
    expect(splitAnswerText('Según [Doc 2] y [Doc 1].')).toEqual([
      { kind: 'text', value: 'Según ' },
      { kind: 'citation', value: '2' },
      { kind: 'text', value: ' y ' },
      { kind: 'citation', value: '1' },
      { kind: 'text', value: '.' },
    ])
  })

  it('leaves unknown citation numbers as plain text', () => {
    expect(splitAnswerText('No existe [Doc 9]', [1, 2])).toEqual([
      { kind: 'text', value: 'No existe [Doc 9]' },
    ])
  })
})
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm install && npm test`
Expected: FAIL — `App.tsx` does not export `splitAnswerText` yet.

- [x] **Step 3: Write `frontend/src/App.tsx`**

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'

const API = ((import.meta as any).env?.VITE_API_URL as string) || 'http://localhost:8000'

export type Doc = { id: number; title: string; filename: string; source_type: string; chunk_count: number }
export type Citation = { n: number; doc_id: number; chunk_id: string; doc_title: string; page: number; chunk_index: number }
export type Chunk = { text: string; doc_title: string; doc_id: number; page: number; chunk_index: number }
type Token = { kind: 'text' | 'citation'; value: string }

export function splitAnswerText(text: string, known: number[] = []): Token[] {
  const result: Token[] = []
  const regex = /\[Doc (\d+)\]/g
  let last = 0
  let match: RegExpExecArray | null
  while ((match = regex.exec(text)) !== null) {
    const number = Number(match[1])
    if (known.length > 0 && !known.includes(number)) continue
    if (match.index > last) result.push({ kind: 'text', value: text.slice(last, match.index) })
    result.push({ kind: 'citation', value: match[1] })
    last = match.index + match[0].length
  }
  if (last < text.length) result.push({ kind: 'text', value: text.slice(last) })
  return result
}

export async function* parseSSE(response: Response): AsyncGenerator<{ event: string; data: any }> {
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let index: number
    while ((index = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      let event = 'message'
      const dataLines: string[] = []
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (dataLines.length) yield { event, data: JSON.parse(dataLines.join('\n')) }
    }
  }
}

export default function App() {
  const [docs, setDocs] = useState<Doc[]>([])
  const [ready, setReady] = useState(false)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [citations, setCitations] = useState<Citation[]>([])
  const [activeChunk, setActiveChunk] = useState<Chunk | null>(null)
  const [uploadProgress, setUploadProgress] = useState<{ processed: number; total: number } | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const loadDocs = useCallback(async () => {
    const response = await fetch(`${API}/api/documents`)
    if (response.ok) setDocs(await response.json())
  }, [])

  useEffect(() => {
    let alive = true
    const check = async () => {
      try {
        const response = await fetch(`${API}/api/ready`)
        if (alive && response.ok) {
          setReady(true)
          await loadDocs()
        }
      } catch {}
    }
    void check()
    const timer = setInterval(check, 3000)
    return () => { alive = false; clearInterval(timer) }
  }, [loadDocs])

  const onUpload = async (file: File) => {
    setError('')
    setUploadProgress({ processed: 0, total: 0 })
    const form = new FormData()
    form.append('file', file)
    const response = await fetch(`${API}/api/upload`, { method: 'POST', body: form })
    if (!response.ok) { setError('No se pudo subir el documento'); setUploadProgress(null); return }
    for await (const event of parseSSE(response)) {
      if (event.event === 'progress') setUploadProgress({ processed: event.data.processed, total: event.data.total })
      if (event.event === 'error') setError(event.data.message)
      if (event.event === 'done') { setUploadProgress(null); await loadDocs() }
    }
  }

  const onAsk = async () => {
    if (!question.trim()) return
    setAnswer(''); setCitations([]); setError(''); setLoading(true)
    const response = await fetch(`${API}/api/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    })
    if (!response.ok) { setError('No se pudo hacer la pregunta'); setLoading(false); return }
    for await (const event of parseSSE(response)) {
      if (event.event === 'citations') setCitations(event.data.citations)
      if (event.event === 'token') setAnswer((previous) => previous + event.data.text)
      if (event.event === 'error') setError(event.data.message)
      if (event.event === 'done') setAnswer(event.data.text)
    }
    setLoading(false)
  }

  const openCitation = async (n: string) => {
    const citation = citations.find((c) => String(c.n) === n)
    if (!citation) return
    const response = await fetch(`${API}/api/chunks/${citation.chunk_id}`)
    if (response.ok) setActiveChunk(await response.json())
  }

  const knownNumbers = citations.map((c) => c.n)
  const tokens = splitAnswerText(answer, knownNumbers.length ? knownNumbers : [])

  return (
    <div className="flex h-screen bg-slate-50 text-slate-900">
      <aside className="w-80 shrink-0 border-r border-slate-200 bg-white p-5">
        <h1 className="text-lg font-bold">NotebookLM local</h1>
        <p className="mt-1 text-xs text-slate-500">Solo responde con tus documentos</p>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.txt"
          className="hidden"
          onChange={(event) => { const file = event.target.files?.[0]; if (file) void onUpload(file) }}
        />
        <button
          onClick={() => fileRef.current?.click()}
          className="mt-5 w-full rounded bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
        >
          Subir PDF/TXT
        </button>
        {uploadProgress && (
          <div className="mt-3">
            <div className="h-2 w-full overflow-hidden rounded bg-slate-200">
              <div
                className="h-full bg-indigo-500 transition-all"
                style={{ width: uploadProgress.total ? `${(uploadProgress.processed / uploadProgress.total) * 100}%` : '10%' }}
              />
            </div>
            <p className="mt-1 text-xs text-slate-500">Indexando {uploadProgress.processed}/{uploadProgress.total} chunks</p>
          </div>
        )}
        <h2 className="mt-7 text-xs font-bold uppercase tracking-wide text-slate-500">Documentos</h2>
        {!ready && <p className="mt-3 text-sm text-slate-500">Inicializando…</p>}
        {ready && docs.length === 0 && <p className="mt-3 text-sm text-slate-500">Subí un documento para empezar</p>}
        <ul className="mt-2 space-y-2">
          {docs.map((doc) => (
            <li key={doc.id} className="rounded border border-slate-200 px-3 py-2 text-sm">
              <p className="font-medium">[Doc {doc.id}] {doc.title}</p>
              <p className="text-xs text-slate-500">{doc.chunk_count} chunks · {doc.source_type}</p>
            </li>
          ))}
        </ul>
      </aside>

      <main className="flex flex-1 flex-col p-8">
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col">
          <h2 className="text-2xl font-bold">Preguntá sobre tus documentos</h2>
          {error && <p className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          <div className="mt-6 flex gap-2">
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') void onAsk() }}
              placeholder="¿Qué dice Bitly sobre los clics?"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <button onClick={() => void onAsk()} disabled={loading} className="rounded bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
              Preguntar
            </button>
          </div>
          <div className="mt-6 min-h-52 rounded border border-slate-200 bg-white p-5 text-sm leading-7">
            {answer ? (
              <p className="whitespace-pre-wrap">
                {tokens.map((token, index) => token.kind === 'text'
                  ? <span key={index}>{token.value}</span>
                  : <button
                      key={index}
                      onClick={() => void openCitation(token.value)}
                      className="mx-0.5 rounded bg-indigo-100 px-1 font-semibold text-indigo-700 hover:bg-indigo-200"
                    >[Doc {token.value}]</button>)}
              </p>
            ) : (
              <p className="text-slate-400">{loading ? 'Pensando…' : 'La respuesta aparecerá acá, con citas clicables.'}</p>
            )}
          </div>
        </div>
      </main>

      {activeChunk && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/40 p-6" onClick={() => setActiveChunk(null)}>
          <div className="max-w-xl rounded bg-white p-6 shadow-xl" onClick={(event) => event.stopPropagation()}>
            <p className="text-xs font-bold uppercase text-indigo-600">{activeChunk.doc_title} · pág. {activeChunk.page} · chunk {activeChunk.chunk_index}</p>
            <h3 className="mt-1 text-lg font-bold">{activeChunk.doc_title}</h3>
            <p className="mt-4 whitespace-pre-wrap text-sm leading-7">{activeChunk.text}</p>
            <button onClick={() => setActiveChunk(null)} className="mt-5 rounded border px-3 py-1 text-sm">Cerrar</button>
          </div>
        </div>
      )}
    </div>
  )
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (2 tests).

- [x] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/citations.test.ts frontend/package.json
git commit -m "feat: add React UI with streaming answers and clickable citations"
```

### Task 7: README and end-to-end verification

**Files:**
- Create: `README.md`
- Test: manual smoke test against running Compose stack

**Interfaces:**
- Consumes: every endpoint and file from Tasks 1–6.
- Produces: user-facing documentation and the smoke-test result.

- [x] **Step 1: Write `README.md`**

````markdown
# ¿Cómo funciona Google NotebookLM? — Ejercicio 0002

Prototipo funcional de NotebookLM: subís PDF o TXT, el sistema los indexa y después responde preguntas **usando solo esos documentos**, con citas clicables.

## Cómo arrancar

```bash
docker compose up
```

El primer arranque descarga `llama3.2:3b` y `nomic-embed-text` (puede tardar varios minutos). Después abrí http://localhost:5174. No hace falta configurar nada ni usar APIs pagas.

Si querés ver el progreso: `docker compose logs -f model-pull seed-docs`.

## Cómo usarlo

1. Al abrir, ya están cargados 3 documentos de ejemplo: **bitly**, **kafka** y **system-design**.
2. Escribí una pregunta, por ejemplo: *¿Qué ventaja tiene un enlace corto de Bitly?*
3. La respuesta llega token a token. Los `[Doc 1]`, `[Doc 2]` son clicables: al hacer clic se abre el chunk original con el título del documento, la página y el índice de chunk.
4. Si la respuesta no está en los documentos, el sistema dice: *No lo sé con los documentos disponibles*.
5. Podés subir tus propios PDF/TXT desde "Subir PDF/TXT"; la barra muestra los chunks indexados en tiempo real.

## Alcance y decisiones de diseño

Este prototipo es local y deliberadamente chico. Las decisiones están detalladas en `docs/decisiones.md`; las principales son:

- **Sin fuentes externas.** Qdrant solo recibe chunks de archivos subidos o de los documentos semilla. No hay crawler ni buscador web: si la respuesta no está en los documentos, el modelo lo dice.
- **Embeddings y respuestas en Ollama.** `nomic-embed-text` (768 dimensiones) para vectores y `llama3.2:3b` para generación, con `OLLAMA_HOST=http://ollama:11434`.
- **Chunks de 500 caracteres con overlap de 50**, con metadata `doc_id`, `doc_title`, `chunk_index` y `page`.
- **Top 4 chunks** por pregunta y numeración `[Doc N]` estable por id de documento, para que `[Doc 2]` signifique lo mismo en todas las preguntas.
- **Postgres guarda documentos, preguntas y respuestas**; Qdrant guarda los chunks y su payload. Las citas clicables se recuerdan en el evento `citations` del stream.
- **Semillas por el endpoint real.** Un contenedor one-shot sube los `.txt` de `docs/seed/` mediante `POST /api/upload`, para que la demo use exactamente el mismo pipeline que un usuario.
- **Un solo comando.** Los modelos se descargan al arrancar y los healthchecks ordenan la secuencia infraestructura → modelos → backend → semillas → frontend.

### A propósito NO se implementa

- Crawler web
- Buscador web
- Fine-tuning
- Evaluación de RAG
- Audio overview (podcast) de NotebookLM
- Guardrails avanzados

## Arquitectura

```
navegador → frontend (5173) → backend FastAPI (8000) → Qdrant (6333) + Postgres (5432) + Ollama (11434)
```

| Servicio | Responsabilidad |
|---|---|
| `backend/main.py` | endpoints, schema y readiness |
| `backend/upload.py` | extracción, chunking e indexación con progreso SSE |
| `backend/search.py` | embeddings y búsqueda top 4 |
| `backend/answer.py` | prompt con citas, streaming SSE y persistencia |
| `frontend/src/App.tsx` | UI, parser SSE y modal de citas |

## Verificación manual

```bash
curl -s localhost:8000/api/ready
curl -s localhost:8000/api/documents | head -c 500
curl -N -X POST localhost:8000/api/ask -H 'Content-Type: application/json' \
  -d '{"question":"¿Qué ventaja tiene un enlace corto de Bitly?"}'
```

Esperado: `ready: true`, 3 documentos, y un stream con eventos `citations`, `token` y `done`.

## Apagar

```bash
docker compose down
```

Los volúmenes se conservan; para borrar también los datos y los modelos: `docker compose down -v`.
````

- [x] **Step 2: Run the smoke test**

Run: `docker compose up -d` then the three `curl` commands from the README.
Expected: `/api/ready` → `{"ready": true, "missing": []}`; `/api/documents` → 3 entries; `/api/ask` → stream containing `event: citations`, several `event: token`, and `event: done`.

- [x] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add README with usage, scope and smoke test"
```

## Estado

Plan ejecutado y verificado el 2026-11-18. Los desvíos respecto del plan original se documentan en los mensajes de commit y en `docs/decisiones.md`.
