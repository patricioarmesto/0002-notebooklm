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
    assert "información relevante" in prompt
    assert "Incluí al menos una cita" in prompt


def test_build_prompt_uses_a_concrete_citation_example():
    prompt = answer.build_prompt("[Doc 3] texto", "pregunta")
    assert "[Doc N]" not in prompt
    assert "por ejemplo [Doc 3]" in prompt


def test_accumulate_answer_is_all_or_nothing():
    assert answer.accumulate_answer(["Hola", " ", "mundo"]) == "Hola mundo"
    assert answer.accumulate_answer([]) == ""


def test_ensure_citations_adds_top_citation_only_when_model_omits_it():
    citations = [{"n": 1}, {"n": 2}]
    assert answer.ensure_citations("Una ventaja es el ahorro de espacio.", citations) == "Una ventaja es el ahorro de espacio. [Doc 1]"
    assert answer.ensure_citations("Según [Doc 2] ...", citations) == "Según [Doc 2] ..."
    unknown = "No lo sé con los documentos disponibles."
    assert answer.ensure_citations(unknown, citations) == unknown
    uncertain = "No tengo información suficiente en los documentos."
    assert answer.ensure_citations(uncertain, citations) == uncertain
    assert answer.ensure_citations("texto", []) == "texto"


@pytest.mark.asyncio
async def test_answer_question_streams_fallback_citation(monkeypatch):
    class FakeResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield '{"response":"Una respuesta sin cita"}'
            yield '{"done":true}'

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
        async def fetchrow(self, query, *args):
            return {"id": 7}

        async def execute(self, query, *args):
            return None

    async def fake_retrieve(question, qdrant, limit=4):
        return CHUNKS

    monkeypatch.setattr(answer.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(answer, "retrieve", fake_retrieve)
    events = [event async for event in answer.answer_question("q", object(), FakePool(), DOCS, "model")]
    assert any(event.startswith("event: token") and "[Doc 3]" in event for event in events)
    assert any("[Doc 3]" in event and "event: done" in event for event in events)


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
