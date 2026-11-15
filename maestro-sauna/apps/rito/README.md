# Rito (Telegram Mini App)

L'esecutore dei riti del Maestro di sauna: una pagina a tutto schermo che tiene l'ordine e il tempo
del rito e lo suona. Si apre dal bottone «♨️ Apri il rito» del bot di Hṛdaya. Pagina statica
(`index.html` + `engine.js` + `sound.js`) su Cloudflare Pages (URL nel `.env` del repo dati:
`RITO_PLAYER_URL`).

**Chi possiede cosa.** La pagina, il motore e i suoni sono di `maestro-sauna`. Il canale è di
`hridaya`: manda il bottone, riceve il ritorno (`web_app_data`) e lo salva. Il contratto fra i due
sono i due file descritti qui: la partitura (`rito.json`) all'andata, la seduta (`session.json`) al
ritorno. La partitura viaggia nel fragment dell'URL (`#r=` base64url del JSON, `#z=` se compresso
deflate-raw): il fragment non arriva al server, quindi online non c'è nessun dato personale.

Flusso: il Maestro scrive `data/sauna/riti/YYYY-MM-DD.rito.json` → `rito_guard.py` (la soglia: forma,
tetti, giorno) → Hṛdaya manda il bottone → rito → `sendData` → il bot salva
`data/sauna/sessions/YYYY-MM-DD.session.json` e avvisa la sessione → debrief del Maestro.

Non è il workout player e non lo imita: lì lo schermo guida uno sforzo, qui il telefono resta fuori
dalla cabina e il rito parla col suono.

## Schema `rito.json`

```json
{"v": 1, "kind": "sauna", "date": "2026-11-19", "title": "Rito della sera", "subtitle": "…",
 "threshold": [{"id": "uscita-lunga", "ok": true, "note": "ieri solo cammino"}],
 "moments": [ … ],
 "closing": [{"id": "corpo", "q": "Il corpo adesso?", "options": ["🪶 Leggero", "🌊 Sciolto", "🪨 Pesante"]}],
 "voice": true, "clock": "words"}
```

`demo: true`: prova a secco, senza sauna (il canale lo salva come `.demo.session.json`, non entra nel
diario e non conta come seduta; solo un demo accetta `?speed=` e si può riaprire in un altro giorno). `clock: "none"` toglie anche le parole del tempo; `voice: false` non dice le frasi `say`.
`threshold` è la soglia dichiarata dal Maestro (la legge `rito_guard.py`, la pagina la ignora).
`prepare`: da 1 a 12 cose da preparare prima di cominciare (teli, acqua, tinozza, mestolo, olio). La
soglia della pagina le mostra in testa, sopra «Come andrà» (ogni momento con dove, gradi, durata,
massimo, acqua, vapore); acqua e acqua fredda si aggiungono da sole se il rito le usa.

Ogni **momento**:

