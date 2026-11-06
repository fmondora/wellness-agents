# Migrazione a Hṛdaya — mappa dei percorsi (marketplace 0.10.0)

Per chi ha un repo dati nato col `generalista` e con script locali (shim + launchd).
Regola: il repo dati trova i plugin solo in
`~/.claude/plugins/cache/wellness-agents/<plugin>/*/scripts/` — mai percorsi di questo repo.

## Script: vecchio → nuovo

| Nel repo dati oggi | Nuovo canonico (cache del plugin) | Note |
|---|---|---|
| shim `scripts/health_api.py` → `generalista/*/scripts/` | `health/*/scripts/health_api.py` | CLI e modulo invariati |
| shim `scripts/health_extract.py` | `health/*/scripts/health_extract.py` | invariato |
| shim `scripts/health_metrics.py` | `health/*/scripts/health_metrics.py` | invariato (era duplicato) |
| shim `scripts/health_sync.py` | `health/*/scripts/health_sync.py` | invariato |
| shim `scripts/insights_engine.py` | `health/*/scripts/insights_engine.py` | `insights_tick(env)` invariata; le notifiche immediate vanno in `data/telegram/push.jsonl` (cancello) invece che in outbox; non lancia più il buongiorno né il nudge serale |
| shim `scripts/trends.py` | `health/*/scripts/trends.py` | invariato |
| shim `scripts/telegram_queue.py` | `hridaya/*/scripts/telegram_queue.py` | stesse funzioni + `enqueue_system`, `record_sent`, lock |
| `scripts/telegram_bot.py` | `hridaya/*/scripts/telegram_bot.py` | da shim; token da portachiavi o `.env`; esce se `ALLOWED_CHAT_IDS` è vuoto (niente più bootstrap col primo messaggio) |
| `scripts/workout_player.py` | `hridaya/*/scripts/workout_player.py` | lato canale del player, stesse funzioni |
| `scripts/telegram_send_rich.py` | `hridaya/*/scripts/telegram_send_rich.py` | `--push` = passa dal cancello; foto solo da cartelle di export |
| `scripts/telegram_send_file.py` | `hridaya/*/scripts/telegram_send_file.py` | `load_env()` compatibile; file solo da cartelle di export |
| `scripts/telegram_get_chat_id.py` | `hridaya/*/scripts/telegram_get_chat_id.py` | percorso guidato: `telegram_setup.py wait-start --register` |
| `scripts/morning_message.py` | `hridaya/*/scripts/morning_message.py` | solo fallback deterministico (`--wake`/`--evening`/`--print`), passa dal cancello; il buongiorno vero lo scrive la sessione |
| `scripts/kaula_voice.py` | — | spento (niente LLM headless) |
| `scripts/meditation_detect.py` | `health/*/scripts/meditation_detect.py` | invariato; `WELLNESS_DATA` dallo shim |
| `scripts/webhook_receiver.py` | `health/*/scripts/webhook_receiver.py` | secret `HEALTH_WEBHOOK_SECRET` (accetta ancora `LUCIA_WEBHOOK_SECRET`); confronto a tempo costante |
| `scripts/register_webhook.py` | `health/*/scripts/register_webhook.py` | progetto, endpoint, subscriber ora dal `.env` (vedi sotto) |
| `scripts/sleep_analysis.py` | `health/*/scripts/sleep_analysis.py` | copia già presente nel plugin |
| `scripts/circadian_plan.py` | `dream-agent/*/scripts/circadian_plan.py` | `evening_nudge_time` non serve più (la sera è di Hṛdaya) |
| `scripts/workout_send.py` | `coach-longevita/*/scripts/workout_send.py` | fallback: in sessione si usa il tool `telegram_send_player` |
| `scripts/workout_fitbit.py` | `coach-longevita/*/scripts/workout_fitbit.py` | invariato |
| `scripts/telegram_ingest.py` | `tantra-guide/*/scripts/telegram_ingest.py` | sessione Telethon spostata da sola in `~/.config/tantra-guide/`; post salvati come citazioni |
| `apps/workout-player/` | `coach-longevita/*/apps/workout-player/` | `deploy.sh` con `WELLNESS_DATA`; clip nuove in `data/coach-longevita/player-voice/` |

