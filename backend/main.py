"""API FastAPI del prototipo: subida, preguntas y healthchecks.

El frontend y el servicio de semillas usan siempre estos endpoints HTTP;
la lógica RAG vive en `upload.py`, `search.py` y `answer.py`.
"""

import asyncio
import os
from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

import upload
from answer import answer_question

# En local apuntan a localhost; dentro de Compose se overridean con los
# nombres de servicio (postgres, qdrant, ollama).
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://notebooklm:notebooklm@localhost:5432/notebooklm")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "llama3.2:3b")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "notebooklm_chunks")
VECTOR_SIZE = 768

# Esquema mínimo aplicado al arrancar: en un prototipo evita tener un
# paso de migraciones separado. `documents` define la numeración [Doc N].
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
    """Espera hasta 60 s a que Postgres acepte conexiones."""
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


def model_reference(name: str) -> str:
    """Ollama informa `name:latest` cuando el pull no especificó tag."""
    return name if ":" in name else f"{name}:latest"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque: crea esquema y colección, y cachea los documentos en memoria.
    Así no hay que leer Postgres en cada pedido; `app.state` es el lugar
    compartido donde los endpoints encuentran sus dependencias.
    """
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
# Abierto porque corre en la propia máquina; en producción se limitaría
# a los orígenes del frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Solo dice que el proceso vive: lo usa el healthcheck de Compose."""
    return {"ok": True}


@app.get("/api/ready")
async def ready():
    """Chequea dependencias reales: BD, Qdrant y los dos modelos de Ollama.
    El frontend espera este endpoint; `/health` no alcanza porque el backend
    puede estar vivo mientras los modelos todavía se descargan.
    """
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
        installed = {model_reference(m["name"]) for m in response.json().get("models", [])}
        for model in (LLM_MODEL, EMBED_MODEL):
            if model_reference(model) not in installed:
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
    """Devuelve el texto original detrás de una cita [Doc N] clicable."""
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


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...), title: str = Form("")):
    filename = file.filename or "documento.txt"
    # Leemos los bytes ACA, dentro del request: el generador SSE corre después
    # de cerrado el UploadFile y ya no podría leerlo.
    content = await file.read()
    try:
        chunks = upload.validate_upload(filename, content)
    except upload.UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    name = title.strip() or filename.rsplit(".", 1)[0]
    return StreamingResponse(
        upload.ingest(chunks, name, filename, app.state.qdrant, app.state.pool, app.state.documents),
        media_type="text/event-stream",
    )


@app.post("/api/ask")
async def ask(payload: dict):
    """Valida antes de abrir el stream: pregunta vacía es 400, no 200 + SSE."""
    question = payload.get("question", "")
    if not question.strip():
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")
    return StreamingResponse(
        answer_question(question, app.state.qdrant, app.state.pool, app.state.documents, app.state.llm_model),
        media_type="text/event-stream",
    )
