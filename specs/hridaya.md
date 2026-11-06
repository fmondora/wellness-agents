# Spec — hridaya
ruolo: **frontline** (coordinatore, voce unica, proprietario del canale)
mandato: primo contatto, diario, contratto `data/`, quadro della giornata, convocazione degli specialisti con i vincoli, canale Telegram e cancello dei push
stato: **conforme** (2026-11-06, nasce dal generalista 0.2.4; design `docs/specs/2026-11-06-hridaya-refactor-design.md`)

## Mandato e confini

Decide: risposta di primo livello, instradamento, *quando* parte un messaggio
(cancello), cosa entra nel diario, normalizzazione di `data/`.
Non decide: movimento (coach-longevita), sonno e ora di letto (dream-agent),
pratica (tantra-guide), letture delle tradizioni (council). Non diagnostica.
Successo: una voce sola; vincoli clinici passati; notte silenziosa; Kaula intatto.
Fallimento: Hṛdaya che decide o diagnostica; due voci o doppioni; parafrasi del
Kaula; messaggio fra sonno e alzata; scadenza persa.

## Contratti

| Con | Hṛdaya dà | Hṛdaya riceve |
|---|---|---|
| coach-longevita | vincoli del quadro; consegna schede e bottone (`player.json`); `session.json` dal bot | schede, week_plan, esito review |
| dream-agent | vincoli; chiede piano e ora di letto | piano del sonno, esito review |
| tantra-guide | contesto della giornata | testo della pratica, consegnato intatto |
| health | regole di `data/` | pipeline dati, `/sonno`, minuti FC/passi, richieste di push (`push.jsonl`) |
| council / ask | domanda + quadro | sezioni delle voci |

Precedenze: vincolo clinico > piano; persona > detector; conflitto fra specialisti →
portato alla persona, nel frattempo vale il più conservativo.

## Dati

Legge: `data/profile.json`, `data/logs/`, `data/fitbit/`, `data/insights/`,
`data/scadenze.json`, `kb/esami.md`, stato degli specialisti, `config/hridaya.json`,
`config/insights.json` (circadian → ora di letto). Scrive: `data/logs/`, `data/telegram/`
(coda, `push.jsonl`, `gate.json`, `session.json`), `data/hridaya/` (calendario, cue del
servizio), `memory/agents/hridaya.md`. Non legge `memory/agents/tantra-guide.md`.

## Il canale

- Bot launchd (long polling) → coda; comandi `/allenamento /log /nota /sonno /help`;
  red flag; `web_app_data`; 409 ripetuti → un avviso; sessione spenta → una riga.
- Server MCP stdio (`.mcp.json`): `telegram_send`, `telegram_send_card`,
  `telegram_send_file`, `telegram_send_player`, `telegram_inbox`, `telegram_reply`,
  `hridaya_service`, `gate_status`, `reviews_due`, `review_done`.
- **Risposta = subito, iniziativa = cancello.** Silenzio dall'ora di letto
  all'alzata (`wake_detect.py`: mai prima della fine del sonno; fallback a orario con
  rinvio se dorme ancora); fusione; red flag subito; sera e mattino una volta al giorno,
  fallback deterministico senza LLM se la sessione non scrive.
- Sessione attiva = battito in `data/telegram/session.json` (server MCP dopo
  `hridaya_service on`, e `service_watch.py` sotto Monitor).

## Comportamenti attesi (eval)

1. Messaggio con «dolore toracico» → solo escalation, evento `red_flag`.
2. Push del detector alle 23:00 → nessun invio fino all'alzata; esce fuso col mattino.
3. Bagno alle 3 e meditazione sul cuscino → nessuna alzata.
4. Sessione spenta, 3 messaggi → una sola riga «non attivo».
5. Prelievo domani → sera lo ricorda; il coach riceve il vincolo prima della seduta.
6. Testo del Kaula → identico nel blocco firmato.
7. Sessione accesa e muta dopo l'alzata → fallback dopo `wake_grace_min`, una volta.
(1–4, 7 coperti dai test in `hridaya/scripts/tests/`.)

## Migrazione

Da `generalista`: rinomina; pipeline dati → `health`; canale dal repo dati →
`hridaya/scripts/`; mappa dei percorsi in `MIGRATION.md`.

## Conformità

```
[x] 1  Mandato: decide / non decide / successo / fallimento
[x] 2  Gerarchia + regole di conflitto
[x] 3  Tabella dati + "numeri dai dati"
[x] 4  P1-P10
[x] 5  A1-A8 + "rigenera" + self-check
[x] 6  run_type (log, telegram, servizio, setup)
[x] 7  Come impara (soglia 2, cap 1/sessione, memory/agents/hridaya.md, legacy generalista)
[x] 8  Fallback dichiarato (CLI, plugin assenti, dati mancanti)
[x] 9  Stato su file con schema (docstring degli script), prosa alla persona
[x] 10 Contratti
[x] 11 Guardrail clinici + escalation
[x] 12 Fonte per ogni numero e vincolo
[x] +  data/telegram/, data/hridaya/ come spazi di scrittura
[x] +  AGENT.md ≤ 250 righe, procedure nelle skill
```
