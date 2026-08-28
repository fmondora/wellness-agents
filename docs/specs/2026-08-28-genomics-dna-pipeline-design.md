# Genetista — Pipeline DNA deterministica (design)

*2026-08-28 · plugin `genomics` del marketplace wellness-agents*

## Problema

Il genetista del marketplace ha un'identità ma nessuno strumento: l'estrazione
dal raw 23andMe (~630k SNP, chip v5, build GRCh37, plus strand) è stata fatta
a mano una volta (58 SNP nel kb dell'utente) e non è riproducibile. Serve una
pipeline **deterministica**: stesso raw + stessa versione dei database =
stesso output, sempre — con tutti i dati personali confinati nel repo dati.

## Decisione

Pipeline Python a strati, tutta offline (Opzione 1 della discussione), con
quattro strati di annotazione: **clinico (ClinVar)**, **farmacogenomica
(CPIC/PharmGKB)**, **tratti (GWAS Catalog)**, **wellness (pannelli curati nel
plugin)**. Query interattiva via CLI e via **server MCP SQLite** dichiarato
nel manifest del plugin.

Scartate: toolchain VEP/snpEff (cache ~20GB, overkill per dati array) e
annotazione via API esterne (i genotipi non escono mai dalla macchina; le API
cambiano nel tempo = non deterministico). Unica eccezione: lookup opzionale
`--web` che invia SOLO un rsID (identificatore pubblico), mai il genotipo.

## Architettura

Nel plugin `genomics` (v0.2.0):

```
genomics/
├── AGENT.md                  ← aggiornato: mapping strumenti + guardrail report
├── skills/dna/SKILL.md       ← la skill /dna del genetista
├── scripts/
│   ├── dna_ingest.py         ← raw → genotypes.db
│   ├── dna_annotate.py       ← join deterministico per strato
│   ├── dna_report.py         ← markdown: kb/genomica.md + reports/
│   ├── dna_query.py          ← lookup rsID/gene (+ --web opzionale)
│   └── tests/ + fixtures/    ← raw sintetico ~100 SNP + mini-DB per strato
├── knowledge/panels/*.json   ← pannelli curati per pathway (sapere pubblico)
└── .claude-plugin/plugin.json  ← + mcpServers: sqlite su data/dna/genotypes.db
```

Nel repo dati dell'utente (`data/dna/`):

```
raw/                     ← file sorgente (xlsx, txt 23andMe, VCF minimale)
genotypes.db             ← SQLite: genotypes + annotations_<layer> + meta
db/                      ← cache DB esterni + versions.json (release pinnate)
annotated/<layer>.jsonl  ← output riga-per-riga con fonte e versione DB
reports/                 ← clinvar.md, pharmgkb.md, gwas.md
```

`kb/genomica.md` = vista curata generata dallo strato panels (mai più a mano).

## Componenti

### dna_ingest.py `<file>`
- Autodetect formato: xlsx (riga di intestazione dati trovata cercando le
  colonne rsid/chromosome/position/genotype), txt 23andMe (tab-separated,
  commenti `#`), VCF minimale (solo righe con rsID e GT).
- Normalizza in `genotypes.db`: tabella `genotypes(rsid PK, chrom, pos,
  genotype, source_file, build)`; tabella `meta` (build, chip, data campione,
  hash del sorgente, versione ingest).
- Idempotente: stesso file (hash) → no-op dichiarato.

### dna_annotate.py `--layer clinvar|pharmgkb|gwas|panels [--update-db]`
- Scarica in `data/dna/db/` (solo con `--update-db` o cache assente):
  ClinVar VCF **GRCh37** (build coerente col raw), CPIC allele/guideline data
  (aperto; PharmGKB dump se l'utente registra l'account), GWAS Catalog
  associations TSV. Ogni download registra release/data in `versions.json`.
- Join sul DB → `annotated/<layer>.jsonl` + tabella `annotations_<layer>`
  in SQLite. Ogni riga: rsid, genotipo, annotazione, fonte, versione DB.
- Panels: nessun download — i pannelli sono nel plugin.

### dna_report.py `[--layer ...]`
- `kb/genomica.md`: sezioni per pathway dai panels (formato tabella attuale:
  Gene | SNP | Genotipo | Effetto | Rilevanza) + sezione Fonti (file raw,
  versioni DB, data generazione).
- `reports/clinvar.md`: SOLO varianti P/LP/protective presenti nel raw, con
  header fisso non rimovibile: *"Dati da chip array: falsi positivi noti.
  Ogni variante patogenica va confermata con sequenziamento clinico e
  valutata con un genetista medico. Questo report non è una diagnosi."*
- `reports/pharmgkb.md`: gene–farmaco con livello di evidenza; chiusura
  fissa "da discutere con il medico che prescrive".
- `reports/gwas.md`: associazioni raggruppate per tratto, con p-value ed
  effect size — e la nota che gli effect size GWAS sono piccoli per natura.

### dna_query.py `rs4680 | --gene COMT [--web]`
- Lookup su genotypes + tutte le annotations. `--web`: arricchimento
  metadati pubblici inviando solo l'rsID.

### MCP SQLite (manifest del plugin)
- Server `mcp-server-sqlite` (via uvx) con `--db-path data/dna/genotypes.db`
  (path relativo → si risolve nel repo dati corrente). Dà al genetista SQL
  libero su genotipi + annotazioni per le domande fuori-report.

### Pannelli (`knowledge/panels/*.json`)
- Un file per pathway: th2, metilazione, nutrizione, detox-fase1, detox-fase2,
  omega, vitamina-d, farmacogenomica-core, ossidativo, barriera, cardiovascolare.
- Schema per SNP: `rsid`, `gene`, `label`, `interpretations` (mappa genotipo →
  effetto + rilevanza), `refs` facoltative. Contenuto = letteratura pubblica,
  MAI genotipi di persone. Seed: i pathway del kb esistente, generalizzati.

## Flusso

```
raw → dna_ingest → genotypes.db
                     │ dna_annotate (per strato, DB pinnati)
                     ▼
       annotated/*.jsonl + annotations_* in SQLite
                     │ dna_report
                     ▼
       kb/genomica.md + data/dna/reports/*.md
```

Il genetista (skill /dna): risponde da kb + reports; per domande puntuali usa
dna_query o SQL via MCP; se manca il raw fa l'intake (già in AGENT.md);
rigenera con i comandi sopra quando arriva un nuovo file o release DB.

## Error handling

- **Build mismatch**: il join usa SOLO release DB della build del raw
  (GRCh37); mai mescolare build. La build vive in `meta` e ogni script la verifica.
- **No-call (`--`) e indel (`DD/DI/II`)**: esclusi dai join SNP, contati e
  riportati nei report ("N varianti non valutabili").
- **Multi-allelici**: match per allele, non per stringa genotipo.
- **Download fallito**: si resta sulla cache esistente dichiarando la versione
  usata; senza cache → errore chiaro, mai output parziale silenzioso.
- **Raw assente**: nessuna invenzione — l'agente rimanda all'intake.

## Testing

- Fixture nel plugin: raw sintetico (~100 SNP inventati, nei 3 formati) +
  mini-DB per ogni strato (10-20 righe costruite ad hoc).
- Golden test: report generati dalle fixture confrontati byte-per-byte.
- Test di determinismo: doppia esecuzione completa → hash identici.
- Test error handling: no-call, indel, build sbagliata, file corrotto.
- MAI genotipi reali nelle fixture o nel repo del plugin.

## Guardrail (invariati, rafforzati)

Il genetista interpreta pathway e predisposizioni wellness. Le hit cliniche
le riporta col disclaimer, non le annuncia. Mai diagnosi, mai determinismo
genetico, mai consigli su farmaci — "col medico che prescrive". I dati
genetici non lasciano mai il repo dati (unica eccezione: rsID nudi con --web).

## Non-goals (YAGNI)

- Imputazione, polygenic risk scores, aplotipi CYP2D6 da array (inaffidabili
  senza dati di copy number), supporto WGS/BAM, UI grafica.
- Aggiornamento automatico schedulato dei DB: si aggiorna a richiesta
  (`--update-db`), la riproducibilità vale più della freschezza.
