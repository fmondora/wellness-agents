# Workout player (Telegram Mini App)

Timer a tutto schermo per le sedute del Coach Longevità, aperto dal bottone «▶️ Avvia allenamento»
del bot di Hṛdaya. Pagina statica (`index.html` + `engine.js`) su Cloudflare Pages (URL nel `.env`
del repo dati: `WORKOUT_PLAYER_URL`).

**Chi possiede cosa.** Il player (pagina, motore, voce, `deploy.sh`) è di `coach-longevita`. Il canale
è di `hridaya`: manda il bottone (tool `telegram_send_player`, o `scripts/workout_send.py` di questo
plugin come fallback), riceve il log (`web_app_data`) e lo salva (`hridaya/scripts/workout_player.py`).
Il contratto fra i due è il formato `player.json` / `session.json` descritto qui.
Il workout viaggia nel fragment (`#w=` base64url del JSON, `#z=` se compresso deflate-raw):
il fragment non arriva al server, quindi online non c'è nessun dato personale.

Flusso: il coach scrive `data/coach-longevita/daily/YYYY-MM-DD.player.json` → Hṛdaya manda il bottone
(`telegram_send_player`; fallback `python3.12 <coach>/scripts/workout_send.py <file>`; o `/allenamento`
dal menu del bot: riapre l'ultimo `player.json` con data ≤ oggi, i demo solo se non c'è altro) → seduta →
`sendData` → il bot salva `YYYY-MM-DD.session.json` e avvisa la sessione → debrief con
`python3.12 <coach>/scripts/workout_fitbit.py YYYY-MM-DD`.

## Schema `player.json`

```json
{"v": 1, "date": "2026-11-06", "title": "…", "blocks": [ … ]}
```

`demo: true` (opzionale): seduta di prova, il bot la salva come `YYYY-MM-DD.demo.session.json` e `workout_fitbit` la ignora (salvo `--demo`).

Ogni blocco: `type`, `name`, `exercises` (lista), e opzionali `prep_s`, `rest_after_s`, `optional`,
`section`, `equipment`, `area`, `go_s`.

