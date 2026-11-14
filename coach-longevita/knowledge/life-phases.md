# Fasi di vita — cosa cambia nel movimento

*Bozza. Le regole dure stanno in `life-phases.json` e le applica `scripts/workout_guard.py`;
qui il razionale e le indicazioni che il coach applica a giudizio. Da rivedere con chi ha
competenza clinica (fisioterapista del pavimento pelvico, ginecologa) prima di darla per definitiva.*

La fase di vita si dichiara nel profilo (`data/profile.json` → `life_phase`), non nello stato del
coach: la leggono anche DreamAgent (sonno), la nutrizionista e Hṛdaya.

```json
"life_phase": {
  "stage": "premenopausa | perimenopausa | menopausa | postpartum | gravidanza | null",
  "postpartum_since": "YYYY-MM-DD",
  "pelvic_floor": {"symptoms": ["perdite con salti", "pesantezza"], "cleared_by_physio": false},
  "bone": {"osteopenia": false, "osteoporosis": false, "vertebral_fracture": false},
  "notes": ""
}
```

Tutto facoltativo: un campo che manca non accende nessuna regola. Il coach non chiede dati che la
persona non vuole dare e non trasforma la fase di vita in una diagnosi.

## Limiti duri (il blocco del canale)

| Condizione | Cosa blocca | Fino a quando |
|---|---|---|
| Gravidanza | Tutta la programmazione: fuori dal perimetro del coach | Indicazione dell'ostetrica o del ginecologo |
| Parto da meno di 12 settimane | Corsa e salti | Valutazione del pavimento pelvico (`cleared_by_physio`) |
| Sintomi del pavimento pelvico | Salti (corda, box, burpee, jack…) | Via libera della fisioterapista |
| Frattura vertebrale | Flessione del tronco ripetuta o caricata (crunch, sit-up, V-up, toes-to-bar, ab wheel) | Sempre, salvo diversa indicazione medica |

## Perimenopausa e menopausa

- **Forza almeno 2 volte a settimana**, progressiva, sui grandi pattern (squat, hinge, push, pull,
  carry). È la leva principale per osso e massa muscolare in questa fase.
- **Impatto progressivo** (salti bassi, step-down, drop landing) se l'osso lo consente: con
  osteoporosi nota l'impatto si introduce piano e con indicazione clinica.
- **Carichi alti non sono vietati**: con tecnica e progressione supervisionata il carico alto è
  stato usato in sicurezza anche con massa ossea bassa (LIFTMOR).
- **Recupero**: la stessa seduta può pesare di più; il semaforo resta la guida, ma un sonno
  frammentato da vampate notturne conta come notte mediocre.
- **Calore**: vampate e sudorazione notturna rendono il blocco termico meno tollerato. Sauna e
  hot tub solo se piacciono e non peggiorano le notti; mai prescritti.
- **Sintomi nuovi** (sanguinamenti anomali, dolore pelvico, palpitazioni) → flag al nodo medico.

## Pavimento pelvico

- Il segnale guida sono i **sintomi durante lo sforzo**: perdite, pesantezza, pressione verso il
  basso. Non c'è un esercizio vietato a tutte; c'è il carico che *quella* persona oggi gestisce.
- Con sintomi: niente salti finché la fisioterapista non dà il via (regola dura). Sui carichi
  pesanti si riduce il peso o si cambia schema (espirare nello sforzo, niente apnea prolungata),
  si tiene nota di cosa li provoca nel debrief.
- L'allenamento dei muscoli del pavimento pelvico è il trattamento di prima linea per
  l'incontinenza da sforzo: lo prescrive la fisioterapista, il coach lo lascia spazio nel cap.
- **Postparto**: rientro alla corsa non prima di 12 settimane e dopo una valutazione; forza e
  cammino sì prima, con progressione.

## Nel debrief

Se la fase di vita è dichiarata, una domanda in più quando c'erano salti o carichi alti:
«Pavimento pelvico: tutto ok / qualche perdita / pesantezza». Il dato va nel debrief, non si
commenta come voto; un peggioramento → flag al nodo medico.

## Fonti

- Brooke-Wavell K. et al. *Strong, steady and straight: UK consensus statement on physical activity
  and exercise for osteoporosis.* Br J Sports Med 2022.
- Watson S.L. et al. *High-intensity resistance and impact training improves bone mineral density
  and physical function in postmenopausal women with osteopenia and osteoporosis: the LIFTMOR
  randomized controlled trial.* J Bone Miner Res 2018.
- Kohrt W.M. et al. *ACSM position stand: physical activity and bone health.* Med Sci Sports Exerc 2004.
- Dumoulin C. et al. *Pelvic floor muscle training versus no treatment, or inactive control
  treatments, for urinary incontinence in women.* Cochrane Database Syst Rev 2018.
- Goom T., Donnelly G., Brockwell E. *Returning to running postnatal — guidelines for medical,
  health and fitness professionals managing this population.* 2019.
