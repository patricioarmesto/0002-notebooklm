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
