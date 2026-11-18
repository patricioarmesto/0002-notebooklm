# Decisiones de diseño — 0002 NotebookLM

Ejercicio 0002 de 1024 del curso "¿Cómo funciona...?". Nivel medio, semana 2 del ciclo.

## Objetivo

Prototipo funcional de NotebookLM: el usuario sube documentos, el sistema los indexa y después responde preguntas usando **solo** esos documentos, con citas verificables. Debe quedar andando con un solo `docker compose up`.

## Requisitos fijados

- Backend IA: Python + FastAPI.
- Frontend: React + Vite + Tailwind.
- Vector DB: Qdrant para chunks.
- Base de datos: Postgres para documentos, preguntas y respuestas.
- LLM: Ollama local en Docker, `llama3.2:3b` para respuestas y `nomic-embed-text` para embeddings. Sin APIs pagas. `OLLAMA_HOST=http://ollama:11434`.
- Chunks de 500 caracteres con overlap de 50; metadata `{ doc_id, doc_title, chunk_index, page }`.
- Top 4 chunks por pregunta; prompt que obliga a citar `[Doc 1]`, `[Doc 2]` y a decir que no sabe si la respuesta no está en los documentos.
- Streaming token a token con Server-Sent Events.
- Tres documentos semilla: Bitly, Kafka y System Design.
- README con sección "Alcance y decisiones de diseño".

## Arquitectura

Servicios de `docker-compose.yml`:

| Servicio | Imagen / rol |
|---|---|
| `postgres` | `postgres:16-alpine`, base `notebooklm`, volumen persistente |
| `qdrant` | `qdrant/qdrant`, puerto 6333, volumen persistente |
| `ollama` | `ollama/ollama`, puerto 11434, volumen `ollama_data` |
| `model-pull` | one-shot, imagen Ollama; descarga `llama3.2:3b` y `nomic-embed-text` |
| `backend` | Python 3.12 + FastAPI, puerto 8000 |
| `seed-docs` | one-shot con `curl`, sube `docs/seed/*.txt` al endpoint real de upload |
| `frontend` | Node 20 + Vite dev server, puerto 5173 |

Los puertos indicados son los internos de la red de Compose. En el host, `POSTGRES_PORT` y `FRONTEND_PORT` default a `5433` y `5174` para no chocar con otros proyectos que ya ocupan `5432` y `5173`; se pueden override con variables de entorno. `backend` (8000), Qdrant (6333) y Ollama (11434) conservan su mapeo.

`model-pull` termina con éxito antes de que arranque `backend` (`depends_on: service_completed_successfully`). `seed-docs` depende de `backend` y termina antes de que arranque `frontend`. Orden real: infraestructura → modelos → backend → semillas → frontend. El frontend espera a `GET /api/ready`.

### Estructura de archivos

```
0002-notebooklm/
├── README.md
├── docker-compose.yml
├── docs/
│   ├── decisiones.md
│   └── seed/{bitly,kafka,system-design}.txt
├── backend/
│   ├── Dockerfile
│   ├── main.py
│   ├── upload.py
│   ├── search.py
│   ├── answer.py
│   └── requirements.txt
└── frontend/
    ├── Dockerfile
    ├── index.html
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.js
    ├── postcss.config.js
    └── src/{main.tsx,App.tsx,index.css}
```

Los archivos fuera del árbol original son necesarios para que un solo `docker compose up` construya y arranque todo.

### Modelo de datos

Postgres, creado de forma idempotente en el `lifespan` de FastAPI:

- `documents(id, title, filename, source_type, chunk_count, created_at)`.
- `questions(id, text, created_at)`.
- `answers(id, question_id → questions.id, text, citations JSONB, created_at)`.

Qdrant, colección `notebooklm_chunks`, distancia coseno, dimensión 768 (`nomic-embed-text`), puntos con id UUID v5 determinista derivado de `<doc_id>:<chunk_index>` (Qdrant solo acepta enteros o UUID), idempotentes en reingestas. Payload: `doc_id`, `doc_title`, `chunk_index`, `page`, `text`.

## Flujo de datos

### Upload

1. `POST /api/upload` multipart con `file` y `title` opcional.
2. Validar extensión `.pdf` / `.txt` y tamaño máximo de 10 MB.
3. Extraer texto: `pypdf` preservando página por página; TXT plano como `page = 1`.
4. Dividir en chunks de 500 caracteres con overlap de 50, llevando la página de origen.
5. Embedding por chunk con `nomic-embed-text` y upsert en Qdrant con su payload.
6. Insertar la fila en `documents` con `chunk_count`.
7. Emitir SSE con eventos `progress` (`phase`, `processed`, `total`) y `done` (`doc_id`, `title`, `chunk_count`). El frontend usa `fetch` + `ReadableStream` porque `EventSource` no soporta POST.

### Pregunta

1. `POST /api/ask` con `{"question": "..."}` devuelve `text/event-stream`.
2. Embedding de la pregunta con `nomic-embed-text`.
3. Búsqueda top 4 por coseno en `notebooklm_chunks`. La colección solo contiene documentos subidos o semillas: no hay camino hacia fuentes web.
4. `[Doc N]` se asigna por orden de `documents.id`, no por similitud, para que la numeración sea estable entre preguntas.
5. Prompt: responder solo con el contexto numerado, citar como `[Doc N]`, y ante la ausencia de evidencia responder literalmente *"No lo sé con los documentos disponibles"*.
6. `llama3.2:3b` con `stream: true`. SSE: `citations` primero, `token` por cada token, `done` al final. Cada entrada de `citations` contiene `n`, `doc_id`, `chunk_id`, `doc_title`, `page` y `chunk_index`.
7. Persistir `questions`, `answers` y el JSON de citas al completar.

### Frontend

Panel izquierdo: lista de documentos, botón de subida PDF/TXT y barra de progreso alimentada por los eventos SSE del upload. Centro: caja de pregunta y respuesta en streaming; un regex convierte `[Doc N]` en botones clicables que consultan `GET /api/chunks/{id}` y abren un modal con el texto original, título, página e índice de chunk. Sin documentos: *"Subí un documento para empezar"*. Las semillas aparecen desde el primer arranque.

## Errores

- `/api/ready` → `503` con dependencias faltantes; el frontend muestra "Inicializando…" y reintenta.
- Fallo de `model-pull` → contenedor termina con error y el backend no arranca; se diagnostica con `docker compose logs`.
- Extensión inválida o >10 MB → `400`. PDF sin texto extraíble → `422`, sin chunks parciales.
- Fallo de embedding/upsert a mitad de un upload → compensación best-effort: borrar puntos insertados y no crear la fila en `documents`.
- Pregunta vacía → `400`. Error de Ollama en streaming → evento SSE `error`, sin persistir respuesta parcial.

## Verificación

Smoke test documentado en el README: `GET /api/ready` → 200; `GET /api/documents` → 3 semillas; `POST /api/ask` sobre Bitly → tokens y evento `citations` con `[Doc N]`; subir un `.txt` propio → aparece en la lista y su cita abre el chunk correcto.

## Alcance explícitamente excluido

Crawler web, buscador web, fine-tuning, evaluación de RAG, audio overview (podcast) de NotebookLM y guardrails avanzados.
