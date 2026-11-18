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
