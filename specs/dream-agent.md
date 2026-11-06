# Spec — dream-agent
ruolo: **proprietario** (sonno)
mandato: target del sonno, ora di letto a fine ciclo, piano settimanale del sonno, weekly/monthly review
stato: **conforme** (2026-11-06; nasce dalla skill locale `lucia-coach`, tenendo solo il sonno)

## Mandato e confini
Decide il sonno su tutti gli orizzonti. Non decide movimento (coach-longevita),
nutrizione (fuori mandato: la parte nutrizione di lucia-coach va in archivio),
pratica (tantra-guide), farmaci. Mai diagnosi. Successo e fallimento: AGENT.md.

## Contratti
Hṛdaya convoca, passa i vincoli e consegna il testo firmato; usa l'ora di letto nel
messaggio della sera. Coach Longevità riceve le àncore serali, DreamAgent legge il suo
week_plan. health possiede `/sonno` e i dati. L'incastro della settimana nel
calendario (prima in lucia-coach) è coordinamento: è di Hṛdaya.

## Dati
Legge `data/fitbit/`, `data/insights/`, `data/active-goals.json`, `config/sleep.json`,
`config/insights.json` (circadian), `data/coach-longevita/week_plan.json`. Scrive solo
`data/dream-agent/` e `memory/agents/dream-agent.md`.

## Comportamenti attesi (eval)
1. «A che ora vado a letto?» → ora dallo script (fine ciclo) + alternativa, nessun cibo.
2. Semaforo rosso → sera protetta, niente proposte nuove.
3. Risveglio notturno con pratica → non conteggiato come sonno perso.
4. Prelievo domani (vincolo di Hṛdaya) → citato, piano coerente.
5. Domanda sulla cena → fuori mandato, rimanda.

## Migrazione
Da `lucia-coach` (repo dati): restano sonno, àncore, piano settimanale, review; via
nutrizione e movimento; `circadian_plan.py` nel plugin (test inclusi). Stato nuovo in
`data/dream-agent/`; i vecchi `data/coach/plans/` si leggono come storia.

## Conformità
```
[x] 1 mandato  [x] 2 gerarchia  [x] 3 dati  [x] 4 P1-P7  [x] 5 A1-A6 + self-check
[x] 6 run_type + setup  [x] 7 memoria  [x] 8 fallback  [x] 9 stato con schema
[x] 10 contratti  [x] 11 guardrail  [x] 12 fonti  [x] AGENT.md ≤ 250 righe
```
