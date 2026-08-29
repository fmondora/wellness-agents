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

## Plugin con server MCP

Un plugin che vuole dare al proprio agente accesso diretto a dati
strutturati del repo dati lo fa dichiarando un server MCP nel proprio
manifest — mai chiedendo all'utente configurazione manuale:

```json
// .claude-plugin/plugin.json del plugin
"mcpServers": {
  "<nome>-sqlite": {
    "command": "uvx",
    "args": ["mcp-server-sqlite", "--db-path", "data/<agente>/<db>.db"]
  }
}
```

Regole del pattern (esempio vivo: `dna-sqlite` del plugin genomics):
1. **Path SEMPRE relativi** → si risolvono nel repo dati della sessione:
   stesso plugin, dati diversi per ogni persona.
2. **Read-only per convenzione** sui dati personali: l'agente interroga via
   MCP, scrive SOLO via i propri script deterministici.
3. **L'AGENT.md documenta entrambi i lati**: come nasce il server
   (prerequisiti tipo `uv`, verifica dei tool `mcp__<nome>__*`, riavvio
   di sessione dopo install/update) e come si usa (schema tabelle, quando
   preferirlo agli script, query d'esempio, limiti noti).
4. **Fallback dichiarato**: nei runtime con shell le stesse query passano
   da `sqlite3`; nei runtime senza shell l'MCP è l'unica porta — se manca,
   l'agente lo dice invece di improvvisare.

## Intake per-agente

Alcuni agenti richiedono dati propri alla prima attivazione, dichiarati nella
sezione "Setup" del loro AGENT.md: jyotish → dati natali (`data/kundali.json`);
ayurveda → prakriti (profilo); tcm → costituzione; genomics → raw DNA
(`data/dna/`); tantra-guide → punto di partenza (`data/tantra/curriculum.json`);
coach-longevita → questionario onboard (`data/coach-longevita/state.json`).

Regole:
1. L'agente si auto-verifica alla prima invocazione DIRETTA e fa il suo intake.
2. Nel COUNCIL non si fa mai intake: nota esplicita ("mi mancano i dati X")
   e si procede in modo generico o senza quella lettura.
3. Il `/setup` del generalista, composto il consiglio, elenca gli intake
   mancanti dei membri scelti e propone di completarli subito o rimandarli.

