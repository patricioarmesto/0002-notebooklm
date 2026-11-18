# Alcance limitado a documentos subidos

El sistema solo puede responder desde lo que el usuario subió: la colección Qdrant no tiene ninguna ruta hacia fuentes web. Decidimos excluir explícitamente crawler, buscador web, fine-tuning, evaluación de RAG, audio overview y guardrails avanzados. Ante una pregunta sin evidencia, la respuesta es literalmente *"No lo sé con los documentos disponibles"*.

## Alternativas descartadas

- **Buscar en la web cuando el contexto no alcanza**: rompe la garantía central del ejercicio —toda afirmación debe tener una cita verificable en un documento— y requiere servicios externos.
- **Fine-tuning del modelo**: caro y lento, y no enseña el mecanismo de recuperación que es el objetivo de la semana.
- **Evaluación automática de RAG y guardrails**: aportan valor en producción, pero suman servicios y conceptos que el nivel de este ejercicio no necesita.
