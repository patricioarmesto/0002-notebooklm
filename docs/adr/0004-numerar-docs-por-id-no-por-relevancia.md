# Numerar los documentos por `id`, no por relevancia

Las citas `[Doc N]` deben significar lo mismo en cualquier pregunta y coincidir con la lista del frontend. Decidimos asignar `N` según el orden de `documents.id`, aunque el chunk más relevante pertenezca al documento 3: el ranking decide qué contexto se incluye, no cómo se nombra cada fuente.

## Alternativas descartadas

- **Numerar por puntaje de similitud**: la misma fuente cambiaría de número entre preguntas, las citas dejarían de ser estables y el modal del frontend podría abrir el documento equivocado.
- **Identificar por título en la respuesta**: legible para una persona, pero no coincide con el formato `[Doc N]` que muestra la UI y obligaría a parsear cadenas en el cliente.
