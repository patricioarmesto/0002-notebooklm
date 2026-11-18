# ¿Cómo funciona Google NotebookLM? — Ejercicio 0002

Prototipo funcional de NotebookLM: subís PDF o TXT, el sistema los indexa y después responde preguntas **usando solo esos documentos**, con citas clicables.

## Cómo arrancar

```bash
docker compose up
```

El primer arranque descarga `llama3.2:3b` y `nomic-embed-text` (puede tardar varios minutos). Después abrí http://localhost:5174. No hace falta configurar nada ni usar APIs pagas.

Los puertos del host son configurables: `POSTGRES_PORT` (default `5433`) y `FRONTEND_PORT` (default `5174`). Se eligieron puertos no conflictivos porque en este host otros proyectos ya usan `5432` y `5173`. Los puertos internos siguen siendo `5432`/`5173`, y el backend (`8000`), Qdrant (`6333`) y Ollama (`11434`) no cambiaron. Si querés usar los puertos originales:

```bash
POSTGRES_PORT=5432 FRONTEND_PORT=5173 docker compose up
```

Si querés ver el progreso: `docker compose logs -f model-pull seed-docs`.

## Cómo usarlo

1. Al abrir, ya están cargados 3 documentos de ejemplo: **bitly**, **kafka** y **system-design**.
2. Escribí una pregunta, por ejemplo: *¿Qué ventaja tiene un enlace corto de Bitly?*
3. La respuesta llega token a token. Los `[Doc 1]`, `[Doc 2]` son clicables: al hacer clic se abre el chunk original con el título del documento, la página y el índice de chunk.
4. Si la respuesta no está en los documentos, el sistema dice: *No lo sé con los documentos disponibles*.
5. Podés subir tus propios PDF/TXT desde "Subir PDF/TXT"; la barra muestra los chunks indexados en tiempo real.

## Alcance y decisiones de diseño

Este prototipo es local y deliberadamente chico. Las decisiones están detalladas en `docs/decisiones.md`; las principales son:

- **Sin fuentes externas.** Qdrant solo recibe chunks de archivos subidos o de los documentos semilla. No hay crawler ni buscador web: si la respuesta no está en los documentos, el modelo lo dice.
- **Embeddings y respuestas en Ollama.** `nomic-embed-text` (768 dimensiones) para vectores y `llama3.2:3b` para generación, con `OLLAMA_HOST=http://ollama:11434`.
- **Chunks de 500 caracteres con overlap de 50**, con metadata `doc_id`, `doc_title`, `chunk_index` y `page`.
- **Top 4 chunks** por pregunta y numeración `[Doc N]` estable por id de documento, para que `[Doc 2]` signifique lo mismo en todas las preguntas.
- **Postgres guarda documentos, preguntas y respuestas**; Qdrant guarda los chunks y su payload. Las citas clicables se recuerdan en el evento `citations` del stream.
- **Semillas por el endpoint real.** Un contenedor one-shot sube los `.txt` de `docs/seed/` mediante `POST /api/upload`, para que la demo use exactamente el mismo pipeline que un usuario.
- **Un solo comando.** Los modelos se descargan al arrancar y los healthchecks ordenan la secuencia infraestructura → modelos → backend → semillas → frontend.

### A propósito NO se implementa

- Crawler web
- Buscador web
- Fine-tuning
- Evaluación de RAG
- Audio overview (podcast) de NotebookLM
- Guardrails avanzados

## Arquitectura

```
navegador → frontend (5173) → backend FastAPI (8000) → Qdrant (6333) + Postgres (5432) + Ollama (11434)
```

| Servicio | Responsabilidad |
|---|---|
| `backend/main.py` | endpoints, schema y readiness |
| `backend/upload.py` | extracción, chunking e indexación con progreso SSE |
| `backend/search.py` | embeddings y búsqueda top 4 |
| `backend/answer.py` | prompt con citas, streaming SSE y persistencia |
| `frontend/src/App.tsx` | UI, parser SSE y modal de citas |

## Verificación manual

```bash
curl -s localhost:8000/api/ready
curl -s localhost:8000/api/documents | head -c 500
curl -N -X POST localhost:8000/api/ask -H 'Content-Type: application/json' \
  -d '{"question":"¿Qué ventaja tiene un enlace corto de Bitly?"}'
```

Esperado: `ready: true`, 3 documentos, y un stream con eventos `citations`, `token` y `done`.

## Apagar

```bash
docker compose down
```

Los volúmenes se conservan; para borrar también los datos y los modelos: `docker compose down -v`.
