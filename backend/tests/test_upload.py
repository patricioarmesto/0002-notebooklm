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
