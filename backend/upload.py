import io
import json
import os
from typing import AsyncGenerator

from pypdf import PdfReader

from search import embed, point_id

CHUNK_SIZE = 500
OVERLAP = 50
MAX_BYTES = 10 * 1024 * 1024
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "notebooklm_chunks")


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
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class UploadValidationError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def validate_upload(filename: str, content: bytes) -> list[dict]:
    filename = filename or "documento.txt"
    if len(content) > MAX_BYTES:
        raise UploadValidationError(400, "El archivo supera los 10 MB")
    if not filename.lower().endswith((".pdf", ".txt")):
        raise UploadValidationError(400, "Formato no soportado: use PDF o TXT")
    try:
        pages = extract_text(filename, content)
        chunks = []
        for page_text, page_number in pages:
            chunks.extend(chunk_text(page_text, page_number))
    except ValueError as exc:
        raise UploadValidationError(422, str(exc)) from exc
    if not chunks:
        raise UploadValidationError(422, "No se pudo extraer texto del documento")
    return chunks


async def ingest(chunks: list[dict], title: str, filename: str, qdrant, pool, documents: list) -> AsyncGenerator[str, None]:
    key = document_key(title)
    existing = next((d for d in documents if document_key(d["title"]) == key), None)
    if existing:
        yield _frame("done", {"doc_id": existing["id"], "title": existing["title"], "chunk_count": existing["chunk_count"]})
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
        for number, chunk in enumerate(chunks):
            vector = await embed(chunk["text"])
            qdrant.upsert(
                collection_name=COLLECTION_NAME,
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
            yield _frame("progress", {"phase": "indexing", "processed": number + 1, "total": len(chunks)})
    except Exception:
        if stored:
            qdrant.delete(collection_name=COLLECTION_NAME, points_selector=stored)
        await pool.execute("DELETE FROM documents WHERE id = $1", doc_id)
        yield _frame("error", {"message": "Falló la indexación; no se guardó el documento"})
        return

    await pool.execute("UPDATE documents SET chunk_count = $1 WHERE id = $2", len(chunks), doc_id)
    doc = {"id": doc_id, "title": key, "filename": filename, "source_type": source_type, "chunk_count": len(chunks)}
    documents.append(doc)
    documents.sort(key=lambda d: d["id"])
    yield _frame("done", {"doc_id": doc_id, "title": key, "chunk_count": len(chunks)})
