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


def test_validate_upload_rejects_bad_extension_with_400():
    with pytest.raises(upload.UploadValidationError) as exc:
        upload.validate_upload("notas.md", b"hola")
    assert exc.value.status_code == 400


def test_validate_upload_rejects_oversized_file_with_400():
    with pytest.raises(upload.UploadValidationError) as exc:
        upload.validate_upload("notas.txt", b"x" * (upload.MAX_BYTES + 1))
    assert exc.value.status_code == 400


def test_validate_upload_rejects_pdf_without_text_with_422(monkeypatch):
    monkeypatch.setattr(upload, "extract_text", lambda filename, content: [])
    with pytest.raises(upload.UploadValidationError) as exc:
        upload.validate_upload("vacio.pdf", b"%PDF-fake")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_ingest_indexes_text_with_page_one(monkeypatch):
    class FakeQdrant:
        def __init__(self):
            self.points = []
            self.collections = []

        def upsert(self, collection_name, points):
            self.collections.append(collection_name)
            self.points.extend(points)

    class FakePool:
        async def fetchrow(self, query, *args):
            return {"id": 1, "title": "notas"}

        async def execute(self, query, *args):
            return None

    async def fake_embed(text):
        return [0.0] * 768

    monkeypatch.setattr(upload, "embed", fake_embed)
    monkeypatch.setattr(upload, "COLLECTION_NAME", "otra_coleccion")
    qdrant = FakeQdrant()
    documents = []
    chunks = upload.validate_upload("notas.txt", b"hola mundo")
    events = [event async for event in upload.ingest(chunks, "notas", "notas.txt", qdrant, FakePool(), documents)]
    assert any("event: done" in event for event in events)
    assert qdrant.collections == ["otra_coleccion"]
    assert qdrant.points[0]["payload"]["page"] == 1
    assert documents[0]["chunk_count"] == 1
