# SSE con `fetch` + `ReadableStream` para progreso y respuestas

Tanto la subida como la pregunta emiten varios eventos a lo largo del tiempo: `progress`, `citations`, `token` y `done`. Decidimos Server-Sent Events sobre HTTP, leídos en el frontend con `fetch` y un lector de stream que acumula un buffer hasta encontrar la línea en blanco que cierra cada evento.

## Alternativas descartadas

- **EventSource del navegador**: solo soporta GET, así que no sirve para `POST /api/upload` ni para `POST /api/ask` con un cuerpo JSON.
- **WebSocket**: agrega otro protocolo y otro servidor para un flujo que es unidireccional (servidor → cliente).
- **Polling**: no permite mostrar tokens a medida que se generan ni el progreso real por chunk durante la indexación.
