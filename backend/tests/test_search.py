import asyncio
import uuid
import search


def test_point_id_is_stable_uuid5():
    first = search.point_id(7, 3)
    second = search.point_id(7, 3)
    assert first == second
    assert uuid.UUID(first).version == 5
    assert search.point_id(7, 4) != first


def test_retrieve_returns_only_payloads_and_respects_limit():
    class Point:
        def __init__(self, point_id, payload):
            self.id = point_id
            self.payload = payload

    class FakeQdrant:
        def query_points(self, collection_name, query, limit, with_payload):
            assert collection_name == "notebooklm_chunks"
            assert query == [0.1] * 768
            assert limit == 4
            assert with_payload is True
            points = [Point("u1", {"text": "a"}), Point("u2", {"text": "b"})]
            return type("R", (), {"points": points})()

    async def fake_embed(text):
        return [0.1] * 768

    search.embed = fake_embed
    result = asyncio.run(search.retrieve("qué es Bitly", FakeQdrant()))
    assert result == [{"text": "a", "id": "u1"}, {"text": "b", "id": "u2"}]
