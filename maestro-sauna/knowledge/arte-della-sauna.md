# L'arte della sauna — due scuole

Il Maestro viene da due scuole e le tiene distinte: il **Saunameister alpino** delle terme
tedesche, austriache e altoatesine (la *Saunagang* ordinata, la cerimonia dell'*Aufguss*, l'acqua
di Kneipp) e la **sauna finlandese** (il *löyly*, il calore senza orologio, la quiete). Dalla prima
prende la forma e il rigore, dalla seconda l'ascolto. È cultura del rito, non medicina: i limiti di
salute stanno nei tetti della persona (`data/sauna/rules.json`) e li dà il medico.

Le fonti sono in fondo. Dove una regola è d'uso e non scritta da nessuno, è detto.

---

## La scuola alpina: la *Saunagang*

È la forma che si impara nelle terme di lingua tedesca: **scaldare, raffreddare, riposare**, e
ripetere. Le regole del Deutscher Sauna-Bund (riportate da più guide delle terme):

| Momento | Come lo fa un Saunameister | Durata |
|---|---|---|
| **Prima** | doccia calda, poi **asciugarsi del tutto**: la pelle asciutta suda prima. Se i piedi sono freddi, un **pediluvio caldo** prima di entrare. Né a stomaco pieno né a digiuno lungo | 5-10′ |
| **Calore** | sdraiati sul telo, così il corpo sta tutto alla stessa temperatura; gli ultimi due minuti seduti coi piedi giù, poi ci si alza piano | **8-15′** nella cabina finlandese a 80-100 °C; nelle cabine più dolci si sta di più |
| **Aria** | **prima l'aria, poi l'acqua**: si esce piano, all'aperto, e per mezzo minuto o due si respira dal naso camminando. Raffredda le vie del respiro prima della pelle | ½-3′ |
| **Acqua** | prima si sciacqua il sudore, poi il freddo **dal lontano al cuore** (Kneipp, sotto). Dal più dolce al più forte: il getto di Kneipp, la doccia, la tinozza | da pochi secondi a un paio di minuti |
| **Pediluvio caldo** | dopo il freddo, i piedi nell'acqua calda: il calore risale fino alla testa e si smette di sudare dopo | 3-5′ |
| **Riposo** | sdraiati, coperti. È qui che il corpo fa il suo lavoro | **20-30′** fra un passaggio e l'altro |

- **Tre passaggi al massimo**: il Sauna-Bund dice che un quarto non aggiunge niente. Due sono un
  rito pieno, uno fatto bene è già un rito.
- **Una o due volte a settimana.**
- **Mezzo litro d'acqua a seduta**, bevuto nei riposi e alla fine; mai alcol.
- Il secondo passaggio non è più lungo del primo: è più quieto, o è quello della cerimonia.

### L'acqua di Kneipp

Sebastian Kneipp (Bad Wörishofen, Ottocento) ha dato alle terme il modo di bagnarsi col freddo.
Il getto è morbido, senza pressione, quasi una lama d'acqua che avvolge la pelle; **si comincia
lontano dal cuore e si sale**.

1. **Ginocchio** (*Knieguss*): gamba destra, il getto sale dal dorso del piede per la caviglia e
   il polpaccio fino a un palmo sopra il ginocchio, dietro; si scende dall'interno. Poi la sinistra.
2. **Coscia** (*Schenkelguss*): lo stesso, fino all'inguine. È il passo successivo, non il primo.
3. **Braccio**: dalla mano destra verso la spalla, dall'esterno; si scende dall'interno. Poi la
   sinistra.
4. **Busto**, solo alla fine e solo se si vuole. Il viso si bagna per ultimo, con le mani.

Chi ha la tinozza la usa dopo il getto, mai di colpo dal caldo. Nella partitura questa sequenza è
la `checklist` del momento dell'acqua.

### L'*Aufguss*: la cerimonia del vapore

Nelle terme un Saunameister versa sulle pietre acqua (spesso profumata) e col telo distribuisce
l'onda di calore: il calore percepito cresce senza che cambi la temperatura dell'aria. Una
cerimonia dura **8-12 minuti** ed è divisa classicamente in **tre gettate**, ognuna seguita dal
movimento del telo:

1. **Si arieggia** (*Lüften*): porta aperta, il telo che gira come un'**elica** fa entrare aria
   fresca; poi la porta si chiude e la cabina torna calda.
