# Adapters — altri runtime

Le identità (`AGENT.md`) e gli script sono runtime-neutri. Solo il packaging
cambia per runtime. Un adapter non duplica contenuto: punta ai file del repo.

## Claude Code (nativo)

```
claude plugin marketplace add <path-o-github>/wellness-agents
claude plugin install wellness-core coach-longevita
```
Le skill usano `${CLAUDE_PLUGIN_ROOT}` per i file del plugin e path relativi
alla cwd per il repo dati.

## Grok Build / Grok TUI

Le skill sono già scritte Grok-aware (spawn_subagent al posto del tool Agent).
Setup: symlink o copia delle directory `<plugin>/skills/*` nella directory
skill di Grok, e le identità restano lette da questo repo. Sostituire
`${CLAUDE_PLUGIN_ROOT}` con il path assoluto di questo repo (vedi
`grok/install.sh`).

## Hermes

Usa il meccanismo `delegation:` in `~/.hermes/config.yaml` (children con
model/provider override, max_concurrent_children, inherit_mcp). Snippet di
esempio in `hermes/delegation-example.yaml`. La sequenza fasi, i brief JSON
e i formati output NON cambiano: solo l'orchestrazione dei subagent.
