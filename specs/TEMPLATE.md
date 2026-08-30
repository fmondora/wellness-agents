# TEMPLATE — Come si scrive un agente di questo repo

*Spec-first: prima la spec in `specs/<agente>.md`, poi l'AGENT.md che la
implementa. Il README rispecchia le spec, mai il contrario.*

Il canone nasce dal reverse engineering dei due agenti meglio scritti
(genomics per la disciplina sui dati, coach-longevita per la struttura
decisionale) e dalla gap analysis del 2026-08-29 sugli altri undici.

---

## Il flusso

1. **Spec** — si scrive/aggiorna `specs/<agente>.md` (questa struttura, sotto)
2. **Implementazione** — l'AGENT.md (e skills/knowledge/scripts) si allineano alla spec
3. **README** — la tabella plugin e il diagramma del colloquio si aggiornano dalla spec
4. **Bump** — versione del plugin a ogni modifica

Per gli agenti esistenti il flusso parte in reverse engineering:
la spec fotografa prima il target, poi l'implementazione insegue.
Una divergenza tra spec e AGENT.md è un bug della implementazione.

---

## Struttura della spec (`specs/<agente>.md`)

```markdown
# Spec — <nome>
ruolo: proprietario | suggeritore | frontline | tradizione | guida
mandato: <una riga: cosa possiede o su cosa suggerisce>
stato: target | conforme   (data ultima verifica)

## Mandato e confini      — cosa decide, cosa NON decide, successo, fallimento
## Contratti              — con quali agenti parla, chi possiede cosa, precedenze
## Dati                   — cosa legge (tabella), dove scrive, cosa non tocca
## Comportamenti attesi   — gli scenari che definiscono l'agente (base per gli eval)
## Migrazione             — solo se l'agente esiste già: delta e passi
## Conformità             — la checklist delle 12 dimensioni, compilata
```

---

## Le 12 dimensioni obbligatorie dell'AGENT.md

1. **Mandato con confini** — cosa decide e cosa NON decide, con definizione
   esplicita di *successo* E di *fallimento*. Un agente che non sa quando
   ha fallito non è valutabile.
2. **Gerarchia decisionale** — priorità ordinate + regole di conflitto nella
   forma "in conflitto tra X e Y → vince Y". I conflitti si scrivono prima
   che accadano.
3. **Accesso dati deterministico** — tabella operazione → file/script/tool
   reale (`Read data/...`, `python3.12 .../x.py`, tool MCP). Regola cardine:
   **i numeri ufficiali escono dai dati, mai dalla memoria del modello.**
4. **Pattern numerati (P1-Pn)** — il metodo positivo, azionabile, raggruppato
   per tema (le liste che crescono per accrezione degradano in changelog).
5. **Anti-pattern numerati (A1-An)** — con la clausola *"se lo fai, la
   risposta è sbagliata: rigenera"* E una checklist di self-check pre-output
   (3-6 righe) che li rende protocollo, non appello alla coscienza.
6. **Statefulness** — run_type espliciti se l'agente ha modalità; setup una
   tantum con cosa chiedere, cosa salvare, quando NON rifarlo.
7. **Come impara** — regole quantitative (soglia di ricorrenza, cap, trigger)
   e dove scrive: `memory/agents/<nome>.md` (fallback legacy dichiarato).
   Una memoria solo letta è una memoria morta.
8. **Fallback e degradazione** — file mancante/corrotto o tool assente →
   *dillo, resta conservativo, non inventare*. La degradazione elegante
   dichiara cosa si perde.
9. **Output separato dallo stato** — le strutture (JSON, schemi) vivono nei
   file di stato in `data/<agente>/`; alla persona arriva prosa. Lo schema
   dei file di stato è dichiarato, non lasciato all'esempio.
10. **Collaborazione** — contratti espliciti: chi possiede cosa, chi legge
    cosa, **nessuno riscrive i file dell'altro**. I contratti twin includono
    obblighi simmetrici (vedi Regole del colloquio).
11. **Guardrail clinici** — mai diagnosi, mai prescrizioni, escalation al
    medico reale definita. Identici per tutti, non configurabili.
12. **Verifica e integrità** — ogni numero/claim citato ha una fonte
    verificabile (file, script, hash, data del post). Chi fa override di un
    piano cita il dato che lo giustifica.

---

## Regole del colloquio (trasversali, non negoziabili)

Riflesse nel diagramma "Chi decide e chi suggerisce" del README:

- **Un mandato, un proprietario.** Nessun agente prescrive nel mandato di un
  altro. I suggeritori propongono dentro il mandato del proprietario.
- **I suggeritori etichettano.** Dosaggi, ricette, protocolli escono come
  *suggerimenti con fonte* — mai in formato prescrittivo, mai a memoria.
- **Registro terapie prima di ogni sostanza.** Chi suggerisce qualsiasi cosa
  di ingeribile legge prima cosa la persona sta prendendo (registro del
  generalista: `kb/terapie.md` + `medications` nel profilo). Se non può
  leggerlo, non suggerisce sostanze.
- **Il dissenso è un dovere dove c'è un contratto twin.** Chi ha l'obbligo di
  contestare lo fa col dato; chi riceve ha l'obbligo di rispondere punto per
  punto. Il disaccordo non risolto emerge nel council come tensione
  dichiarata, non si media in silenzio.
- **Spazi di scrittura.** Ogni agente scrive solo in `data/<agente>/` e nella
  propria memoria; legge tutto il resto.

---

## Convenzioni di implementazione

- **Privacy** — identità senza memoria: nulla di personale nel plugin, tutto
  nel repo dati (vedi `core/CONVENTIONS.md`).
- **Dimensione** — AGENT.md ≤ ~250 righe: il core sempre caricato è il
  mandato; le procedure per run_type vivono nelle skill, il sapere in
  knowledge/. Niente manuale integrale per un debrief da quattro righe.
- **Matematica negli script** — se l'agente ha calcoli con conseguenze
  (formule, soglie, punteggi), stanno in `scripts/` con test, non nella
  testa del modello. Le soglie riconfigurabili stanno in config/JSON, non
  hardcoded in prosa.
- **Niente ridondanza senza fonte unica** — una regola vive in un posto; se
  va ripetuta per aderenza, le copie citano la sezione madre.
- **Eval** — i "Comportamenti attesi" della spec sono scenari eseguibili:
  dato input X (semaforo RED, file mancante, farmaco in corso), l'output
  rispetta Y. Senza eval ogni bump è un deploy al buio.

---

## Checklist di conformità (da copiare e compilare nella spec)

```
[ ] 1  Mandato: decide / non decide / successo / fallimento
[ ] 2  Gerarchia + regole di conflitto
[ ] 3  Tabella dati + "numeri dai dati, mai dalla memoria"
[ ] 4  P1-Pn
[ ] 5  A1-An + "rigenera" + self-check pre-output
[ ] 6  run_type / setup una tantum
[ ] 7  Come impara (soglia, cap, dove scrive)
[ ] 8  Fallback conservativo dichiarato
[ ] 9  Stato su file con schema, prosa alla persona
[ ] 10 Contratti (ownership, twin se applicabile)
[ ] 11 Guardrail clinici + escalation
[ ] 12 Fonte per ogni numero citato
[ ] +  Registro terapie (se suggerisce sostanze)
[ ] +  Etichettatura suggerimento-vs-prescrizione
[ ] +  data/<agente>/ come unico spazio di scrittura
[ ] +  AGENT.md ≤ 250 righe, procedure nelle skill
```
