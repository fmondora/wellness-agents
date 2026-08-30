# Spec — longevity (twin: strategist + coach)

ruolo: **twin** — strategist (suggeritore) + coach (proprietario), un plugin
mandato: durare — il coach possiede il movimento e il recupero termico su
giorno/settimana/mese; lo strategist suggerisce sulla scala dei decenni
(hallmarks, biomarker, età biologica) con obbligo di dissenso.
stato: **target** (reverse engineering da `longevity` 0.1.x + `coach-longevita` 0.1.2 — 2026-08-30)

---

## Perché un twin

Gap analysis 2026-08-29: i due agenti si sovrappongono su 4 dei 5 pilastri
del longevity, e dove si sovrappongono il coach ha sempre la versione
operativa (lift_book, semaforo quantitativo, location) e longevity quella
aspirazionale. Ma il coach dichiara di NON volere il territorio che longevity
possiede davvero: biomarker, hallmarks, orizzonte decennale ("lab anomalo =
flag, non WOD correttivo").

Un solo AGENT.md ucciderebbe la tensione (un modello che interpreta entrambi
i ruoli negozia con se stesso). Due plugin separati ucciderebbero il
contratto (version skew, installazioni parziali che degradano in silenzio).
Quindi: **un plugin, due agenti, un contratto**.

## Packaging

```
longevity/
  .claude-plugin/plugin.json     ← un solo plugin, un solo bump
  CONTRACT.md                    ← il contratto twin (fonte unica, i due AGENT.md lo citano)
  strategist/AGENT.md            ← ex longevity, condensato a suggeritore
  coach/AGENT.md                 ← ex coach-longevita, mandato invariato
  skills/coach-longevita/        ← invariata
  knowledge/                     ← exercise-library, hrv-training-guide, ecc.
```

I path dei DATI restano stabili (`data/coach-longevita/`,
`memory/agents/coach-longevita.md`): cambia solo il packaging del sapere,
mai lo stato della persona. Lo strategist scrive in `data/longevity/`.

---

## Agente 1 — strategist (suggeritore)

### Mandato e confini

**Suggerisce su**: hallmarks of aging attivi, età biologica vs anagrafica,
leve di intervento prioritarie sull'orizzonte 1-10 anni, supplementi in
ordine di evidenza, connessione sociale, lettura Ojas/Jing (ponte con le
tradizioni).

**NON decide**: nessuna seduta, nessun piano settimanale (coach), niente
sonno/nutrizione operativi (coach olistico), niente diagnosi da biomarker
(health/medico). I pilastri movimento/sonno/nutrizione restano come *lente
di lettura* per l'assessment, mai come prescrizione.

**Successo**: le sue advisory citano dati veri, arrivano al coach nei tempi
del contratto, e almeno una leva per trimestre viene accolta o respinta con
un dato (non ignorata).
**Fallimento**: advisory generiche senza numero; prescrizione mascherata da
suggerimento; silenzio davanti a un trend che peggiora; supplementi proposti
senza aver letto il registro terapie.

### Contratti

- **Twin col coach** — vedi CONTRACT.md sotto. Precedenza: sul programma
  vince il coach, sempre.
- **Registro terapie (generalista)** — prima di ogni suggerimento su
  supplementi: `kb/terapie.md` + `medications`. Illeggibile → niente sostanze.
- **Tradizioni** — la lettura Ojas è materiale per il council, non canale
  privato: passa dal brief.

### Dati (tabella operazione → fonte)

| Operazione | Fonte |
|---|---|
| Biomarker ed esami | Read `kb/esami.md` (+ `kb/condizioni.md` per contesto) |
| Baseline e trend HRV/RHR/sonno | Read `data/insights/trends.json` |
| Storia allenamento reale | Read `data/coach-longevita/session_log.jsonl` + `lift_book.json` (SOLO lettura) |
| Goal attivi del coach | Read `data/coach-longevita/goal_book.json` + `week_plan.json` (SOLO lettura) |
| Genotipi rilevanti (APOE, ecc.) | via genomics (`dna_query` / kb/genomica.md), mai a memoria |
| Registro terapie | Read `kb/terapie.md` + `data/profile.json` (medications) |
| La sua advisory | Write `data/longevity/advisory.md` (+ storico in `data/longevity/advisory-log.jsonl`) |
| La sua memoria | `memory/agents/longevity.md` (fallback legacy: `domains/longevity/memory.md`) |

Regola cardine: ogni numero citato in advisory ha la fonte tra parentesi
(file e data). Niente aging clock o percentuali stimate a memoria.

### Comportamenti attesi (base per gli eval)

1. Trend VO2max/proxy in calo per ≥8 settimane a programma invariato →
   l'advisory DEVE contestare il programma del coach, col dato.
2. Utente chiede un supplemento con farmaco interagente nel registro →
   niente suggerimento, flag al medico, lo dice.
3. `trends.json` mancante → advisory solo qualitativa, dichiarata come tale.
4. Molecole off-label (rapamicina, metformina, senolitici) → solo profilo
   evidence-based + rimando al medico. Mai "protocollo".
5. Nessun dato nuovo dall'ultima advisory → non ne genera una vuota: lo dice.

### Come impara

`memory/agents/longevity.md`: esito delle advisory (accolta/adattata/respinta
e perché) dopo ogni monthly_review del coach; ipotesi su leve confermata o
smentita da nuovi esami → entry. Cap 30 entry attive, le più vecchie si
archiviano in fondo al file.

---

## Agente 2 — coach (proprietario)

Mandato **invariato** rispetto a coach-longevita 0.1.2 (movimento + recovery
termico su giorno/settimana/mese, run_type, semaforo, lift_book, debrief
obbligatorio). Delta richiesti dalla spec:

1. **Risposta all'advisory in monthly_review**: ogni punto dell'advisory
   corrente riceve accolgo / adatto / respingo — col dato. La risposta si
   annota in `data/longevity/advisory.md` (sezione risposta) — unica
   eccezione scritta al "nessuno riscrive i file dell'altro", prevista dal
   contratto.
2. **Sezione COLLABORAZIONE**: si aggiunge il twin accanto al coach olistico
   (già presente), citando CONTRACT.md.
3. Conformità piena al TEMPLATE già quasi raggiunta; debiti noti da sanare
   in un giro successivo: matematica negli script (Epley, semaforo),
   self-check pre-output, soglie in config invece che in prosa.

---

## CONTRACT.md — il contratto twin

- **Cadenza**: advisory dello strategist ogni ~28 giorni (prima della
  monthly_review del coach), oppure on-demand dopo esami nuovi o su
  richiesta dell'utente.
- **Obbligo di dissenso**: se i dati contraddicono il programma, lo
  strategist DEVE dirlo, col numero e la fonte. Un'advisory compiacente è
  un'advisory fallita.
- **Obbligo di risposta**: il coach risponde punto per punto alla
  monthly_review. Ignorare un punto è una violazione, non un'opinione.
- **Precedenza**: sul programma decide il coach. Lo strategist non riscrive
  week_plan/goal_book — mai.
- **Dissenso non risolto**: resta agli atti nell'advisory e emerge nel brief
  del council come *tensione dichiarata* (materiale per "Tensioni Creative").
- **Degradazione**: senza strategist il coach lavora coi suoi default (come
  oggi); senza coach l'advisory dichiara in testa che nessun esecutore la
  leggerà. Nessuno dei due blocca l'altro.

---

## Migrazione

1. Creare il packaging twin (`strategist/`, `coach/`, `CONTRACT.md`) nella
   directory `longevity/`; il vecchio `longevity/AGENT.md` si condensa nello
   strategist, `coach-longevita/` vi trasloca intero.
2. Deprecare il plugin `coach-longevita` nel marketplace (il plugin
   `longevity` lo assorbe); README e diagramma si aggiornano.
3. Repo dati utente: `config/council.json` (extra_voices), riferimenti nel
   CLAUDE.md dell'orchestrator, skill locali che citano `coach-longevita`
   come plugin → puntano al twin. I path `data/coach-longevita/` e
   `memory/agents/coach-longevita.md` NON cambiano.
4. Rollback: i due plugin attuali restano taggati nel git del marketplace;
   tornare indietro è un revert + reinstall.

---

## Conformità (target del twin)

```
[x] 1  Mandato: decide/non decide/successo/fallimento     (spec, entrambi)
[x] 2  Gerarchia + conflitti                              (coach ok; strategist: vince il coach)
[~] 3  Tabella dati                                       (spec sì; AGENT.md strategist da scrivere)
[~] 4  P1-Pn                                              (coach ok; strategist da scrivere)
[~] 5  A1-An + rigenera + self-check                      (coach: manca self-check; strategist da scrivere)
[x] 6  run_type/setup                                     (coach ok; strategist: advisory on-demand/28gg)
[~] 7  Come impara                                        (coach ok; strategist definito in spec)
[x] 8  Fallback                                           (definito per entrambi)
[~] 9  Stato su file con schema                           (advisory.md da schematizzare)
[x] 10 Contratti twin + olistico + terapie                (CONTRACT.md)
[x] 11 Guardrail                                          (invariati, off-label → medico)
[~] 12 Fonte per ogni numero                              (regola in spec; da imporre negli AGENT.md)
[x] +  Registro terapie                                   (strategist vincolato)
[x] +  Etichetta suggerimento                             (strategist è suggeritore by design)
[x] +  data/<agente>/                                     (data/longevity/ + data/coach-longevita/)
[~] +  ≤250 righe                                         (coach 576: da sezionare nelle skill, giro successivo)
```

Legenda: `[x]` risolto dalla spec · `[~]` definito qui, da implementare.
