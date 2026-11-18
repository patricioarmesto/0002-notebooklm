import json
import os
import re
from typing import AsyncGenerator

import httpx

from search import retrieve

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

UNKNOWN_ANSWER = "No lo sé con los documentos disponibles"
UNCERTAINTY_MARKERS = ("no lo sé", "no sé", "no tengo información", "no dispongo", "no está en el contexto")
PROMPT_TEMPLATE = """Respondé SOLO usando el siguiente contexto. No uses conocimiento externo.
Citá cada afirmación indicando el número de documento entre corchetes, por ejemplo {example}, usando exactamente la numeración indicada. Incluí al menos una cita concreta en la respuesta.
Si el contexto no contiene información relevante para la pregunta, respondé exactamente: "{unknown}".
Si el contexto sí contiene información relacionada, respondé con ella aunque no repita literalmente las palabras de la pregunta.

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
    match = re.search(r"\[Doc (\d+)\]", context)
    example = f"[Doc {match.group(1)}]" if match else "[Doc 1]"
    return PROMPT_TEMPLATE.format(unknown=UNKNOWN_ANSWER, context=context, question=question, example=example)


def accumulate_answer(tokens: list[str]) -> str:
    return "".join(tokens)


def ensure_citations(text: str, citations: list[dict]) -> str:
    """Fallback: el modelo a veces omite [Doc N] aunque recibió el contexto citado."""
    lowered = text.lower()
    if not citations or any(marker in lowered for marker in UNCERTAINTY_MARKERS) or re.search(r"\[Doc \d+\]", text):
        return text
    return f"{text.rstrip()} [Doc {citations[0]['n']}]"


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
    except BaseException:
        failed = True
        raise
    finally:
        if failed:
            await pool.execute("DELETE FROM questions WHERE id = $1", question_row["id"])

    if failed:
        return

    raw_text = accumulate_answer(tokens)
    text = ensure_citations(raw_text, citations)
    if text != raw_text:
        yield _frame("token", {"text": text[len(raw_text.rstrip()):]})
    answer_row = await pool.fetchrow(
        "INSERT INTO answers (question_id, text, citations) VALUES ($1, $2, $3::jsonb) RETURNING id",
        question_row["id"],
        text,
        json.dumps(citations),
    )
    yield _frame("done", {"answer_id": answer_row["id"], "text": text})
