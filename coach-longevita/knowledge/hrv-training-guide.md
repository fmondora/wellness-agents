# HRV come bussola dell'allenamento
*Guida operativa — riferita dall'AGENT.md*

---

## La scala personale dell'utente

Prima di applicare qualsiasi soglia, individua la scala HRV
dell'utente nel suo repo dati:

- Il valore tipico è **rMSSD in ms** da misura notturna
  (wearable: Fitbit, Oura, Garmin, ecc.)
- Baseline mobile 30 giorni: se il repo dati la calcola,
  cercala in `data/insights/trends.json`; altrimenti stimala
  dalla mediana degli ultimi 30 log
- ⚠️ Alcune app (es. scale "Recovery Points" 1-10) usano scale
  proprietarie: **scale diverse non si confrontano mai tra loro**.
  Se nei log storici coesistono più scale, trattale come serie separate.

Il range personale va osservato, non assunto: nota il minimo
(giorni di crollo) e il massimo (recupero pieno) dell'utente
e ragiona sempre in relazione alla sua baseline.

## Il semaforo mattutino

Soglie relative alla baseline mobile 30gg (adattale se il repo
dati dell'utente definisce soglie proprie in `config/`):

| rMSSD mattutino | Cosa fare |
|---|---|
| ≥ baseline | Allenamento pieno — forza o metcon, con intenzione |
| 5-15% sotto baseline | Solo zona 2: camminata lunga, bici lenta, mobilità |
| > 15% sotto baseline | Recupero attivo, niente intensità |
| > 15% sotto baseline per 2 mattine | Riposo. Sauna ok. Indaga la causa |

## Zone operative

- **Zona 2** — conversazionale, naso-respirabile. Tipicamente
  camminata sostenuta, bici lenta, nuoto tranquillo. Come proxy FC:
  ~60-70% della FC massima stimata.
- **Intensità** (metcon/forza pesante) — FC alta sostenuta.
  Solo con semaforo verde, e mai nei giorni già dedicati ad altri
  stressor termici pianificati (es. sauna).

## Progressione rientro post-detraining (>2 settimane di stop)

1. Settimane 1-2: forza lenta al 60% del carico abituale, 2 sessioni + camminate
2. Settimane 3-4: +1 metcon breve (≤12 min), carichi al 75%
3. Settimana 5+: programmazione normale se HRV stabile ≥ baseline

Deload ogni 4-6 settimane. Se l'utente ha una condizione respiratoria
(es. asma da esercizio): warm-up respiratorio lungo (10 minuti progressivi)
per prevenire il broncospasmo; verifica nel profilo la copertura della
terapia rispetto all'orario di allenamento e segnala al medico
qualsiasi cambio di tolleranza allo sforzo.

## Segnali di stop

- HRV in calo per 3+ giorni consecutivi nonostante riposo → guarda oltre
  l'allenamento (infiammazione, stato del ferro, sonno, stress)
- Sintomi personali noti che peggiorano post-sessione (verifica il profilo
  e la memoria dell'agente) → ridurre intensità (asse simpatico)
- Dolore acuto → stop immediato + valutazione medica
