# IDs UUIDv5 deterministas para los puntos de Qdrant

Qdrant solo acepta enteros o UUID como identificador de punto. Decidimos derivar cada ID con UUIDv5 desde `<doc_id>:<chunk_index>` en el namespace URL. Así, reindexar un chunk sobrescribe el punto existente en lugar de duplicarlo, y el ID puede reconstruirse en cualquier proceso o reinicio.

## Alternativas descartadas

- **UUID aleatorio**: cada reingesta crearía puntos nuevos y dejaría vectores viejos accesibles, con citas que apuntan a texto descartado.
- **Entero autoincremental**: depende del orden global de inserción y no puede reconstruirse desde el documento y su chunk sin consultar Qdrant.
- **Usar solo `chunk_index`**: colisiona entre documentos distintos, porque todos empiezan en cero.
