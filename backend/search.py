"""Buscador vectorial de la capa de recuperación (retrieval).

Un embedding es una lista de números que representa el significado de un
texto: dos textos parecidos tienen vectores cercanos. Este módulo une
Ollama (que genera los vectores) con Qdrant (que los guarda y busca).
"""

import os
import uuid

import httpx

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "notebooklm_chunks")


def point_id(doc_id: int, chunk_index: int) -> str:
    """ID determinista: el mismo (doc_id, chunk_index) da siempre el mismo UUID.
    Así reindexar un chunk no crea puntos duplicados y el ID es estable entre procesos.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{chunk_index}"))


async def embed(text: str) -> list[float]:
    """Pide a Ollama el vector del texto (nomic-embed-text, 768 dimensiones)."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["embedding"]


async def retrieve(question: str, qdrant, limit: int = 4) -> list[dict]:
    # No comparamos palabras exactas sino cercanía de significado: por eso una
    # pregunta puede encontrar un fragmento que no repite sus propios términos.
    vector = await embed(question)
    return _query(qdrant, vector, limit)


def _query(qdrant, vector: list[float], limit: int) -> list[dict]:
    """Agregamos el id de cada punto a su payload.
    El frontend lo necesita para abrir el chunk original al clickear una cita.
    """
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
