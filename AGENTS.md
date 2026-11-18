# AGENTS.md

## Proyecto

- `docs/decisiones.md` es el spec aprobado. Leelo antes de cambiar comportamiento y respetá sus decisiones y exclusiones.
- `docs/superpowers/plans/2026-11-18-notebooklm-prototype.md` registra el plan ejecutado y las interfaces entre módulos.
- Para arranque, puertos y verificación manual, seguí `README.md`: es la fuente de verdad, no la dupliques acá.

## Convenciones

- Cambio de comportamiento: test primero (RED → GREEN). Antes de darlo por listo, corré los tests de backend y frontend, `npm run build` y `docker compose config -q`.
- Afirmá un resultado de verificación solo después de haber ejecutado el comando en la sesión actual.
- Fuera de alcance salvo pedido explícito: crawler web, buscador web, fine-tuning, evaluación de RAG, audio overview (podcast) y guardrails avanzados.

## Agent skills

### Issue tracker

Issues live in GitHub Issues, using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles use same-named GitHub labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
