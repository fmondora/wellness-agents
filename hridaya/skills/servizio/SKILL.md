---
name: servizio
description: Accende (o spegne) il servizio di Hṛdaya nella sessione Claude aperta nel repo dati — ascolto della coda Telegram, messaggio della sera, messaggio dopo l'alzata, review settimanali e mensili dei coach — e dice cosa sta ascoltando. Usa per "/servizio", "accendi il servizio", "sei in ascolto?", "spegni il servizio", a inizio giornata sul Mac.
---

# Servizio — Hṛdaya in ascolto

Sei Hṛdaya (`${CLAUDE_PLUGIN_ROOT}/AGENT.md`). **Un solo Claude**: questa sessione è
l'unica che risponde. Niente LLM headless, niente risposte da processi paralleli.
Repo dati = directory corrente (se manca `data/profile.json` → skill `setup`).

## Accendere

1. **Battito** — tool `hridaya_service(action="on")`: il bot vede che ci sei e smette di
   rispondere «Hṛdaya non è attivo». Riporta `listening`, messaggi in coda, stato del
   cancello. (Senza MCP: il watcher del punto 2 batte da solo.)
2. **Ascolto** — tool **Monitor**, `timeout_ms: 1800000`, descrizione «Hṛdaya: coda e ritmo»:
   `python3.12 ${CLAUDE_PLUGIN_ROOT}/scripts/service_watch.py --max-minutes 29`
   Alla scadenza (o all'uscita) **riarmalo** subito, sempre uguale.
   Ogni riga è un evento:
   - `MSG <id> …` → skill `telegram` su quel messaggio (`telegram_reply`)
   - `SYS wake …` / `MATTINO <data>` → messaggio dopo l'alzata (P7): `/sonno` + scadenze
     48 h, `telegram_send(kind="wake")`. `duplicate` = il fallback è già partito: basta.
     `too_late` = il mattino è passato (dopo `late_cutoff`): non insistere. Poi riprendi i
     messaggi rimasti in coda di notte (`telegram_inbox`: file e bottoni non partono di notte).
   - `SYS workout_session …` → proponi il debrief al Coach Longevità
   - `SYS red_flag …` → verifica l'escalation, nient'altro
   - `SERA <data>` → messaggio della sera (P6): lancia il subagente `tantra-guide:kaula`
     (tool Agent; tipo `meditazione_sera`; brief: HRV/semaforo, carico, sonno, emozioni del
     diario, vincoli di domani — il curriculum e la memoria li legge lui); componi: blocco «🕉️ Kaula» **intatto** + ora di letto
     (DreamAgent / `gate_status.bedtime`) + prelievo domani se c'è (`data/scadenze.json`,
     `kb/esami.md`). `telegram_send(kind="evening", parse_mode="HTML")`. `too_late` = è
     già ora di letto: non insistere.
   - `REVIEW <job>` → avvia la skill dello specialista col run_type del job
     (`coach-longevita` weekly/monthly_review, `dream-agent` weekly/monthly_review),
     consegna l'esito firmato con `telegram_send(kind="review")`, poi `review_done(job)`.
3. **Messaggi già in coda** — se `telegram_inbox` ne ha, processali (skill `telegram`).
4. **Di' cosa stai ascoltando**, in tre righe: coda Telegram (quanti in attesa), sera alle
   `evening_message` con ora di letto `bedtime`, alzata (stato del cancello: silenzio sì/no,
   alzata vista alle…), review dovute. E ricorda: la sessione va tenuta aperta sul Mac.

## Stato / spegnere

- «sei in ascolto?» → `hridaya_service(action="status")` + `gate_status`, in prosa.
- «spegni» → ferma il Monitor (TaskStop) e `hridaya_service(action="off")`: da lì il bot
  risponde «non attivo» e sera/mattino vanno in automatico.

## Regole

- Il cancello decide il *quando*: non mandare iniziative fuori da `telegram_send`.
- Un messaggio della sera e uno dopo l'alzata al giorno: lo garantisce il cancello, tu
  non forzare (`urgent` solo per red flag).
- Di notte nessuna iniziativa: gli eventi `REVIEW` dopo l'ora di letto si rimandano al
  mattino (il cancello li tratterrebbe comunque).
