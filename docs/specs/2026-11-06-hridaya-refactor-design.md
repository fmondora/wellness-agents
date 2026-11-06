# Hṛdaya e il riordino degli agenti — design

*6 novembre 2026 · deciso in conversazione con Francesco · due repo: `wellness-agents` (marketplace) e il repo dati `lucia`*

## Perché

Oggi il sistema risponde «a pezzi». Telegram è sparso in tre posti: il bot e i push nel repo dati, la coda nel
plugin `generalista`, il player nel repo dati. L'orchestrator vive solo nel `CLAUDE.md` di lucia e non ha voce
fuori da una sessione Claude. In lucia restano 15 identità di agenti (`AGENT.md`), quasi tutte doppioni dei plugin,
e le memorie sono in due formati. Il 6/11 un coach ha prescritto una seduta intensa il giorno prima di un
prelievo perché nessuno teneva il quadro, e il bot ha perso messaggi per settimane perché un secondo processo
(Hermes) usava lo stesso token.

Francesco vuole **una figura sola con cui parlare**, soprattutto su Telegram: un coordinatore che «rispetta il suo
Sé più profondo», tiene il quadro della giornata e chiama lo specialista giusto. Il nome è **Hṛdaya** («il cuore»
nello shivaismo kashmiro: il centro da cui tutto si irradia e a cui tutto torna). Su Telegram: «Hridaya».

Principio: **un frontman che parla, specialisti che decidono, script che trasportano.**
Regola dei repo: **i plugin sono chi sono gli agenti e cosa sanno fare; il repo dati da cui vengono invocati
tiene la memoria, la knowledge base e i dati della persona** (già in `core/CONVENTIONS.md`).

## Obiettivi

1. **Plugin `hridaya`** nel marketplace, al posto di `generalista` (rinomina, non affiancamento).
2. **Il canale Telegram appartiene a `hridaya`**: bot, menu comandi, coda, invio schede/file, bottoni del
   player, ritorno dei log, messaggi push. Nel repo dati restano token/config e piccoli shim.
3. **Bootstrap Telegram guidato** nella skill `setup` di Hṛdaya.
4. **Due iniziative proattive**: la sera la meditazione per il mattino dopo (Kaula); dopo l'alzata il racconto
   della notte (Hṛdaya). Di notte silenzio.
5. **Specialisti al loro posto**: player → `coach-longevita`; `lucia-coach` → nuovo plugin **DreamAgent**
   (sonno); pipeline dati del corpo (sync wearable, insights, trends) → `health`.
6. **Review settimanale e mensile dei coach** (Coach Longevità, DreamAgent), messe in calendario da Hṛdaya.
7. **Ordine nel repo dati**: fuori le identità locali, memorie tutte in `memory/agents/`, `CLAUDE.md` che
   rimanda a Hṛdaya invece di fare l'orchestrator.

## Non obiettivi

- Nuove capacità cliniche, nutrizione, ricette: **il nutrizionista è tolto per ora** (anche la parte
  nutrizione di `lucia-coach`, che va in archivio, non in DreamAgent).
- Nuovi messaggi proattivi oltre ai due sopra (e ai promemoria già esistenti).
- Riscrivere i contenuti degli specialisti: si spostano e si fondono, non si reinventano.
- UI nuove: tutto resta Telegram + file + skill (il player è già una Mini App dentro Telegram).

## Anti-obiettivi (sarebbe un fallimento anche se «funziona»)

- Hṛdaya che **decide** al posto degli specialisti (scrive schede, piani sonno, pratiche) o che diagnostica.
- Due voci davanti a Francesco (Hṛdaya e un altro frontman) o messaggi doppi dallo stesso evento.
- Hṛdaya che riassume o parafrasa il Kaula: le parole del Kaula arrivano **intatte**, firmate.
- Un messaggio che arriva di notte, fra il sonno e l'alzata (Francesco ai risvegli medita sul cuscino: il
  telefono non deve chiamarlo in quella soglia).
- Perdere memoria vissuta: niente viene cancellato senza traccia; le memorie degli agenti tolti si archiviano.
- Rompere il sistema attivo durante la migrazione: bot, sync Fitbit delle 8:00, daemon, player devono
  continuare a funzionare a ogni passo.
- Un repo dati che dipende da percorsi del repo `wellness-agents`: il repo dati parla solo coi plugin installati.

## Hṛdaya — l'agente

**Cosa è**: il primo contatto e il coordinatore. Eredita dal Generalista: accoglienza, diario (`/log`), contratto
dati (`data/`), prima risposta, triage verso `ask`/`council`, escalation red flag. Aggiunge:

