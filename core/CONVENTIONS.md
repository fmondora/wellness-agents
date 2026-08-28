# Convenzioni del Repo Dati Personale

Gli agenti di questo marketplace sono **identità senza memoria**: tutto lo
stato vive nel *repo dati personale* di ciascun utente. Gli agenti si eseguono
con la directory corrente dentro quel repo (o, per gli script, con `--data-dir`).

## Layout del repo dati

```
<repo-dati>/
├── data/
│   ├── profile.json            # profilo, vincoli, medications, guardrail personali
│   ├── logs/YYYY-MM-DD.json    # log giornalieri
│   ├── fitbit/ insights/       # wearable e trend (se presenti)
│   └── <agente>/               # stato per-agente (es. coach-longevita/)
├── kb/                         # knowledge base clinica personale (esami, condizioni…)
├── memory/agents/<agente>.md   # memoria vivente di ogni agente
└── config/
    ├── council.json            # CHI partecipa al consiglio di questa persona
    └── *.json + .env           # soglie, token, segreti (MAI nel plugin)
```

Fallback legacy (repo dati nati prima di questo marketplace): la memoria può
trovarsi in `domains/<agente>/memory.md` o `traditions/<agente>/memory.md` —
gli agenti provano prima il path nuovo, poi il legacy.

## config/council.json

```json
{
  "members": ["ayurveda", "tcm", "functional-medicine", "shamanic-plants"],
  "pre_reading": "jyotish",
  "extra_voices": ["coach-longevita", "george"],
  "output_style": "full"
}
```

Il council convoca solo i membri elencati E installati come plugin.
Un membro elencato ma non installato → nota esplicita, si procede con gli altri.
Il propagator propaga solo verso le memorie degli agenti presenti.

## Regole condivise (tutti gli agenti)

1. **Privacy**: nessun dato personale entra mai nei repo dei plugin.
2. **Output umano**: JSON e strutture = stato su file; all'utente solo prosa
   o schema leggibile. Mai payload a schermo.
3. **Guardrail clinici non negoziabili**: red flag → escalation immediata;
   mai diagnosi, prescrizioni, dosaggi. Identici per ogni utente, non configurabili.
4. **Memoria**: dopo sessioni significative, aggiorna `memory/agents/<te>.md`
   (formato: `## YYYY-MM-DD — Titolo` + implicazione).
5. **Runtime**: le identità sono markdown neutro. Claude Code le usa via skill
   (`${CLAUDE_PLUGIN_ROOT}`), Grok/Hermes via adapters (vedi `/adapters`).
