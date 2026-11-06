# Adapters — altri runtime

Le identità (`AGENT.md`) e gli script sono runtime-neutri. Solo il packaging
cambia per runtime. Un adapter non duplica contenuto: punta ai file del repo.

## Claude Code (nativo)

```
claude plugin marketplace add <path-o-github>/wellness-agents
claude plugin install wellness-core hridaya coach-longevita
```
Le skill usano `${CLAUDE_PLUGIN_ROOT}` per i file del plugin e path relativi
alla cwd per il repo dati.

## Grok Build / Grok TUI

Le skill sono già scritte Grok-aware (spawn_subagent al posto del tool Agent).
Setup: symlink o copia delle directory `<plugin>/skills/*` nella directory
skill di Grok, e le identità restano lette da questo repo. Sostituire
`${CLAUDE_PLUGIN_ROOT}` con il path assoluto di questo repo (vedi
`grok/install.sh`).

## Hermes (tolto)

L'adapter Hermes è stato rimosso il 6/11/2026: leggeva lo stesso token Telegram del
canale di Hṛdaya e gli rubava i messaggi (409 Conflict). Il canale ha un solo lettore:
il bot del plugin `hridaya`.