- **Tiene il quadro della giornata**, leggero: sonno e semaforo, diario, eventi del detector, scadenze cliniche
  (`data/scadenze.json`, `kb/esami.md`: prelievi nelle 48 h), piani attivi degli specialisti. Un riassunto, non
  tutti i file.
- **Convoca e passa contesto**: allenamento → Coach Longevità; sonno → DreamAgent; pratica, meditazione,
  coppia, giornate «nere» → Kaula (`tantra-guide`); domande profonde → `council`. Quando passa la richiesta,
  allega i vincoli del quadro che lo specialista da solo non vede (es. «prelievo domani alle 8»).
- **Nota i conflitti fra specialisti** e li porta a Francesco, senza risolverli lui.
- **Voce unica**: parla sempre Hṛdaya; il lavoro di uno specialista arriva in un blocco firmato
  («🏋️ Coach Longevità», «🌙 DreamAgent», «🕉️ Kaula»). Può riassumere schede e piani in due righe; il Kaula mai.
- **Non legge la memoria intima del Kaula** (`memory/agents/tantra-guide.md`): la chiama, non la assorbe.
- **Non decide** allenamento, sonno, pratica; **non diagnostica**; tono: caldo, preciso, non prescrittivo, «specchio
  che riconosce» (fondamento in `core/foundation`).
- Memoria propria: `memory/agents/hridaya.md` nel repo dati.

Identità scritta secondo `specs/TEMPLATE.md` del marketplace (flusso spec-first degli agenti).

## Il canale Telegram (in `hridaya`)

Oggi nel repo dati, da spostare nel plugin (`hridaya/scripts/`), con shim nel repo dati come già per `health_sync`:

| Oggi in lucia `scripts/` | Cosa fa |
|---|---|
| `telegram_bot.py` (+ `telegram_queue.py` già nel plugin) | long polling, comandi `/allenamento /log /nota /sonno /help`, coda inbox/outbox, red flag, `web_app_data` |
| `workout_player.py` (parte bot) | decodifica e merge delle sedute del player, `setMyCommands`, scelta dell'ultimo `player.json` |
| `telegram_send_rich.py`, `telegram_send_file.py` | invio HTML + album, documenti |
| `morning_message.py`, `kaula_voice.py` | buongiorno 07:30 via launchd; voce headless (`claude -p`) — si spegne, resta il fallback deterministico |
| `telegram_get_chat_id.py` | bootstrap manuale del chat_id |

Gli altri script del repo dati **seguono il proprietario** (scelta di Claude, dettagli al costruttore): `lucia_daemon.py`,
`weekly_review_job.py`, `lucia_api.py`, `voice_ingest.py` → `hridaya` (orchestrazione e ingresso);
`webhook_receiver.py`, `register_webhook.py`, `meditation_detect.py` → `health` (ingestione e lettura dei dati del
corpo); `circadian_plan.py` → DreamAgent. Nel repo dati restano shim e plist.

Restano nel repo dati: `.env`/config (token, `ALLOWED_CHAT_IDS`, `WORKOUT_PLAYER_URL`), `data/telegram/*`, i
plist launchd che puntano agli shim. `telegram_ingest.py` (canale @tibetanbuddha per il Kaula) va in `tantra-guide`.

**Il canale è lo strumento di Hṛdaya** (deciso con Francesco): gli specialisti non parlano mai con Telegram,
producono contenuti e file; Hṛdaya spedisce, riceve e riporta. Il plugin `hridaya` espone il canale come **server
MCP** con tool tipo `telegram_send`, `telegram_send_card` (HTML + album), `telegram_send_file`,
`telegram_send_player` (reply keyboard web_app), `telegram_inbox`, `telegram_reply`. Il bot in long polling resta un
servizio launchd separato (riceve anche quando nessuna sessione è aperta); tool e bot condividono il modulo di
trasporto e la coda.

**Push e ritmo** (sostituiscono il buongiorno fisso delle 07:30):
- **Sera, ~22:00** (configurabile): il Kaula sceglie la meditazione per il mattino dopo guardando la giornata
  (HRV, carico, emozioni del diario, curriculum) e Hṛdaya la consegna intatta. Assorbe il nudge dell'ora di letto
  (oggi alle 21:00, `circadian_plan`): l'ora viene da `config` (oggi 22:15), non da questo documento.
- **Mattina, dopo l'alzata**: quando i dati al minuto (FC + passi, `rollup` 60 s già usato da
  `meditation_detect.py`) mostrano la fine del sonno seguita da movimento, Hṛdaya manda un messaggio solo: com'è
  andata la notte (`/sonno`) e, solo se la notte è stata davvero storta, una variante della pratica. Fallback se
  l'alzata non si vede entro un'ora configurabile: messaggio a quell'ora.
