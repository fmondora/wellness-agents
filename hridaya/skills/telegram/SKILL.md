---
name: telegram
description: Il generalista processa la coda messaggi Telegram (data/telegram/inbox.jsonl → outbox.jsonl): triage, risposte di primo livello, ask/council quando serve, chiusura delle domande aperte del detector. Usa per "processa telegram", "/telegram", o se ci sono messaggi pending a inizio sessione.
---

# Telegram — la porta d'ingresso del generalista

Sei il generalista (identità: `${CLAUDE_PLUGIN_ROOT}/AGENT.md`). Il bot nel
repo dati riceve i messaggi e li mette in coda; TU li processi e scrivi le
risposte. Il bot invierà le righe di outbox non ancora inviate.

**Repo dati:** directory corrente.
**Coda:** `python3.12 ${CLAUDE_PLUGIN_ROOT}/scripts/telegram_queue.py pending`
(o Read `data/telegram/inbox.jsonl` filtrando `"status": "pending"`).

## Fase 0 — Red flag

Se manca `data/profile.json`: il repo dati non è inizializzato — avvia la skill `setup` del plugin generalista (o proponila) invece di fermarti con un errore.

Messaggio con red flag clinico → in outbox SOLO l'escalation al medico/pronto
soccorso, nient'altro.

## Fase 1 — Risposte a domande aperte del detector

PRIMA di trattare un pending come query, controlla
`data/insights/state.json` → `open_questions`. Un pending è una RISPOSTA se:
- `reply_to_text` contiene (anche parzialmente) il testo della domanda, OPPURE
- c'è una open question con `asked_at` < 24h e il messaggio non è un comando
  né una domanda, ed è plausibilmente la risposta

Se è una risposta: scrivila nel log di oggi al `log_target` della question
(merge), chiudi la question (rimuovi da state.json, aggiorna l'evento in
`data/insights/events/` con `answer` e `answered_at`), ack breve e caldo in
outbox, `done --id`. Question con `asked_at` > 24h → scadute, rimuovile.

## Fase 2 — Ogni messaggio pending (triage del generalista)

1. Contesto: profilo, ultimi 3 log, log di oggi, kb rilevante
2. Triage (tabella nell'AGENT.md):
   - cosa semplice / dato da registrare → rispondi TU e aggiorna il log
   - `/council` o esplorazione profonda → skill **council** del core
   - domanda specifica di dominio → skill **ask** del core
3. Risposta in outbox:
   `python3.12 ${CLAUDE_PLUGIN_ROOT}/scripts/telegram_queue.py reply --id <ID> --text "..."`
4. `... done --id <ID>`

## Fase 3 — Metriche nel messaggio

Se il messaggio contiene vitali (HRV, FC), aggiornali anche nel log di oggi
(`morning.hrv`, `morning.heart_rate`).

## Tono

Italiano, caldo, conciso da Telegram (max ~3500 caratteri, spezza se serve).
Mai JSON a schermo.
