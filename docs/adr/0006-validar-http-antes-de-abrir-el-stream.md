# Validar con códigos HTTP antes de abrir el stream

La extensión inválida, el archivo mayor a 10 MB, el PDF sin texto extraíble y la pregunta vacía se validan en la ruta, antes de construir la `StreamingResponse`, y devuelven `400` o `422`. Los fallos que ocurren durante la generación, como un error de Ollama, se emiten como evento SSE `error`.

## Alternativas descartadas

- **Validar dentro del generador SSE**: FastAPI ya envió `200` cuando se emite el error, así que `curl --fail` —usado por `seed-docs`— no lo detecta y la aplicación arranca "verde" con menos documentos.
- **Devolver siempre `200` con un evento `error`**: obliga a cada cliente a interpretar dos capas de error y rompe el contrato HTTP que describe el spec.