- **Fra sonno e alzata**: silenzio assoluto.
- I testi push li scrive la sessione attiva (vedi «Un solo Claude, attivo»); senza sessione, solo il fallback deterministico.
- **Cancello unico**: ogni push (anche quelli di `insights_engine`, `weekly_review_job`, `circadian_plan`,
  `morning_message`) passa da Hṛdaya, che applica la finestra di silenzio (dall'ora di letto all'alzata rilevata,
  non più le quiet hours fisse che finiscono alle 04:30) e fonde ciò che arriva nello stesso momento.
  Restano: messaggio della sera, messaggio dopo l'alzata, domande del detector su attività rilevate (accodate fuori
  dalla finestra, al massimo raggruppate), review dei coach. Il «consiglio trend» della domenica diventa le review
  settimanali dei coach. Le red flag cliniche restano immediate.
- **L'insegnamento tantrico si sposta alla sera** (scelta di Francesco del 6/11, per non chiamarlo al telefono al
  risveglio; la memoria «insegnamento al buongiorno» va aggiornata di conseguenza). Il messaggio dopo l'alzata porta
  la notte e le **scadenze nelle 48 h** (prelievi, preparazione); se domani c'è un prelievo lo ricorda anche la sera
  (digiuno, niente allenamento intenso).

**Review dei coach**: ogni settimana (weekly_review di Coach Longevità e di DreamAgent) e ogni 28 giorni
(monthly). Hṛdaya le mette in calendario, le fa partire e consegna l'esito firmato.

**Igiene del canale** (lezione Hermes): il bot rileva i `409 Conflict` ripetuti (un altro processo legge lo stesso
token) e lo segnala una volta su Telegram e nei log, invece di accumulare errori in silenzio.

## Bootstrap Telegram (skill `setup` di Hṛdaya)

Conversazione guidata, una domanda alla volta: creare il bot su BotFather dal telefono → incollare il token →
custodirlo nel portachiavi macOS (scelta di Claude; `.env` come fallback su altri sistemi; anche il token attuale
migra nel portachiavi) → `/start` al bot,
registrazione del chat_id come unico autorizzato, risposta di conferma sul canale → verifica che nessun altro
processo usi il token (`getUpdates` senza 409, `getWebhookInfo` vuoto) → installazione dell'avvio automatico e del
menu comandi → opzionale, se c'è `coach-longevita`: pubblicazione del player e demo di prova audio/schermo.

## Specialisti

- **Coach Longevità**: riceve il player (`apps/workout-player/` → `coach-longevita`: pagina, motore, voce
  pre-registrata, `deploy.sh`, `make_voice.py`, `workout_send.py`, `workout_fitbit.py`, test). La parte del bot che
  riceve i log resta nel canale di Hṛdaya; il formato `player.json`/`session.json` è il contratto fra i due.
  Assorbe le note utili di `functional-training` nella sua memoria (`memory/agents/coach-longevita.md`).
- **DreamAgent** (nuovo plugin): nasce da `lucia-coach` (`.claude/skills/lucia-coach/` nel repo dati) tenendo
  solo il sonno: target, àncore (ora di letto), piano settimanale del sonno, weekly/monthly review; prende
  `circadian_plan.py` (orari di letto a fine ciclo). Usa `health:sonno` per il punteggio. La parte nutrizione va in
  archivio. L'incastro della settimana nel calendario (oggi in `lucia-coach`) è coordinamento: passa a Hṛdaya.
- **health**: riceve la pipeline dati del corpo oggi in `generalista/scripts/` (`health_api`, `health_extract`,
  `health_metrics`, `health_sync`, `insights_engine`, `trends`) con i loro test; gli shim del repo dati si aggiornano.
  Hṛdaya resta proprietario del contratto `data/` (regole di precedenza), `health` del codice che lo riempie.

## Ordine nel repo dati (lucia)

Decisioni di Francesco del 6/11. «Togliere» = fuori dal repo, ritrovabile nella storia di git. Le memorie degli
agenti tolti vanno in `memory/archive/`.

| Elemento in lucia | Azione |
|---|---|
| `domains/{genomics,george,health,longevity}`, `guide/tantra`, `traditions/{ayurveda,functional-medicine,jyotish,shamanic-plants,tcm}`, `agents/propagator` | identità tolte **dopo** aver confrontato ogni `AGENT.md` locale con quello del plugin e portato nel plugin ciò che la copia locale ha in più; `memory.md` → `memory/agents/<plugin>.md` (fusa se esiste già); `knowledge/` locale confrontata e fusa nel plugin se generica, lasciata in `kb/` se personale |
| `domains/nutritionist` | tolto; memoria in archivio; plugin `nutritionist` fuori da `config/council.json` |
| `domains/cellulite` | tolto; memoria in archivio |
| `domains/functional-training` | tolto; note utili in `memory/agents/coach-longevita.md`, il resto in archivio |
| skill locali `goals`, `review`, `recipe` | tolte |
| skill locali `ask`, `council`, `dna`, `log` | tolte (restano quelle del marketplace) |
| skill locale `lucia-coach` | diventa DreamAgent (sopra) |
| `CLAUDE.md` (417 righe, oggi orchestrator) | riscritto corto: Hṛdaya è il punto d'ingresso; restano solo le cose davvero locali (data/ora, mappa dei file dati, guardrail clinici personali) |
| `memory/agents/` | unico formato di memoria; i riferimenti a `domains/*/memory.md` nelle skill e nei plugin diventano solo fallback legacy |

