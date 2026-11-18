"""Formato SSE compartido por upload y respuestas."""

import json


def sse_frame(event: str, data: dict) -> str:
    """Un evento SSE: línea `event`, línea `data` y línea en blanco de cierre."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
