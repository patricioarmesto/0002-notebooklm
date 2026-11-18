def test_sse_frame_uses_named_event_and_json_data():
    from events import sse_frame

    assert sse_frame("token", {"text": "hola"}) == 'event: token\ndata: {"text": "hola"}\n\n'


def test_sse_frame_keeps_unicode_readable():
    from events import sse_frame

    assert sse_frame("error", {"message": "No lo sé"}) == 'event: error\ndata: {"message": "No lo sé"}\n\n'