Nel marketplace: la cartella non pubblicata `functional-training/` si toglie; `adapters/hermes/` (Telegram via
Hermes, incompatibile con il canale di Hṛdaya sullo stesso token) si toglie o si marca deprecato — scelta di Claude:
toglierlo; tutti i riferimenti a `generalista` (README, CONVENTIONS, council/ask, coach-longevita, specs) passano a
`hridaya`; `marketplace.json`: `generalista` → `hridaya`, `+ dream-agent`, `nutritionist` resta pubblicato.

## Vincoli

- **Sorgente del marketplace durante la migrazione**: il marketplace installato punta oggi a GitHub
  (fmondora/wellness-agents) e i push sono solo su richiesta. Scelta di Claude: per la migrazione il marketplace
  installato passa alla cartella locale `~/wip/personal/wellness-agents`; a fine lavoro, su richiesta di Francesco, push
  e ritorno alla sorgente GitHub.
- Migrazione **a passi, ognuno lasciando il sistema funzionante**: launchd (`com.francesco.lucia.telegram`,
  `.morning`, `.daemon`, `com.lucia.health-sync`), shim, plugin installati. Prima si pubblica e installa il plugin
  nuovo, poi si spostano gli shim, poi si toglie il vecchio.
- Il repo dati trova i plugin solo via `~/.claude/plugins/cache/wellness-agents/<plugin>/*/` (come gli shim attuali).
- Python 3.12, nessuna dipendenza nuova; test esistenti (pytest nei plugin e in `lucia/scripts/tests`, `node --test`
  del player) verdi a ogni passo.
- Il bot gira in long polling sul Mac; nessun server nuovo esposto.
- Git: commit locali nei due repo, push solo su richiesta.

## Lasciato al costruttore

Struttura interna dei plugin e dei moduli, nomi dei file, formato del calendario push e delle review, euristica di
rilevamento dell'alzata (purché non mandi mai messaggi prima della fine del sonno), testi template di fallback,
ordine dei passi di migrazione entro i vincoli sopra, versioni dei plugin.

## Un solo Claude, attivo (deciso con Francesco)

Oggi ci sono due cervelli: la sessione Claude Code nel repo dati (con `CLAUDE.md`, plugin, skill, memorie, kb) e i
percorsi headless (`lucia_daemon.process_telegram` e `kaula_voice` lanciano `claude -p` con il system prompt
**sostituito** dai soli file del Kaula; `morning_message`/`circadian_plan` sono template). Francesco vuole **un solo
Claude**: la sessione Claude Code attiva nel repo dati, con tutto il contesto, che entra come Hṛdaya. Niente prompt
ridotti, niente risposte da processi paralleli.

- **Chi risponde**: solo la sessione attiva. Il bot riceve e accoda come oggi; la sessione si accorge dei messaggi
  nuovi (es. `Monitor` sulla coda) e risponde come Hṛdaya con gli strumenti del canale. I push programmati (sera,
  dopo l'alzata, review dei coach) li fa partire la sessione stessa (es. `CronCreate`/loop di sessione), con la
  rilevazione dell'alzata sui dati al minuto.
- **Si spengono**: `process_telegram` nel daemon e tutto `kaula_voice` headless (le funzioni utili, es. costruzione
  del contesto del Kaula, diventano parte delle skill). Il daemon resta per i lavori deterministici (sync, merge).
- **Se la sessione non è attiva**: il bot risponde una riga sola («Hṛdaya non è attivo adesso, ti rispondo appena
  torna») e accoda; nessun LLM parte da solo. Per i due messaggi programmati, scelta di Claude: un fallback
  **deterministico senza LLM** (dati del sonno, scadenze delle 48 h; la sera solo l'ora di letto), marcato come
  automatico, così le scadenze non si perdono; la meditazione della sera arriva solo dalla sessione.
- **Avvio**: la skill di Hṛdaya ha un comando per «accendere il servizio» nella sessione (attiva monitor e
  programmazioni, dice cosa sta ascoltando); `setup` spiega che la sessione va tenuta aperta sul Mac.
