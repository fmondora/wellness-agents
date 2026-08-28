# Libreria Esercizi — riferimenti visivi

Due fonti complementari:

1. **Sala / corpo libero** — [bryllim/workout-guide](https://github.com/bryllim/workout-guide)
   (302 esercizi illustrati; codice MIT, illustrazioni CC BY-SA 4.0 di Bryl Lim / Everkinetic).
   Catalogo locale: `exercise-catalog.json` (slug, nome, attrezzo, muscoli, tipo).
2. **Movimenti CrossFit** — video ufficiali di tecnica su crossfit.com/essentials.
   Lista locale: `crossfit-movements.md` (119 movimenti: oly lifts, ginnastica,
   kipping, handstand walk, toes-to-bar, double-under...).

Ordine di ricerca del link: se è un movimento CrossFit → `crossfit-movements.md`;
altrimenti → `exercise-catalog.json`. Se non è in nessuno dei due, niente link.

## Come usarla nei piani

Ogni esercizio proposto all'utente porta un link 📖 alla pagina illustrata:

- Pagina esercizio: `https://bryllim.github.io/workout-guide/exercises/<slug>/`
- Solo illustrazione SVG: `https://raw.githubusercontent.com/bryllim/workout-guide/main/packages/workout-guide/assets/<slug>/frame-1.svg`

Regole:
1. **Il catalogo NON è il menu.** La programmazione nasce da pattern + luogo +
   storia + preferenze (P1-P3), MAI dalla disponibilità di un'illustrazione.
   Il coach usa liberamente tutto il vocabolario funzionale/CrossFit del box —
   clean, thruster, toes-to-bar, box jump, double-under, sled, turkish get-up,
   muscle-up... — anche se qui non hanno una figura.
2. Lo slug si prende dal catalogo locale (`exercise-catalog.json`), cercando
   per nome o per muscolo. MAI inventare slug (spirito di A2): se l'esercizio
   non è nel catalogo, niente link — o linka la variante più vicina dicendolo.
3. Il link è un riferimento di forma, non una prescrizione: la tecnica la
   detta il coach nel testo (tempo, RIR, stop_if).
4. Su Telegram i link passano come URL semplici in coda alla riga.

## Copertura

Il catalogo illustrato NON ha i movimenti CrossFit (alzate olimpiche, thruster,
toes-to-bar, box jump, double-under, muscle-up, GHD, sled, turkish get-up,
wall ball) — per quelli si usa `crossfit-movements.md` (video ufficiali).
Nota: wall ball e burpee per Francesco sono comunque "no" (asma) —
il resto è vocabolario legittimo al box, dosato dal semaforo e dalla storia.

## Riferimenti per lo skill HSW di Francesco (video ufficiali)

- [The Handstand Walk](https://www.crossfit.com/essentials/the-handstand-walk) — l'arrivo
- [The Handstand](https://www.crossfit.com/essentials/freestanding-handstand)
- [Wall walk](https://bryllim.github.io/workout-guide/exercises/wall-walk/) (illustrato)
- [The Chest-to-Wall Handstand Push-Up](https://www.crossfit.com/essentials/the-chest-to-wall-handstand-push-up) — solo la posizione, non il push-up

## Mapping rapido per gli esercizi ricorrenti di Francesco

| Nome nel piano | Slug catalogo |
|---|---|
| Back squat | `squat` |
| Goblet squat | `goblet-squat` |
| Box/single-leg squat | `single-leg-box-squat` |
| Panca piana | `bench-press` |
| Panca manubri (swap spalla) | `dumbbell-bench-press` |
| Stacco / RDL | `deadlift` / `romanian-deadlift` |
| Kettlebell swing | `kettlebell-swing` |
| Rematore manubrio | `one-arm-dumbbell-row` |
| Ring/inverted row | `inverted-row` |
| Farmer carry | `farmer-carry` |
| Rower (engine) | `rowing` |
| Plank | `plank` |
| Band pull-apart | `band-pull-apart` |
| Scap push-up | `scapular-push-up` |
| Air squat | `bodyweight-squat` |

## Progressione HSW (skill in wishlist) — drill presenti nel catalogo

`plank` → `scapular-push-up` → `pike-push-up` → `wall-walk` →
`wall-handstand-push-up` (solo hold, non il push-up) → camminata.
Il wall plank / wall-facing hold non ha slug proprio: usare `wall-walk`
come riferimento visivo della posizione d'arrivo.
