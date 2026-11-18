from fastapi.testclient import TestClient
import main


def test_health_ok():
    client = TestClient(main.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_documents_empty_before_ingest():
    main.app.state.documents = []
    client = TestClient(main.app)
    response = client.get("/api/documents")
    assert response.status_code == 200
    assert response.json() == []


def test_ready_reports_missing_models():
    class FakeQdrant:
        def collection_exists(self, collection_name):
            return True

    class FakePool:
        async def fetchval(self, query):
            return 1

    async def fake_get(url, timeout):
        class R:
            def raise_for_status(self):
                return None

            def json(self):
                return {"models": [{"name": "llama3.2:3b"}]}

        return R()

    main.app.state.pool = FakePool()
    main.app.state.qdrant = FakeQdrant()
    main.httpx_get = fake_get
    client = TestClient(main.app)
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["missing"] == ["model:nomic-embed-text"]


def test_ready_rejects_wrong_llama_tag(monkeypatch):
    class FakeQdrant:
        def collection_exists(self, collection_name):
            return True

    class FakePool:
        async def fetchval(self, query):
            return 1

    async def fake_get(url, timeout):
        class R:
            def raise_for_status(self):
                return None

            def json(self):
                return {"models": [{"name": "llama3.2:1b"}, {"name": "nomic-embed-text:latest"}]}

        return R()

    main.app.state.pool = FakePool()
    main.app.state.qdrant = FakeQdrant()
    monkeypatch.setattr(main, "httpx_get", fake_get)
    client = TestClient(main.app)
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["missing"] == ["model:llama3.2:3b"]


def test_ready_accepts_latest_tag_for_untagged_config(monkeypatch):
    class FakeQdrant:
        def collection_exists(self, collection_name):
            return True

    class FakePool:
        async def fetchval(self, query):
            return 1

    async def fake_get(url, timeout):
        class R:
            def raise_for_status(self):
                return None

            def json(self):
                return {"models": [{"name": "llama3.2:3b"}, {"name": "nomic-embed-text:latest"}]}

        return R()

    main.app.state.pool = FakePool()
    main.app.state.qdrant = FakeQdrant()
    monkeypatch.setattr(main, "httpx_get", fake_get)
    client = TestClient(main.app)
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True, "missing": []}


def test_upload_bad_extension_returns_400():
    client = TestClient(main.app)
    response = client.post("/api/upload", files={"file": ("notas.md", b"hola", "text/markdown")})
    assert response.status_code == 400


def test_upload_pdf_without_text_returns_422(monkeypatch):
    monkeypatch.setattr(main.upload, "extract_text", lambda filename, content: [])
    client = TestClient(main.app)
    response = client.post("/api/upload", files={"file": ("vacio.pdf", b"%PDF-fake", "application/pdf")})
    assert response.status_code == 422


def test_ask_empty_question_returns_400():
    client = TestClient(main.app)
    response = client.post("/api/ask", json={"question": "   "})
    assert response.status_code == 400
