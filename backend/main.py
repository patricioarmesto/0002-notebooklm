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

from upload import ingest

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


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...), title: str = Form("")):
    name = title.strip() or (file.filename or "documento").rsplit(".", 1)[0]
    return StreamingResponse(
        ingest(file, name, app.state.qdrant, app.state.pool, app.state.documents),
        media_type="text/event-stream",
    )
