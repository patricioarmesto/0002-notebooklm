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