**Sezioni e attrezzi.** `section` (testo: Riscaldamento, Forza, Misure, WOD, Defaticamento…) compare in alto
durante il blocco e, al cambio, la prep dice «INIZIA: WOD». Senza `section` il player la deduce (nome del blocco,
poi tipo: emom/interval/amrap/fortime → WOD, sets → Forza, timed primo/ultimo → Riscaldamento/Defaticamento).
`equipment` (lista di testi, carichi compresi) e `area` (dove nella palestra) compaiono nell'intro, sotto ogni
blocco, e nella prep manuale come lista «PREPARA»; senza `equipment` il player elenca gli esercizi con carico.
Prima di un blocco a cronometro (emom, interval, amrap, fortime) con prep manuale, dopo «▶ Pronto» parte
un countdown «SI PARTE» di `go_s` secondi (default 10, `0` = subito): il passo è una prep con etichetta `Via <blocco>`.
Esercizio: `name` (**nome inglese standard CrossFit**: Deadlift, Goblet Squat, Strict Press, Pull-up Negative,
Row, Bike, Plank, Cat-Cow, World's Greatest Stretch, Walk in Place…: così compare a schermo, nella Scheda,
nel «Prossimo» e nella voce «Next: Deadlift»; note e dettagli restano in italiano), `reps` (numero o testo: `"8 cal"`, `"3 per lato"`), `time_s`, `kg`, `note`,
`img` (slug del catalogo del coach, es. `deadlift`, `goblet-squat`, `push-up`: il player alterna
`img/<slug>-frame-1.svg` e `-frame-2.svg` ogni secondo; se lo slug manca o il file non c'è, niente riquadro).
Le SVG vengono dal bundle del plugin (`assets/img/`) più le SVG generiche scaricate dal coach in
`data/coach-longevita/daily/img/`: le copia `deploy.sh`.

| type | campi | come gira |
|---|---|---|
| `timed` | `duration_s` (se un solo esercizio) | un passo per esercizio: a countdown se ha `time_s`, altrimenti «Fatto» |
| `sets` | `rounds`, `rest_s` (a fine giro), `rest_between_s` (tra esercizi della superserie) | «Fatto» a fine serie → recupero a countdown. Rampa: `exercise.sets: [{reps, kg, rest_s, note}]` |
| `emom` | `minutes`, `interval_s` (60) | esercizi a rotazione minuto per minuto; «Fatto (segna)» registra quando hai finito il lavoro del minuto |
| `interval` | `work_s`, `rest_s`, `rounds` | ogni giro passa per tutte le stazioni (Tabata = 20/10 × 8) |
| `amrap` | `duration_s` | countdown, «+1 giro» a tap |
| `fortime` | `cap_s`, `rounds` | cronometro, «Fatto» o fine al cap |

`prep_s`: countdown «Preparati» prima del blocco. Default: 5 s per il primo blocco, attesa manuale
(«▶ Pronto») per gli altri — in palestra serve tempo per caricare il bilanciere. `0` = niente prep.
Nessun recupero dopo l'ultima serie di un blocco `sets`: se serve, `rest_after_s`.

### Debrief a fine seduta

`debrief` (opzionale): domande a bottoni mostrate a fine seduta (o dopo «■ Ferma»), un tocco ciascuna, più una nota
libera facoltativa (max 280 caratteri). Le risposte viaggiano nel log (`q`, `nt`) e il bot le salva in
`session.json` → `debrief: {answers, note}`.

```json
"debrief": [
  {"id": "rir",  "q": "Deadlift 100: quante ne avevi ancora?", "options": ["0", "1", "2", "3+"]},
  {"id": "back", "q": "La schiena?", "options": ["ferma", "si è mossa", "dolore"]},
  {"id": "wod",  "q": "Il WOD?", "options": ["love", "ok", "meh", "no"]},
  {"id": "energy", "q": "Energia adesso?", "options": ["bassa", "ok", "alta"]},
  {"id": "tomorrow", "q": "Domani?", "options": ["come da piano", "più facile", "off"]}
]
```

Le prime due cambiano ogni giorno (alzata principale della seduta; la schiena a parole, mai scala 0-10); le ultime tre
sono fisse. Senza `debrief` il player mostra le tre fisse (`wod` solo se c'è un blocco WOD). Tutto facoltativo: senza
risposte la seduta si invia lo stesso e il coach chiede dopo.

## Schermo

- Lavoro: esercizio, carico, illustrazione. In AMRAP/for time la lista degli esercizi (scorrevole) e le illustrazioni a rotazione.
- Recupero e prep: in evidenza **PROSSIMO** con nome, carico e illustrazione del prossimo passo di lavoro;
  all'inizio di un recupero ≥ 15 s la voce dice «Next: <nome>» (en-US). Altre voci: «Half way there», «10 seconds».
- «☰ Scheda» (in alto): tutta la seduta, con i passi fatti (✓, attenuati), saltati (⤼, barrati), il corrente evidenziato
  e il prossimo cerchiato. Il timer continua sotto; un tocco chiude.

## Log

Eventi `{t, e, s, auto?}`: `t` ms epoch, `e` ∈ start|step|pause|resume|skip|done|round|stop|end,
`s` indice del passo nella timeline. `auto` = transizione calcolata in ritardo (pagina sospesa a
schermo bloccato: il tempo è orologio reale, al ritorno le transizioni vengono registrate all'istante giusto).
Lo stato si ricostruisce rigiocando il log: salvato a ogni evento in localStorage e (compatto) in
`Telegram.WebApp.CloudStorage`. Riaprendo lo stesso workout dopo una chiusura il tempo ad app chiusa non conta:
«Riprendi» torna in pausa sul passo salvato (la ripresa porta `reopen`), «Invia quello che c'è» chiude
all'ultimo evento reale, «Ricomincia» chiede conferma e archivia la seduta vecchia (`wp_<id>_a<t0>`).
La seduta resta salvata anche dopo l'invio. Se è finita (stop o end) da meno di 6 ore, riaprendola compare
«▶ Continua da dove eri»: riparte in pausa (dalla serie interrotta, se lo stop è caduto su una serie non chiusa;
altrimenti dal passo dopo), con un evento `step` flag `cont`. All'invio parte solo la continuazione, con `cont` = t0
della seduta originale: il bot la unisce allo stesso `.session.json` (eventi in ordine, `segments` con gli invii).
Un reinvio dello stesso log (stesso t0) non crea doppioni.
Ogni tap porta il passo che l'utente vedeva: se nel frattempo il timer è scaduto, l'azione non fa nulla;
i tap nei 700 ms dopo un cambio di passo sono ignorati (doppio tap).

`sendData` (≤ 4096 byte), JSON compatto:
`{v, d, n, t0, st, demo?, B:[nomi blocchi], S:[[passo, blocco, p|w|r, etichetta]], E:[[sec da t0, codice evento, passo, flag?]]}`
(flag: 1 = auto, 2 = reopen, 4 = cont); `cont` = t0 della seduta originale se è una continuazione.
Se sfora, accorcia le etichette, poi le toglie, poi tiene gli eventi più recenti (`tr` = quanti tolti).
Seduta reale del 6/11: ~70 eventi ≈ 2,5 KB.

`sendData` funziona solo se la Mini App è aperta da un bottone di **reply keyboard** (non inline).

## Sviluppo

```sh
node --test coach-longevita/apps/workout-player/            # motore
python3.12 -m pytest coach-longevita/scripts/tests          # debrief Fitbit, fallback di invio
python3.12 -m pytest hridaya/scripts/tests/test_workout_player.py   # lato canale (decodifica, unione)
WELLNESS_DATA=<repo dati> coach-longevita/apps/workout-player/deploy.sh [--dry-run]
```

`deploy.sh` pubblica solo asset generici (pagina, motore, illustrazioni, voce) da una cartella
temporanea; progetto Pages da `WORKOUT_PLAYER_PAGES_PROJECT` nel `.env` del repo dati. Le clip vocali
nuove (`make_voice.py`, voce macOS Samantha) finiscono in `data/coach-longevita/player-voice/` del repo
dati, non nella cache del plugin.
