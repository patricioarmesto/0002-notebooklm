# Separar Qdrant de Postgres para la búsqueda vectorial

El prototipo necesita dos cosas distintas: persistencia relacional de documentos, preguntas y respuestas, y búsqueda por similitud de vectores. Decidimos Postgres para lo primero y Qdrant para lo segundo, con la colección `notebooklm_chunks` (coseno, 768 dimensiones). La separación hace explícita la frontera entre datos del dominio e índice de recuperación.

## Alternativas descartadas

- **pgvector dentro de Postgres**: reduce servicios, pero mezcla el índice vectorial con el esquema transaccional que se crea en el `lifespan`, y oscurece para el alumno la diferencia entre una base de datos y una vector DB.
- **FAISS en memoria del backend**: más liviano, pero pierde persistencia: al reiniciar habría que reindexar todo antes de que `GET /api/chunks/{id}` pueda mostrar el texto original de una cita.
