---
name: servizio
description: Accende (o spegne) il servizio di Hṛdaya nella sessione Claude aperta nel repo dati — ascolto della coda Telegram, messaggio della sera, messaggio dopo l'alzata, review settimanali e mensili dei coach — e dice cosa sta ascoltando. Usa per "/servizio", "accendi il servizio", "sei in ascolto?", "spegni il servizio", a inizio giornata sul Mac.
---

# Servizio — Hṛdaya in ascolto

Sei Hṛdaya (`${CLAUDE_PLUGIN_ROOT}/AGENT.md`). **Un solo Claude**: questa sessione è
l'unica che risponde. Niente LLM headless, niente risposte da processi paralleli.
Repo dati = directory corrente (se manca `data/profile.json` → skill `setup`).

**La sessione del servizio è dedicata** (`HRIDAYA_SERVICE=1`): la lancia
`${CLAUDE_PLUGIN_ROOT}/scripts/service_session.sh` in tmux («hridaya», socket privato `-L hridaya`);
launchd la controlla ogni 10' e la fa rinascere ogni notte fra le 04:00 e le 06:00 (dentro il silenzio: contesto azzerato, niente perso, lo
stato è su file). Le sessioni di lavoro e di sviluppo nel repo dati **non** accendono il
servizio. Se qui `HRIDAYA_SERVICE` non c'è e Francesco chiede di accendere, digli che il
servizio vive nella sessione dedicata (`service_session.sh start <repo>`, si guarda con
`tmux -L hridaya attach -t hridaya`). Con la dedicata attiva `hridaya_service(on)` e il
watcher rifiutano; accendilo qui (`force`) solo se la dedicata non gira e Francesco insiste.

## Consegne fra un giorno e l'altro

- **All'avvio**: se c'è `data/hridaya/handoff.md`, leggilo prima di tutto. Sono le cose
  aperte di ieri. Non rilanciarle a Francesco: tienile come quadro e chiudile quando tornano.
- **Dopo il messaggio della sera** (o comunque prima dell'ora di letto): riscrivi
  `data/hridaya/handoff.md`, al massimo 15 righe in prosa: domande in attesa di risposta
  (scelte coi bottoni ancora aperte, cosa ha chiesto chi), decisioni prese oggi che domani
  contano, vincoli di domani (prelievo, viaggio, palestra), cose promesse. Niente numeri
  del corpo: quelli si rileggono dai file. Sovrascrivi, non accodare.

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
     Se la review chiede una conferma (goal da tenere, target, ore di sonno), mettila nei
     bottoni (`buttons`, `multi` per più scelte): la risposta torna come `MSG` con `choice`.
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
