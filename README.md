# Wellness Agents

Marketplace di agenti per il benessere integrato — medici osservazionali,
coaching, tradizioni. **Identità senza memoria**: ogni agente è un plugin
installabile singolarmente; tutto lo stato personale (profilo, log, esami,
memorie) vive nel *repo dati* privato di ciascun utente, mai qui.

Ogni persona compone il proprio consiglio: installa solo gli agenti che vuole
e li elenca in `config/council.json` del proprio repo dati.

## Installazione (Claude Code)

```
claude plugin marketplace add <questo-repo>
claude plugin install wellness-core        # obbligatorio
claude plugin install coach-longevita      # e gli altri che vuoi
```

Altri runtime (Grok Build/TUI, Hermes): vedi `adapters/`.

## Plugin

| Plugin | Cosa fa |
|---|---|
| `wellness-core` | Fondamento tantrico, propagation agent, convenzioni repo dati (`core/CONVENTIONS.md`) |
| `coach-longevita` | Training per durare: daily/week plan, debrief, lift book, uno skill alla volta |

In migrazione dal sistema originale: health, nutritionist, genomics, george,
ayurveda, tcm, functional-medicine, shamanic-plants, jyotish, tantra-guide,
logger (ingestione unificata: persona, wearable, Telegram).

## Principi

- Il repo dati è la persona; il plugin è il sapere. Mai mescolarli.
- Guardrail clinici identici per tutti, non configurabili.
- Nessun agente diagnostica o prescrive. Red flag → medico, subito.
