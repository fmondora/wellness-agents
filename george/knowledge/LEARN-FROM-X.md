# Come George impara da X (e YouTube) — @Bluefidel47

Obiettivo: l'agente resta allineato al medico reale sul profilo, non a uno snapshot morto.

**Canali:** X primario · YouTube secondario (quando identificato)

### Scraper lento (sconsigliato — rischio ban)

**Preferenza di default: niente ban risk.** Non usare lo scraper con l’account X personale dell'utente.

Vie sicure (in ordine):
1. **Sync orchestrator** — tool `from:Bluefidel47` / semantic (nessun login tuo)
2. **TwitterAPI.io** — `export TWITTERAPI_IO_KEY=...` poi  
   `python3.12 scripts/george_twitterapi_io.py --pages 20`  
   (script nel repo dati dell'utente; free tier: 1 req/5s; ~$0.15/1k tweet; no login X personale)
3. **Paste manuale** di thread medici lunghi → `data/george/x-feed-log.md` / `framework`

Lo script `scripts/george_x_scrape.py` (repo dati) resta solo per account throwaway + flag esplicito `--i-accept-ban-risk`.

---

## Source of truth

| Campo | Valore |
|-------|--------|
| Handle | `@Bluefidel47` |
| Nome display | George |
| Focus | Longevity, reverse aging, chetocarnivora, stack molecolari |

### Limite tecnico (onestà)
I tool X restituiscono **max ~10 post per query**. Non si può “leggere tutti i tweet” in un colpo.
Strategia: molte query (finestre `since/until`, keyword, semantic) → unione + filtro medicina → `framework.md`.
Un “sync full medical” = **massima copertura protocolli**, non archivio legale completo.

---

## Trigger di sync

1. Utente: *«aggiorna George»*, *«sync George»*, *«cosa ha scritto George»*
2. Orchestrator: se `data/george/x-feed-log.md` (repo dati; si crea al primo sync) ha `last_sync` > 7 giorni — o non esiste — e la query è su George
3. Post-sessione significativa su reverse aging (opzionale, se c'è tempo tool)

---

## Procedura (orchestrator / Grok / Claude)

### Step 1 — Raccolta
Esegui in parallelo (o sequenza):
- Keyword search `from:Bluefidel47` mode **Latest** (max)
- Keyword search `from:Bluefidel47` mode **Top**
- Semantic search su: `protocollo dieta integratori longevità NMN chetocarnivora` limitando a username Bluefidel47

### Step 2 — Filtro scope

**IN (scrivi nel log) — solo medicina:**
- Dieta, digiuno, macro, alimenti
- Integratori, dosi, timing, sinergie
- Biomarker, interpretazioni lab
- Biohacking, movimento, sonno, recovery
- Protocolli salute (anche controversi) — etichettati con risk

**OUT assoluto (scarta, non loggare):**
- Politica, geopolitica, immigrazione, guerre, partiti, poll
- Sport gossip, cultura pop non clinica
- Quote politiche anche se "di sfondo" al post

**Nota:** all'utente interessa la medicina di George, non le sue opinioni politiche.

### Step 3 — Estrazione
Per ogni post rilevante:
- `date`, `post_id`, `engagement` (likes/views se utili)
- `thesis` (1 riga)
- `protocol_delta` (cosa è nuovo o ridetto)
- `evidence_level`: aneddoto | thread lungo | studio citato | quote di terzi
- `risk`: low | medium | high (farmaci, onco, claim assoluti)

### Step 4 — Persistenza
1. Appendi blocco in `data/george/x-feed-log.md` nel repo dati (più recente in alto; crea il file al primo sync)
2. Se cambia un protocollo stabile → patch `framework.md`
3. Se cambia identità/tono/pilastri → patch `AGENT.md` (sezione Framework)
4. Entry breve nella memoria agente: `memory/agents/george.md` (fallback legacy: `domains/george/memory.md`)

### Step 5 — Risposta all'utente
Dopo sync: 5–10 bullet *cosa c'è di nuovo*, non dump grezzo dei tweet.

---

## YouTube — quando compare un canale o video suoi

**Stato (2026-08-02):** nessun canale ufficiale trovato per Bluefidel47 / George longevity.  
**Regola:** non appena utente o sync X rivelano un link YouTube **suo** (canale o video long-form in cui parla lui di medicina):

1. Registrare in `knowledge/youtube-sources.md`:
   - URL canale / video
   - data discovery
   - titolo, tema, protocolli citati
   - risk level (low/medium/high)
2. Distillare solo **medicina** → patch `framework.md` se stabile
3. Entry in `memory/agents/george.md`: `YYYY-MM-DD — YouTube: …`
4. Nei reply X, se linka video **di terzi**, non contano come “sua voce” salvo che commenti con un protocollo proprio

**Come cercare canale (a ogni sync o su richiesta “cerca YouTube George”):**
- Bio e pin di @Bluefidel47
- Keyword `from:Bluefidel47 (youtube OR youtu.be OR canale)`
- Web: `"Bluefidel47" youtube`, `George longevity Bluefidel youtube`

**Trigger extra:** *«sync George YouTube»*, *«ha un canale?»*, link YouTube incollato dall’utente.

**Filtro:** stesso IN/OUT della medicina — no politica nei transcript/video.

---

## Template entry `data/george/x-feed-log.md`

```markdown
## YYYY-MM-DD — Sync

**last_sync:** YYYY-MM-DDTHH:MM
**posts_scanned:** N
**in_scope:** N

### Nuovo / rilevante
- [post_id] thesis — protocol_delta (risk)

### Confermato (già nel framework)
- ...

### Out of scope (ignorato per clinica)
- ...
```

---

## Regole di fusione knowledge

| Segnale | Azione |
|---------|--------|
| Stesso protocollo ripetuto 3+ volte | Promuovi in `framework.md` se non c'è |
| Contradizione col framework | Nota "evoluzione" in log + tieni entrambe finché non chiarisce |
| Dose/farmaco high-risk | Solo log + disclaimer; non automatizzare in consigli all'utente |
| Immagine protocollo (foto) | Descrivi e linka; se possibile OCR/nota manuale |

---

## Comando rapido per l'orchestrator

Quando l'utente dice solo **"aggiorna George"**:

1. Esegui procedura sopra  
2. Scrivi log  
3. Rispondi: novità + eventuale impatto sull'utente (profile/log)  
4. Non spawnare altri agenti salvo richiesta  
