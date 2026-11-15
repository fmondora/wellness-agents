# L'arte della sauna

Quello che un maestro di sauna sa del mestiere. È cultura del rito, non medicina: i limiti di
salute non stanno qui, stanno nei tetti della persona (`data/sauna/rules.json`) e li dà il medico.

## La forma: il passaggio

Tutte le tradizioni del calore, dalla sauna finlandese alla *Saunagang* delle terme tedesche, dal
*banja* russo all'hammam, hanno la stessa struttura: **scaldare, raffreddare, riposare**, e ripetere.
Un giro completo si chiama passaggio. Due passaggi sono un rito pieno; tre sono il massimo che le
terme propongono; uno solo, fatto bene, è già un rito.

| Momento | Cosa succede | Durata d'uso nelle terme |
|---|---|---|
| **Soglia** | doccia calda con sapone, poi asciugarsi del tutto: la pelle asciutta suda prima e meglio. Via orologi, anelli, occhiali. Piedi caldi (se sono freddi, un pediluvio caldo). Né a stomaco pieno né a digiuno lungo | 5-10 minuti |
| **Calore** | sdraiati se la panca lo permette (il corpo sta tutto alla stessa temperatura), il telo sotto ogni parte che tocca il legno. Più in alto è più caldo: si sceglie la panca, non si subisce. Gli ultimi due minuti seduti, i piedi giù: ci si alza piano | 8-15 minuti; meno a temperature alte, di più nelle cabine dolci |
| **Aria** | prima di tutto aria fresca: uno o due minuti di passi lenti, respirando dal naso. Raffredda le vie del respiro prima della pelle | 1-3 minuti |
| **Acqua** | dai piedi verso il cuore: gamba destra da fuori a salire e da dentro a scendere, poi la sinistra, le braccia, in ultimo il busto. Doccia, getto, secchio, tinozza. Chi si immerge lo fa dopo essersi bagnato, mai di colpo dal caldo | da pochi secondi a un paio di minuti |
| **Riposo** | sdraiati, coperti, piedi al caldo. Dura almeno quanto il calore. È la parte del rito in cui il corpo fa il suo lavoro: chi la salta ha fatto metà sauna | 10-20 minuti |
| **Chiusura** | dopo l'ultimo riposo: bere con calma (acqua, tisana), un velo d'olio o di crema, vestirsi caldi. Niente sapone: la pelle è già pulita | 5-10 minuti |

Regole del mestiere che valgono ovunque:
- **Si esce quando lo dice il corpo, non l'orologio.** L'orologio dice il massimo, mai il minimo.
- **Il secondo passaggio è più quieto del primo**, non più lungo.
- **Non si parla nel calore**; si parla, se si vuole, nel riposo.
- **Il freddo è una scelta.** Molti maestri fanno solo aria e doccia tiepida a chi non ama l'acqua
  fredda: il rito resta intero.
- **Bere**: la tradizione vuole che si beva alla fine; oggi si lascia bere quando c'è sete, nel
  riposo. Mai alcol prima o durante.
- **La sera**: un rito serale finisce almeno un'ora e mezza prima di dormire, e si chiude col
  riposo più lungo.

## Le cabine

| Cabina | Aria | Carattere |
|---|---|---|
| Finlandese | 80-100 °C, secca (10-20%) | il calore pieno; passaggi brevi; la gettata di vapore lo rende vivo |
| Bio / soft (Sanarium) | 50-65 °C, umida (40-55%) | dolce, si sta più a lungo, si respira bene |
| Infrarossi | 40-60 °C | scalda il corpo più dell'aria; niente pietre, niente vapore |
| Bagno di vapore | 42-48 °C, satura | il calore umido; pelle e respiro |
| Banja | 60-80 °C, molto umida | vapore a ondate, frasche di betulla (*venik*) |

La partitura si scrive sulla cabina che c'è (`setup.json`): in una cabina dolce il traguardo può
essere più lungo che in una finlandese, **sempre dentro i tetti**.

## La gettata di vapore (*löyly*, *Aufguss*)

Dove ci sono pietre calde, un mestolo d'acqua fa salire per qualche secondo un'onda di vapore: il
calore percepito cresce senza che cambi la temperatura. È il gesto più antico della sauna
finlandese (*löyly* è il vapore, e anche lo spirito della sauna).

- **La gettata semplice**: uno o due mestoli, a metà del passaggio o negli ultimi minuti. Dopo la
  gettata si resta fermi: l'onda passa in mezzo minuto.
- **La cerimonia** (*Aufguss* delle terme): tre gettate a distanza di un paio di minuti, e fra
  l'una e l'altra il maestro muove l'aria con un telo. Dura 8-12 minuti e occupa tutto il passaggio.
  A casa, da soli, basta la forma: tre mestoli, tre pause.
- **Varianti di stagione**, da proporre una per volta e solo se `setup.json` le ammette:
  - *essenze* nell'acqua della gettata (betulla, pino mugo, agrumi, lavanda) — mai sulle pietre
    pure, mai con asma o naso sensibile senza che la persona dica che le tollera già;
  - *ghiaccio* sulle pietre al posto dell'acqua: un vapore più lento (solo se il costruttore della
    stufa lo ammette: su certe pietre e resistenze fa danni);
  - *sale* o *miele* sulla pelle prima dell'ultimo passaggio (pelle integra);
  - *frasche* di betulla, messe a bagno prima;
  - *suono*: una ciotola che canta durante la gettata, in silenzio.

Nella partitura la gettata è un richiamo dentro il calore: `{"at_s": 300, "sound": "vapore",
"text": "Un mestolo d'acqua sulle pietre."}`. Il suono `vapore` è lo sfrigolio: dice «adesso»
anche a chi non guarda il telefono.

## Riti di casa: tre forme da cui partire

- **Rito breve** (30-35 minuti): soglia · un calore · aria · acqua facoltativa · riposo lungo ·
  chiusura. Per le sere strette, per i giorni stanchi, per ricominciare dopo una pausa.
- **Rito pieno** (55-65 minuti): soglia · calore · aria · acqua · riposo · secondo calore (più
  quieto, con la gettata se c'è) · aria · riposo lungo · chiusura.
- **Rito quieto** (40-45 minuti): un solo calore dolce, niente acqua fredda, un'aria lunga, e un
  riposo che dura il doppio del calore. Per le sere in cui la testa è accesa.

Sono forme, non ricette: tempi e passaggi vanno sempre riscritti dentro i tetti della persona.

## Errori del mestiere

- Entrare bagnati o con i piedi freddi: si suda male e ci si stanca prima.
- Stare seduti in alto con i piedi in basso per tutto il tempo: testa calda, piedi freddi.
- Alzarsi di scatto alla fine: gli ultimi due minuti seduti esistono per questo.
- Saltare l'aria e buttarsi nell'acqua col fiato corto.
- Accorciare il riposo «perché tanto ho finito».
- Aggiungere un passaggio perché «oggi sto bene».
- Contare i minuti come un risultato.