| campo | |
|---|---|
| `id` | slug unico (a-z, 0-9, -) |
| `name` | come compare a schermo («Primo calore») |
| `type` | `prep` soglia · `heat` calore · `air` aria · `cold` acqua · `rest` riposo · `close` chiusura. Decide colore, tappeto e colpo predefiniti, e la parola del bottone |
| `end` | `tap` (predefinito): finisce col tocco · `time`: finisce da solo a `target_s`. **Caldo e freddo solo `tap`**: non finiscono mai da soli |
| `target_s` | il traguardo: a quel punto suona la ciotola e le parole dicono «è tempo» (nei momenti a tempo, lì si passa oltre) |
| `max_s` | il limite: oltre, gong doppio a volume pieno ogni 30 s e lo sfondo pulsa finché non si esce. **Obbligatorio** per `heat` e `cold`. Per il calore è il tempo massimo in cabina, contato dal tocco «Entro» |
| `min_s` | sotto il minimo un tocco solo non basta: «Resta ancora, se puoi», e un secondo tocco entro 6 s. Non vale per `heat` e `cold`: dal caldo e dal freddo si esce subito |
| `lead_s` | **il passaggio**: i secondi per arrivare al momento prima che il suo tempo cominci (raggiungere l'acqua, asciugarsi e stendersi). Predefiniti: aria 15, acqua 30, riposo 60, soglia e chiusura 0; il primo momento sempre 0. Massimo 300 (acqua 120). **Nel calore il tempo conta dal tocco**: lì `lead_s` (predefinito 30, massimo 60) è solo il tempo per stendersi, dopo il quale suona il gong d'inizio |
| `lead_text` | cosa fare nel passaggio («Asciugati, copriti, stenditi») |
| `optional` | si può saltare («Oggi lo salto»). Solo per ciò che il corpo può non volere, come l'acqua fredda; **mai per il riposo** |
| `text` | due righe: un gesto e una sensazione |
| `where`, `temp_c` | sotto il nome: «cabina, 65 gradi». `temp_c` solo sul calore (la soglia lo confronta col tetto) |
| `sound` | tappeto: `silenzio` `brace` (solo calore) `bordone` `acqua` `aria` `respiro` |
| `breath` | `{in_s, out_s}` (da 2 a 15 secondi) per il tappeto `respiro` e l'alone a schermo |
| `enter_sound` | colpo d'inizio: `tingsha` `ciotola` `campanella` `legno` `vapore` `goccia`, o `false`. Il `gong` è del richiamo oltre il limite: non usarlo per aprire un momento |
| `cues` | richiami dentro il momento: `[{at_s, sound?, say?, text?}]` (almeno uno dei tre) |
| `checklist` | da 1 a 8 voci brevi da spuntare (prima e dopo: cosa preparare, cosa fare). La pagina le mostra al posto della clessidra; se ne manca qualcuna, «Avanti» chiede un secondo tocco, non blocca. Non nel caldo né nel freddo |
| `drink` | `true`: un minuto dopo l'inizio del momento (a metà, se è più corto) suona la goccia e lo schermo dice «Un sorso d'acqua». Nei riposi, nell'aria, prima e dopo; mai nel caldo né nel freddo |
| `done_label` | la parola del bottone, se quella predefinita non va («Entro in cabina») |

Esempio completo: `fixtures/demo.rito.json`.

## Come scorre

- **Passaggio.** Finito un momento comincia il passaggio verso il successivo: il tappeto cambia, la
  clessidra è piena e ferma, lo schermo dice dove andare. Il tempo parte da solo alla fine del
  passaggio, col colpo d'inizio; un tocco su «Ci sono» lo fa partire prima. Il calore no: chi ha
  toccato «Entro» è già dentro, quindi la sabbia scende subito e il tingsha d'inizio suona dopo mezzo minuto.
- **Sicurezza.** Caldo e freddo finiscono solo con un tocco, hanno sempre un massimo, non si mettono
  in pausa; uscirne nei primi 20 secondi chiede un secondo tocco (dita bagnate). Se la pagina torna
  dopo essere stata chiusa durante un calore, il tempo è continuato e il richiamo suona subito. Un
  rito vale per il suo giorno: la pagina non apre la partitura di un altro giorno né un rito già
  chiuso. Se il suono si ferma (una chiamata, un'altra app) compare «Il suono si è fermato».
  **La pagina accompagna, non sorveglia**: funziona solo se resta aperta, accesa e non in
  silenzioso; in cabina resta la clessidra.
- **Il tempo è orologio reale.** Ogni momento ha un istante d'inizio; se la pagina viene sospesa, al
  ritorno i passaggi a tempo sono registrati all'istante giusto e i suoni ormai vecchi non suonano
  (il richiamo oltre il massimo sì).
- **Tocco per sbaglio.** Per 15 secondi dopo un tocco c'è «Ho toccato per sbaglio»: si torna al
  momento di prima senza perdere il suo tempo. Vale anche dall'ultimo tocco del rito.
- **Altro.** «Mi fermo un momento» (pausa: il tempo del momento si ferma), volume, «Interrompo il rito».
- **Ripresa.** Lo stato è il log degli eventi, salvato sul telefono a ogni evento. Riaprendo lo
  stesso rito: «Riprendo il rito». Se la pagina è rimasta chiusa più di 20 minuti, il rito risulta
  in pausa da quando era stata vista.
- **Chiusura.** Com'è andata in una frase, le domande del Maestro, una nota facoltativa, «Chiudo il
  rito» → `sendData`.

## Ritorno

`sendData` (≤ 4096 byte), JSON compatto:
`{v, k:"rito", d, n, t0, st, demo?, M:[[id, type, target_s, max_s, lead_s]], E:[[sec da t0, codice, momento, flag?]], A:[[secondi veri, come è finito]], q:{id: risposta}, nt}`
con i codici di `EVENTS` = `start enter tap auto skip pause resume undo stop end begin` (`begin` =
«Ci sono») e flag 1 = passaggio a tempo registrato in ritardo, 2 = pausa da riapertura.
`st` = `end` (rito compiuto) o `stop` (interrotto). `A` è il riassunto per momento (−1 = mai
cominciato): se il log sfora e gli eventi vengono tagliati (`tr`), i tempi veri restano lì.

`sendData` funziona solo se la Mini App è aperta da un bottone di **reply keyboard** (non inline).

## Sviluppo

```sh
node --test maestro-sauna/apps/rito/                       # motore
python3.12 -m pytest maestro-sauna/scripts/tests           # la soglia (forma, tetti, giorno)
cd maestro-sauna/apps/rito && python3.12 -m http.server 8797
#   http://127.0.0.1:8797/index.html?demo            il rito di esempio, a tempo vero
#   http://127.0.0.1:8797/index.html?demo&speed=30   lo stesso, trenta volte più veloce (i suoni restano veri)
maestro-sauna/apps/rito/deploy.sh [--dry-run]
```

`engine.js` e `rito_guard.py` hanno le stesse regole di forma: una partitura che passa la soglia si
apre sul telefono. Chi ne cambia una cambia l'altra: i due test leggono gli stessi casi, validi e
no, da `fixtures/cases.json`.

`telegram-web-app.js` si carica dal sito di Telegram senza `integrity`: è il loader ufficiale, non
ha versione e viene aggiornato sul posto, quindi un hash fisso lo romperebbe a ogni aggiornamento
(come nel workout player).

## Design

Materiali di una sauna, non di un cronometro: pietra scura, legno chiaro, lino. Ogni tipo di momento
tinge tutto lo sfondo dal basso, come un chiarore — brace per il calore, acqua profonda per il
freddo, foglia per il riposo. Un solo oggetto al centro: la **clessidra**, quella che sta appesa in
ogni cabina; la sabbia prende il colore del momento. Il tempo si dice a parole («ancora quattro
minuti», «è tempo»), mai a cifre che corrono. Un carattere solo, Optima. Un bottone solo, grande,
per mani bagnate. Si legge a due metri: il nome del momento e quanta sabbia resta.

Token CSS in testa a `index.html` (`--basalto`, `--lino`, `--sabbia`, `--legno`, e per momento
`--bg-a`, `--bg-b`, `--grain`).