2. **Prima gettata**: due o tre mestoli, piano. Poi il telo spinge l'onda verso le panche, a
   **ventaglio** (movimenti ampi e lenti, dall'alto verso il basso).
3. **Seconda gettata**, un paio di minuti dopo: più acqua, l'onda più forte.
4. **Terza gettata**: la più intensa, poi il saluto. Chi è in cabina non si alza durante la
   cerimonia.

Il movimento del telo è un mestiere: le scuole insegnano alcuni movimenti di base e poi le figure.
Le gare di *Aufguss* sono diventate spettacolo, con musica e costumi; la cerimonia da terme resta
quella delle tre gettate.

**A casa, da soli**, la cerimonia si riduce al suo scheletro: si arieggia una volta col telo
prima di entrare, porta chiusa, poi tre gettate a tre minuti l'una dall'altra; dopo ogni gettata
si resta fermi e si lascia passare l'onda. **Il telo non si agita sopra di sé**: a nessuno serve
spingersi il caldo in faccia.

Nella partitura le gettate sono richiami dentro il calore, col suono `vapore`:
`{"at_s": 180, "sound": "vapore", "text": "Prima gettata: due mestoli, piano."}`.

---

## La scuola finlandese: il *löyly*

In Finlandia la sauna ha più di mille anni ed era il posto più pulito della casa: ci si lavava, ci
si curava, ci si nasceva. La Suomen Saunaseura (Società finlandese della sauna) la spiega così:
una stanza calda; ci si siede, si versa col mestolo acqua sulle pietre, e l'acqua diventa vapore,
il **löyly**. La parola dice il vapore e anche lo spirito della sauna.

- **Il löyly si chiede.** Si versa solo se tutti lo vogliono, e chi versa resta: alzarsi subito
  dopo una gettata è scortese. La porta resta chiusa.
- **Niente orologio.** Si sta finché si sta bene; l'orologio serve solo a dire il massimo (nella
  partitura c'è sempre).
- **Rinfrescarsi come capita**: una doccia, seduti fuori, il lago, la neve. Dice la Saunaseura:
  tutto ciò che raffredda il corpo va bene. Poi si torna dentro, due o tre volte.
- **Bere molta acqua.**
- **Quiete.** «In sauna ci si comporta come in chiesa», dice un proverbio finlandese: non si
  litiga, non si alza la voce.
- **La *vihta*** (o *vasta*), il mazzo di rami di betulla bagnato prima: si usa solo quando la
  pelle è già calda, con colpi leggeri su schiena e gambe; muove il sangue e libera il profumo
  della betulla. **Chi è allergico alla betulla non lo usa** (lo scrive la Saunaseura); con asma e
  naso sensibile vale `setup.json`: se non è ammessa, non si propone.

La sera finlandese è il contrario della cerimonia: un calore lungo e lento, piccoli mestoli quando
il corpo li chiede, fuori seduti a guardare il buio, e ancora dentro.

---

## Come il Maestro le fonde

Le due scuole non si mescolano a caso: **la forma è alpina, il tono è finlandese.**

- **L'ordine non si salta** (alpino): prima, calore, aria, acqua, riposo. Il riposo dura almeno
  quanto il calore, e fra due passaggi cerca i 20 minuti.
- **Il primo calore è finlandese**: lento, silenzioso, piccoli mestoli se li vuole, nessun richiamo
  tranne quelli di sicurezza. Serve a entrare nel caldo.
- **La cerimonia sta nel secondo passaggio** (alpino): le tre gettate, quando il corpo è già caldo
  e la testa già quieta.
- **L'acqua è di Kneipp** quando c'è un getto o una doccia; la tinozza dopo il getto.
- **Si esce quando lo dice il corpo** (finlandese). L'orologio dice il massimo, mai il minimo.
- **Le durate della scuola** (8-15′ di calore a 80-100 °C, più a lungo nelle cabine tiepide) sono
  la misura di partenza; i tetti della persona vengono prima. Se un tetto taglia la forma della
  scuola, il Maestro lo dice in una riga, con quale tetto e da dove viene: non lo allarga, ma non
  lo nasconde.

## Le cabine

| Cabina | Aria | Carattere |
|---|---|---|
| Finlandese | 80-100 °C, secca (10-20%) | il calore pieno; passaggi brevi; il löyly la rende viva |
| Finlandese tiepida | 60-75 °C | si sta più a lungo che a 90 °C; il löyly conta di più |
| Bio / soft (*Sanarium*) | 50-65 °C, umida (40-55%) | dolce, si respira bene |
| Infrarossi | 40-60 °C | scalda il corpo più dell'aria; niente pietre, niente vapore |
| Bagno di vapore | 42-48 °C, satura | il calore umido |
| *Banja* | 60-80 °C, molto umida | vapore a ondate, il *venik* di betulla o quercia |

## Riti di casa

Sono forme, non ricette: tempi e passaggi vanno sempre riscritti dentro i tetti della persona.

- **Rito alpino pieno** (circa 75-90′): prima (doccia, asciugarsi, pediluvio caldo se serve) ·
  calore lento · aria · Kneipp · pediluvio caldo e riposo · **secondo calore con l'Aufguss in tre
  gettate** · aria · acqua · riposo lungo · dopo.
- **Sera finlandese** (circa 60′): prima · calore lungo e lento coi mestoli che chiede · fuori,
  seduti · acqua da bere · ancora calore · fuori · riposo · dopo. Pochi richiami, molto silenzio.
- **Rito breve** (35-45′): prima · un calore · aria · acqua facoltativa · riposo lungo · dopo. Per
  le sere strette, i giorni stanchi, il ritorno dopo una pausa.
- **Rito quieto** (40-50′): un calore dolce senza gettate, niente freddo, un'aria lunga e un
  riposo doppio del calore. Per le sere con la testa accesa.

## Errori del mestiere

- Entrare bagnati o coi piedi freddi.
- Stare seduti in alto coi piedi in basso tutto il tempo: testa calda, piedi freddi.
- Alzarsi di scatto alla fine: gli ultimi due minuti seduti esistono per questo.
- Saltare l'aria e buttarsi nel freddo col fiato corto.
- Il freddo di colpo sul petto invece che dai piedi.
- Accorciare il riposo «perché tanto ho finito».
- Aggiungere un passaggio perché «oggi sto bene».
- Versare il löyly e uscire.
- Contare i minuti come un risultato.

---

## Fonti

- Deutscher Sauna-Bund, regole del bagno di sauna, riportate da guide di terme e riviste:
  [Goldene Regeln (Mengen)](https://www.Mengen.de/sw-wAssets/docs/sauna/2022_Goldene-Regeln.pdf),
  [prisma.de](https://www.prisma.de/magazin/themen/Leitfaden-fuer-die-Sauna-Richtig-schwitzen-einfach-gesund,11753757),
  [aponeo](https://www.aponeo.de/ratgeber/sauna-schwitzen-fuer-die-gesundheit.html),
  [Otto, Wärme-Ratgeber](https://d.otto.de/files/001_2018_41_waerme_ratgeber_richtig_saunieren.pdf),
  [Limes-Therme](https://www.limes-therme.de/fileadmin/user_upload/Sonstige/Downloads/LT_Stilvoll-schwitzen.pdf).
  Il testo originale delle regole non è stato consultato direttamente: le durate (8-15′, riposo
  20-30′, tre passaggi al massimo, mezzo minuto d'aria) sono quelle su cui le guide concordano.
- Kneipp, i getti: [Altmeyers Enzyklopädie, Güsse](https://www.altmeyers.org/de/dermatologie/gusse-kneipp-156363);
  pediluvio dopo la sauna: [Klafs](https://klafs.com/residential/health/abc-of-well-being/foot-bath).
- Aufguss: [wissen.de](https://www.wissen.de/wellness-die-kunst-des-saunierens),
  [Kothmühle, Aufguss fai-da-te](https://kothmuehle.at/de/hotel-blog/posts/20241015_diy_saunaaufguss-wp811-302.html),
  [Baur](https://www.baur.de/magazin/sauna-aufguss),
  [Aufguss Roots, corsi](https://cdn.shopify.com/s/files/1/0661/9866/7481/files/Flyer-Aufguss-Roots-23-web.pdf).
  Le tre gettate e gli 8-12′ sono d'uso nelle terme; i nomi dei movimenti del telo cambiano da
  scuola a scuola.
- Suomen Saunaseura: [guida illustrata al bagno di sauna](https://sauna.fi/en/sauna-knowledge/guidelines-for-bathing-in-the-sauna/),
  [sauna e salute](https://sauna.fi/en/sauna-knowledge/sauna-and-health-effects/) (betulla e
  allergia; il tuffo freddo alza la pressione di colpo),
  [linee guida per le vihta](https://sauna.fi/en/sauna-knowledge/quality-guidelines-for-sauna-whisks/);
  [finland.fi](https://finland.fi/life-society/bare-facts-of-the-sauna/).
