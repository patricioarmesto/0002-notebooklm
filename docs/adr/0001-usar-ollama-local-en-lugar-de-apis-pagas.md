# Usar Ollama local en lugar de APIs pagas

El ejercicio debe funcionar en una máquina con un solo `docker compose up`, sin claves ni costos. Decidimos correr `llama3.2:3b` y `nomic-embed-text` en un contenedor Ollama local y descargarlos en un servicio `model-pull` antes de arrancar el backend. El host se inyecta por `OLLAMA_HOST`, así que cambiar de modelo no cambia el contrato HTTP.

## Alternativas descartadas

- **OpenAI o Anthropic**: requieren API key y pago, y rompen el objetivo de un prototipo autocontenido y reproducible sin credenciales.
- **Ollama instalado en el host**: obliga al alumno a instalar algo fuera del repo y hace que `docker compose up` no alcance por sí solo.
