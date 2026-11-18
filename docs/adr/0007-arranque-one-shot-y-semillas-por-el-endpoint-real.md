# Arranque orquestado con servicios one-shot y semillas por el endpoint real

Un solo `docker compose up` debe dejar la aplicación lista. Decidimos encadenar `depends_on` con `service_healthy` y `service_completed_successfully`: infraestructura → `model-pull` → backend → `seed-docs` → frontend. Las tres semillas se suben con `curl` al endpoint real de upload, no se insertan directamente en la base.

## Alternativas descartadas

- **Script `init` dentro de Postgres**: deja los documentos en la base pero no crea los puntos de Qdrant ni ejercita el pipeline de chunking y embeddings.
- **Semillas insertadas por código interno del backend**: más rápido, pero el arranque no verificaría la ruta de upload que usa el usuario, así que un bug en ese endpoint pasaría desapercibido.
- **Esperas fijas con `sleep` entre servicios**: frágiles en máquinas lentas; los healthchecks y las condiciones de Compose hacen el orden determinista.