Restano nel repo dati (non spostati in questa fase): `lucia_daemon.py` (togliere
`process_telegram` e la risposta xAI: risponde solo la sessione), `weekly_review_job.py`
(il consiglio trend headless si spegne: le review sono dei coach, in calendario di Hṛdaya;
se resta un invio, `telegram_send_rich.py --push`), `hrv_merge.py`, `lucia_api.py`,
`voice_ingest.py`, `ca_bundle.py`.

## Shim

Stesso modello degli shim attuali (CA bundle prima di tutto, `WELLNESS_DATA`, esecuzione
come CLI o import come modulo); cambia solo il glob:

```python
_cands = glob.glob(os.path.expanduser(
    "~/.claude/plugins/cache/wellness-agents/<plugin>/*/scripts/<nome>.py"))
```

Gli script del plugin che importano fratelli di altri plugin (es. `workout_fitbit` → `health`,
bot → `health` per `/sonno` e l'alzata) li trovano da soli nella cache (`_plugins.py`).

## `.env` del repo dati

| Chiave | Stato |
|---|---|
| `TELEGRAM_BOT_TOKEN` | migra nel portachiavi (`telegram_setup.py token-store --from-env --remove-from-env`), poi sparisce |
| `TELEGRAM_TOKEN_SOURCE=keychain`, `TELEGRAM_KEYCHAIN_ACCOUNT` | scritte dalla migrazione |
| `ALLOWED_CHAT_IDS`, `WORKOUT_PLAYER_URL`, `LUCIA_INSIGHTS` | restano |
| `WORKOUT_PLAYER_PAGES_PROJECT` | nuova: progetto Cloudflare Pages del player |
| `HEALTH_WEBHOOK_SECRET` | facoltativa (altrimenti vale `LUCIA_WEBHOOK_SECRET`) |
| `GOOGLE_HEALTH_PROJECT_NUMBER`, `HEALTH_WEBHOOK_URL`, `HEALTH_WEBHOOK_SUBSCRIBER_ID` | nuove, solo per `register_webhook.py` |
| `LUCIA_MORNING_MESSAGE`, `LUCIA_MORNING_LLM`, `LUCIA_KAULA_MODEL`, `XAI_API_KEY` | non più lette |

`config/hridaya.json` (facoltativo): `evening_message`, `bedtime` (altrimenti da
`config/insights.json` → `circadian`), `wake.earliest`, `wake.fallback`, … (default in
`hridaya/scripts/channel_config.py`). In `config/insights.json` non servono più
`quiet_hours`, `morning_push`, `circadian.evening_nudge_time`.

## Ordine dei passi (il sistema funziona a ogni passo)

1. Marketplace dalla cartella locale; installare `hridaya`, `dream-agent`; aggiornare
   `health`, `coach-longevita`, `tantra-guide`, `wellness-core`. La cache del vecchio
   `generalista` resta finché gli shim la usano.
2. Bot: fermarlo, migrare il token, `telegram_setup.py check` (niente 409, niente webhook),
   shim `telegram_bot.py` → hridaya, riavviarlo, `data/telegram/bot.log`.
   Il bot nuovo consuma `push.jsonl` e instrada nel cancello le righe di outbox non di risposta.
3. Shim della pipeline (`health_*`, `insights_engine`, `trends`) → health; `telegram_queue` → hridaya.
4. Gli altri shim della tabella.
5. launchd: togliere il buongiorno delle 07:30 (lo fa il cancello dopo l'alzata);
   spegnere il consiglio trend headless; daemon senza `process_telegram`.
6. In sessione: `/hridaya:servizio`.
7. Disinstallare `generalista`; togliere le copie locali rimaste (es. `apps/workout-player/`).
