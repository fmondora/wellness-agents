---
name: propagate
description: Propaga le scoperte post-sessione nelle memorie degli agenti e nella knowledge base del repo dati. Usa dopo un council, un ask significativo, un log importante, o quando l'utente dice "propaga".
---

# Propagate — distribuzione delle scoperte

Non rispondere all'utente con un report lungo: aggiorna la memoria in silenzio,
poi changelog compatto (max 10 righe: file toccati, cosa è stato aggiunto).

**Repo dati:** directory corrente. **Protocollo completo:**
`${CLAUDE_PLUGIN_ROOT}/agents/propagator/AGENT.md` — leggilo e seguilo.

## Processo

1. **Estrai scoperte** dalla sessione: condition, correlation, hypothesis,
   protocol, confirmation. Nessuna novità → rispondi solo
   `Propagazione: nessuna novità.` e fermati.
2. **Mappa destinatari** (dal protocollo): memorie in `memory/agents/<nome>.md`
   (fallback legacy `domains|traditions/<nome>/memory.md`) SOLO per agenti
   installati/presenti; kb del repo dati (`kb/scoperte.md` per cross-domain,
   `kb/condizioni.md`/`terapie.md`/`esami.md` per il clinico oggettivo);
   `data/profile.json` solo se strutturale.
3. **Scrivi** entry nel formato standard:
   `## YYYY-MM-DD — Titolo` + testo + `**Implicazione**: ...`
4. Mai duplicare entry esistenti. Mai propagare rumore (mood passeggero senza pattern).

**Runtime note:** su Hermes usa delegation/background job; su Grok
`spawn_subagent background:true`; su Claude Code il tool Agent in background.
La logica non cambia.
