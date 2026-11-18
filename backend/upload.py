import io
import json
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
