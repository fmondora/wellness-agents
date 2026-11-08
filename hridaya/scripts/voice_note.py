#!/usr/bin/env python3.12
"""Vocali e meditazioni di Hṛdaya: testo scritto per l'orecchio → voce sintetica locale → Telegram.

Facoltativi: si accendono nel setup (skill `setup`, fase Vocali). Config in config/hridaya.json:

  "voice": {"enabled": true, "engine": "mlx-audio",
            "python": "<python con mlx-audio>", "model": "mlx-community/Voxtral-4B-TTS-2603-mlx-bf16",
            "voice": "it_male", "quant_bits": 8, "hf_home": "<cartella della cache di Hugging Face>",
            "method": "generate", "seed": null, "generate_kwargs": {}, "pause_s": 2.0,
            "voice_filter": "<filtri ffmpeg sul timbro, es. bass=g=3:f=160,treble=g=-4:f=5500>",
            "music_dirs": ["<cartelle con musica di sottofondo>"], "meditation_music": "drone"}
  più voci: "default_name": "maschile", "profiles": {"femminile": {<chiavi che cambiano: model, voice,
    method, seed, generate_kwargs, voice_filter, quant_bits>}}; chi manda sceglie con voice_profile.
  voce disegnata (Qwen3-TTS VoiceDesign): "model": "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16",
    "voice": "", "method": "generate_voice_design", "seed": 7,
    "generate_kwargs": {"language": "Italian", "instruct": "<descrizione della voce>"}
  oppure, per provare senza modelli: {"enabled": true, "engine": "say", "voice": "Luca"}  (macOS)

Il testo NON è il messaggio scritto letto ad alta voce: è la versione per l'orecchio che scrive lo
specialista (frasi brevi; riga vuota = pausa lunga; «...» = pausa breve; niente HTML né emoji).

L'invio è un lavoro in background (la sintesi dura da secondi a minuti): il server MCP crea il
lavoro e risponde subito; `run-job` sintetizza, spedisce, e se fallisce lo dice alla sessione con
un evento di sistema `voice_failed`. Stesso lavoro due volte = `duplicate`.

  voice_note.py discover                      modelli vocali e ambienti con mlx-audio già sul Mac
  voice_note.py check                         la configurazione regge? (python, ffmpeg, modello)
  voice_note.py make (-t TESTO | -f FILE) [-o out.ogg]   genera un vocale di prova (non lo manda)
  voice_note.py install [--venv DIR] [--model M] [--hf-home DIR]   ambiente nuovo + modello
  voice_note.py run-job ID                    (lo lancia il server MCP)
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import channel_config as cc  # noqa: E402

Runner = Callable[..., subprocess.CompletedProcess]

MAX_CHARS = 3000            # ~3-4 minuti: oltre, è una lezione da leggere, non un vocale
SYNTH_TIMEOUT_S = 300
DEFAULT_VENV = Path.home() / ".local" / "share" / "hridaya" / "voice-venv"
DEFAULT_MODEL = "mlx-community/Voxtral-4B-TTS-2603-mlx-bf16"
DEFAULT_VOICE = "it_male"
MIN_MLX_AUDIO = (0, 6)
PACKAGES = ["mlx-audio>=0.6", "soundfile", "numpy", "huggingface-hub"]
HERE = Path(__file__).resolve().parent
WORKER = HERE / "voice_worker.py"
KEEP_DAYS = 30              # vocali e meditazioni esportati: poi si potano
STALE_RUNNING_S = 1800      # un lavoro «running» da più di 30' è morto: si può rifare

# nomi di modelli vocali (TTS) riconoscibili nelle cache di Hugging Face
TTS_HINTS = ("tts", "voxtral", "kokoro", "omnivoice", "voxcpm", "chatterbox", "fish-audio", "audio8",
             "vibevoice", "pocket-tts", "kugelaudio", "openvoice", "csm", "dia-", "orpheus", "outetts",
             "spark-tts", "f5-tts", "xtts", "piper", "supertonic", "marvis")
NOT_TTS = ("whisper", "diarization", "tokenizer", "wavmark", "s3tokenizer")


class VoiceError(RuntimeError):
    pass


# --- configurazione ---------------------------------------------------------------------

def config(root: Path | None = None) -> dict | None:
    """La config dei vocali se accesi e ben formata, altrimenti None."""
    v = cc.rhythm(root).get("voice")
    return v if isinstance(v, dict) and v.get("enabled") is True else None


PROFILE_KEYS = ("model", "voice", "method", "seed", "generate_kwargs", "voice_filter", "quant_bits", "pause_s",
                "engine", "python")


def profiles(cfg: dict) -> list[str]:
    """Nomi delle voci disponibili: la principale per prima."""
    extra = cfg.get("profiles") if isinstance(cfg.get("profiles"), dict) else {}
    return [cfg.get("default_name") or "principale", *[k for k in extra if k != cfg.get("default_name")]]


def with_profile(cfg: dict, name: str | None) -> dict:
    """La config con la voce `name` (None o la principale = com'è)."""
    if not name or name == (cfg.get("default_name") or "principale"):
        return cfg
    prof = (cfg.get("profiles") or {}).get(name) if isinstance(cfg.get("profiles"), dict) else None
    if not isinstance(prof, dict):
        raise VoiceError(f"voce sconosciuta: {name!r} (disponibili: {', '.join(profiles(cfg))})")
    # le chiavi proprie di una voce non passano dalla principale all'altra (metodo, seed, timbro…)
    base = {k: v for k, v in cfg.items() if k not in ("method", "seed", "generate_kwargs", "voice_filter", "profiles")}
    return {**base, **{k: v for k, v in prof.items() if k in PROFILE_KEYS}}


def _hf_home(cfg: dict) -> Path:
    """La cache del modello: quella della config, altrimenti quella standard. MAI l'HF_HOME della
    shell: la sessione di servizio parte da launchd e non lo vede."""
    return Path(cfg["hf_home"]).expanduser() if cfg.get("hf_home") else Path.home() / ".cache" / "huggingface"


def _hf_env(cfg: dict) -> dict:
    env = dict(os.environ)
    env["HF_HOME"] = str(_hf_home(cfg))
    env["HF_HUB_OFFLINE"] = "1"   # il modello è già lì: niente rete a ogni vocale
    return env


def _ffmpeg() -> str:
    for c in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if c and Path(c).exists():
            return c
    raise VoiceError("ffmpeg non trovato (brew install ffmpeg)")


def model_dir(model: str, cfg: dict) -> Path:
    return _hf_home(cfg) / "hub" / ("models--" + model.replace("/", "--"))


def _run(run: Runner, cmd: list[str], what: str, timeout: float, **kw) -> subprocess.CompletedProcess:
    try:
        r = run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        raise VoiceError(f"{what}: oltre {int(timeout)} s")
    except OSError as e:
        raise VoiceError(f"{what}: {e}")
    if r.returncode != 0:
        raise VoiceError(f"{what}: {(r.stderr or '').strip()[-400:]}")
    return r


# --- il testo per la voce ---------------------------------------------------------------

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍⬀-⯿]")
_TAGS = re.compile(r"</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|a|span|tg-spoiler|tg-emoji|blockquote)\b[^>]*>",
                   re.I)
_SIGN = re.compile(r"^\s*[—–-]?\s*(?:Kaula|Coach Longevità|DreamAgent|Hṛdaya|Hridaya)\b\s*(?:·.*)?$", re.I)
_MD = [(re.compile(r"^\s*#{1,6}\s*"), ""), (re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+"), ""),
       (re.compile(r"\*\*|__|`"), "")]


def _clean_line(ln: str) -> str:
    for rx, rep in _MD:
        ln = rx.sub(rep, ln)
    return ln.strip()


def spoken(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Paragrafi da leggere: via tag di Telegram, entità, markdown, emoji, firme; riga vuota =
    paragrafo (pausa lunga); una riga senza punteggiatura finale prende un punto (pausa breve)."""
    t = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    t = html.unescape(_TAGS.sub("", t))
    t = _EMOJI.sub("", t)
    paras = []
    for block in re.split(r"\n\s*\n", t):
        lines = [_clean_line(ln) for ln in block.splitlines()]
        lines = [ln for ln in lines if ln and not _SIGN.match(ln)]
        lines = [ln if ln[-1] in ".!?…:;,»\"'" else ln + "." for ln in lines]
        p = re.sub(r"\s+", " ", " ".join(lines)).strip()
        if p:
            paras.append(p)
    if not paras:
        raise VoiceError("testo vuoto per il vocale")
    if sum(map(len, paras)) > max_chars:
        raise VoiceError(f"testo troppo lungo per un vocale (> {max_chars} caratteri): accorcialo o mandalo scritto")
    return paras


# --- sintesi ----------------------------------------------------------------------------

def _wav_duration(p: Path) -> float:
    with wave.open(str(p)) as w:
        return w.getnframes() / float(w.getframerate())


def _to_ogg(wav: Path, out: Path, run: Runner, cfg: dict | None = None) -> None:
    cfg = cfg or {}
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(run, [_ffmpeg(), "-loglevel", "error", "-y", "-i", str(wav), "-af", ",".join(
               x for x in (voice_filter(cfg), "loudnorm=I=-18:TP=-2:LRA=11") if x),
               "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "48k", "-application", "voip", str(out)],
         "ffmpeg", 180)
    if not out.exists():
        raise VoiceError("ffmpeg non ha scritto il file")


def _python(cfg: dict) -> Path:
    py = Path(cfg.get("python") or DEFAULT_VENV / "bin" / "python").expanduser()
    if not py.exists():
        raise VoiceError(f"python dei vocali non trovato: {py} (voice_note.py install o discover)")
    return py


def worker_spec(cfg: dict) -> dict:
    return {"model": cfg.get("model") or DEFAULT_MODEL, "voice": cfg.get("voice", DEFAULT_VOICE),
            "quant_bits": cfg.get("quant_bits", 8), "generate_kwargs": cfg.get("generate_kwargs") or {},
            "method": cfg.get("method") or "generate", "seed": cfg.get("seed"),
            "pause_s": cfg.get("pause_s", 2.0)}


def voice_filter(cfg: dict) -> str:
    """Filtro ffmpeg sulla voce (timbro): solo caratteri da catena di filtri, niente opzioni."""
    f = (cfg.get("voice_filter") or "").strip().strip(",")
    if f and not re.fullmatch(r"[a-z0-9_=:|.,\-]+", f):
        raise VoiceError(f"voice_filter non valido: {f!r}")
    return f


def run_worker(script: Path, spec: dict, cfg: dict, run: Runner, timeout: float) -> dict:
    r = _run(run, [str(_python(cfg)), str(script)], "sintesi", timeout, input=json.dumps(spec), env=_hf_env(cfg))
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise VoiceError(f"risposta inattesa dal worker: {r.stdout[-200:]!r}")


def _synth_say(paras: list[str], wav: Path, cfg: dict, run: Runner) -> None:
    pause = int(cfg.get("pause_s", 2.0) * 1000)
    txt = wav.with_suffix(".txt")
    txt.write_text(f" [[slnc {pause}]] ".join(paras), encoding="utf-8")
    aiff = wav.with_suffix(".aiff")
    _run(run, ["say", "-v", cfg.get("voice") or "Alice", "-o", str(aiff), "-f", str(txt)], "say", 300)
    _run(run, [_ffmpeg(), "-loglevel", "error", "-y", "-i", str(aiff), str(wav)], "ffmpeg", 120)


def fake_mode() -> bool:
    """Test: niente modelli né ffmpeg. Vale solo col trasporto finto (mai verso Telegram vero)."""
    return bool(os.environ.get("HRIDAYA_VOICE_FAKE") and os.environ.get("HRIDAYA_TRANSPORT_LOG"))


def synth(text: str, out: Path, cfg: dict, run: Runner = subprocess.run) -> dict:
    """Testo per l'orecchio → `out` (.ogg Opus). → {"path", "duration"}"""
    paras = spoken(text)
    if fake_mode():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"OggS-fake")
        return {"path": str(out), "duration": round(sum(map(len, paras)) / 14, 1)}
    engine = cfg.get("engine", "mlx-audio")
    with tempfile.TemporaryDirectory(prefix="hridaya-voce-") as d:
        wav = Path(d) / "voce.wav"
        if engine == "mlx-audio":
            res = run_worker(WORKER, {**worker_spec(cfg), "paragraphs": paras, "lead_s": 0.8, "tail_s": 3.0,
                                      "out": str(wav)}, cfg, run, cfg.get("timeout_s", SYNTH_TIMEOUT_S))
            dur = float(res.get("duration") or 0)
        elif engine == "say":
            _synth_say(paras, wav, cfg, run)
            dur = 0.0
        else:
            raise VoiceError(f"motore sconosciuto: {engine} (mlx-audio | say)")
        if not dur and wav.exists():
            dur = _wav_duration(wav)
        _to_ogg(wav, out, run, cfg)
    return {"path": str(out), "duration": round(dur, 1)}


def slug(s: str, default: str = "vocale") -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or default


def export_dir(kind: str, root: Path | None = None) -> Path:
    sub = "meditazioni" if kind == "meditation" else "voce"
    return (root or cc.data_root()).resolve() / "data" / "exports" / sub


def prune(d: Path, days: int = KEEP_DAYS) -> int:
    """Via i file esportati più vecchi di `days` giorni (sono rigenerabili, e pesano)."""
    if not d.is_dir():
        return 0
    cut, n = time.time() - days * 86400, 0
    for f in d.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cut:
                f.unlink()
                n += 1
        except OSError:
            pass
    return n


# --- lavori in background ---------------------------------------------------------------

def jobs_dir(root: Path | None = None) -> Path:
    return (root or cc.data_root()).resolve() / "data" / "hridaya" / "voice_jobs"


def job_path(jid: str, root: Path | None = None) -> Path:
    if not re.fullmatch(r"[0-9a-f]{16}", jid or ""):
        raise VoiceError(f"id di lavoro non valido: {jid!r}")
    return jobs_dir(root) / f"{jid}.json"


def read_job(jid: str, root: Path | None = None) -> dict | None:
    try:
        return json.loads(job_path(jid, root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_job(job: dict, root: Path | None = None) -> None:
    p = job_path(job["id"], root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def create_job(kind: str, key: str, payload: dict, spawn: Callable[..., Any] = subprocess.Popen,
               root: Path | None = None) -> dict:
    """Registra e lancia un lavoro. `key` decide i doppioni: già spedito → duplicate; in corso (processo
    vivo) → running. Un lavoro col processo morto si rifà."""
    jid = hashlib.sha1(f"{kind}\n{key}".encode()).hexdigest()[:16]
    old = read_job(jid, root)
    if old and old.get("status") == "sent":
        return {"status": "duplicate", "job": jid, "file": old.get("file")}
    if old and old.get("status") in ("queued", "running", "waiting_wake"):
        if _alive(old.get("pid")) or (not old.get("pid") and time.time() - old.get("updated_ts", 0) < 120):
            return {"status": "running", "job": jid}
    base = (root or cc.data_root()).resolve()
    prune(jobs_dir(root))
    job = {"id": jid, "kind": kind, **payload, "status": "queued",
           "created_at": datetime.now(timezone.utc).isoformat(), "updated_ts": time.time()}
    write_job(job, root)
    cmd = [sys.executable, str(Path(__file__).resolve()), "run-job", jid]
    if Path("/usr/bin/caffeinate").exists() and not fake_mode():
        cmd = ["/usr/bin/caffeinate", "-i", *cmd]          # il Mac non dorme a metà montaggio
    with open(job_path(jid, root).with_suffix(".log"), "a", encoding="utf-8") as f:
        p = spawn(cmd, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                  cwd=str(base), env={**os.environ, "WELLNESS_DATA": str(base)})
    if hasattr(p, "wait"):                                  # raccolto quando finisce: niente zombie
        threading.Thread(target=p.wait, daemon=True).start()
    return {"status": "preparing", "job": jid}


def _multipart(token: str, method: str, fields: dict, files: dict) -> dict:
    if os.environ.get("HRIDAYA_TRANSPORT_LOG"):      # test: trasporto finto
        with open(os.environ["HRIDAYA_TRANSPORT_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "multipart", "method": method,
                                "params": {**fields, "_files": {k: str(v) for k, v in files.items()}}},
                               ensure_ascii=False) + "\n")
        return {"ok": True, "result": {"message_id": 1}}
    import tg_transport as tt
    return tt.multipart(token, method, fields, files)


def _send(method: str, fields: dict, files: dict) -> None:
    """Spedisce; con un 400 sull'HTML della caption riprova senza formattazione."""
    import tg_transport as tt
    cc.apply_ca_bundle()
    token = cc.bot_token(cc.load_env())
    if not token:
        raise VoiceError("manca il token del bot")
    for attempt in range(2):
        try:
            _multipart(token, method, fields, files)
            return
        except tt.TelegramError as e:
            if e.code == 400 and fields.get("parse_mode") and "entit" in str(e).lower():
                fields = {k: v for k, v in fields.items() if k != "parse_mode"}
                if fields.get("caption"):
                    fields["caption"] = html.unescape(re.sub(r"<[^>]+>", "", fields["caption"]))
                continue
            if tt.is_permanent(e) or attempt:
                raise
        except OSError:
            if attempt:
                raise
        time.sleep(10)


WAKE_WAIT_S = 14 * 3600


def _wait_day(job: dict) -> None:
    """Il file è pronto ma è scattato il silenzio notturno: aspetta l'alzata (il processo resta vivo,
    il lavoro dice «waiting_wake»). Oltre 14 ore, rinuncia."""
    import push_gate as pg
    t0 = time.time()
    while pg.is_silent(datetime.now(cc.tz()), cc.rhythm(), pg.load_state()):
        if time.time() - t0 > WAKE_WAIT_S:
            raise VoiceError("silenzio notturno troppo lungo: non spedito")
        job.update(status="waiting_wake", updated_ts=time.time())
        write_job(job)
        time.sleep(60)
    if job.get("status") == "waiting_wake":
        job.update(status="running", updated_ts=time.time())
        write_job(job)


def run_job(jid: str, run: Runner = subprocess.run) -> dict:
    import telegram_queue as tq
    job = read_job(jid)
    if not job:
        raise VoiceError(f"lavoro {jid} non trovato")
    if job.get("status") == "sent":
        return job
    job.update(status="queued", pid=os.getpid(), updated_ts=time.time())
    write_job(job)
    lock = open(jobs_dir() / ".synth.lock", "w")
    try:
        while True:                                        # un lavoro alla volta: il modello pesa 8 GB
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                job["updated_ts"] = time.time()
                write_job(job)
                time.sleep(5)
        job.update(status="running", updated_ts=time.time())
        write_job(job)
        cfg = config()
        if not cfg:
            raise VoiceError("vocali spenti")
        cfg = with_profile(cfg, job.get("voice_profile"))
        stamp = datetime.now(cc.tz()).strftime("%Y-%m-%d-%H%M%S")
        out_d = export_dir(job["kind"])
        prune(out_d)
        fields: dict[str, Any] = {"chat_id": job["chat_id"]}
        if job.get("practice"):                            # «▶️ Inizia» / «⏹ Fine» sotto la pratica
            import practice
            fields["reply_markup"] = practice.create(job.get("title") or "Pratica",
                                                     "meditation" if job["kind"] == "meditation" else "voice",
                                                     pid=jid)[1]
        if job.get("caption"):
            fields.update(caption=job["caption"][:1024], parse_mode="HTML")
        def send(method: str, files: dict) -> None:
            _wait_day(job)
            _send(method, fields, files)

        if job["kind"] == "meditation":
            import meditation
            ext = ".ogg" if job.get("as_voice") else ".m4a"
            out = out_d / f"{stamp}-{slug(job.get('title') or '', 'meditazione')}{ext}"
            res = meditation.build(job["script"], out, cfg, job.get("music"), run=run)
            fields["duration"] = int(round(res["duration"]))
            job["music_used"] = res.get("music")
            if job.get("as_voice"):
                send("sendVoice", {"voice": Path(res["path"])})
            else:
                fields.update(title=job.get("title") or "Meditazione", performer=job.get("performer") or "Hṛdaya")
                send("sendAudio", {"audio": Path(res["path"])})
        else:
            out = out_d / f"{stamp}-{slug(job.get('title') or '')}.ogg"
            res = synth(job["text"], out, cfg, run=run)
            fields["duration"] = int(round(res["duration"]))
            send("sendVoice", {"voice": Path(res["path"])})
        job.update(status="sent", file=Path(res["path"]).name, duration=res["duration"],
                   sent_at=datetime.now(timezone.utc).isoformat(), updated_ts=time.time())
        if res.get("shifted"):
            job["shifted"] = res["shifted"]
        write_job(job)
        return job
    except Exception as e:  # noqa: BLE001 — qualunque errore va detto alla sessione
        job.update(status="failed", error=str(e)[:500], updated_ts=time.time())
        write_job(job)
        what = "la meditazione" if job["kind"] == "meditation" else "il vocale"
        why = re.sub(r"(/[^\s:'\"]+)+", "…", str(e))[:200]       # niente percorsi nella coda
        tq.enqueue_system("voice_failed", f"Non sono riuscito a mandare {what} «{job.get('title') or ''}»: {why}",
                          {"job": jid}, dedup_key=f"voice_failed:{jid}:{job.get('created_at')}")
        raise
    finally:
        lock.close()


# --- scoperta di ciò che c'è già --------------------------------------------------------

def _hf_hubs() -> list[Path]:
    home = Path.home()
    cands = [Path(os.environ["HF_HOME"]) if os.environ.get("HF_HOME") else None,
             home / ".cache" / "huggingface", home / "models" / "huggingface", home / "huggingface",
             home / ".local" / "share" / "huggingface"]
    seen, out = set(), []
    for c in cands:
        if c and (c / "hub").is_dir():
            r = (c / "hub").resolve()
            if r not in seen:
                seen.add(r)
                out.append(c)
    return out


def _du(p: Path) -> int:
    """Byte dei file del modello (seguendo i symlink, ognuno una volta)."""
    total, seen = 0, set()
    for f in p.rglob("*"):
        try:
            st = f.stat()
        except OSError:
            continue
        if f.is_file() and (st.st_dev, st.st_ino) not in seen:
            seen.add((st.st_dev, st.st_ino))
            total += st.st_size
    return total


def find_models() -> list[dict]:
    out = []
    for hf in _hf_hubs():
        for d in sorted((hf / "hub").glob("models--*")):
            name = d.name[len("models--"):].replace("--", "/", 1)
            low = name.lower()
            if not any(h in low for h in TTS_HINTS) or any(n in low for n in NOT_TTS):
                continue
            if not any((d / "snapshots").glob("*/*")):
                continue                                    # download interrotto
            out.append({"model": name, "hf_home": str(hf), "size_gb": round(_du(d) / 1e9, 1),
                        "mlx": "mlx" in low})
    return out


SKIP_DIRS = {"node_modules", ".git", "__pycache__", "Library", ".Trash", "snapshots", "blobs", "site-packages"}


def _ver(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s or "")[:3]) or (0,)


def find_envs(roots: list[Path] | None = None, max_depth: int = 5) -> list[dict]:
    """Ambienti Python (venv) che hanno già mlx-audio, dal più recente; ok=False sotto la 0.6."""
    home = Path.home()
    roots = roots or [home / ".local" / "share", home / "wip", home / "venvs", home / ".venvs", home / "projects"]
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        base = len(root.parts)
        for dirpath, dirs, files in os.walk(root):
            if "pyvenv.cfg" in files:
                p = Path(dirpath)
                hit = list(p.glob("lib/python3*/site-packages/mlx_audio"))
                if hit and (p / "bin" / "python").exists():
                    ver = ""
                    meta = list(p.glob("lib/python3*/site-packages/mlx_audio-*.dist-info"))
                    if meta:
                        ver = meta[0].name.split("-")[1].removesuffix(".dist")
                    found.append({"python": str(p / "bin" / "python"), "mlx_audio": ver,
                                  "ok": _ver(ver)[:2] >= MIN_MLX_AUDIO})
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                       and (not d.startswith(".") or d.startswith(".venv") or d == ".local")]
            if len(Path(dirpath).parts) - base >= max_depth:
                dirs[:] = []
    return sorted(found, key=lambda e: _ver(e["mlx_audio"]), reverse=True)


def discover() -> dict:
    return {"models": find_models(), "envs": find_envs(), "ffmpeg": bool(shutil.which("ffmpeg") or
            Path("/opt/homebrew/bin/ffmpeg").exists()), "apple_silicon": os.uname().machine == "arm64"}


# --- verifica e installazione -----------------------------------------------------------

def check(cfg: dict | None, run: Runner = subprocess.run) -> list[str]:
    """Problemi della configurazione (vuota = pronta)."""
    if not cfg:
        return ["vocali spenti: manca \"voice\": {\"enabled\": true, …} in config/hridaya.json"]
    probs = []
    try:
        _ffmpeg()
    except VoiceError as e:
        probs.append(str(e))
    engine = cfg.get("engine", "mlx-audio")
    if engine == "say":
        try:
            r = _run(run, ["say", "-v", "?"], "say", 30)
            if not re.search(rf"^{re.escape(cfg.get('voice') or 'Alice')}\s", r.stdout, re.M):
                probs.append(f"voce di say non trovata: {cfg.get('voice')}")
        except VoiceError as e:
            probs.append(str(e))
        return probs
    if engine != "mlx-audio":
        return probs + [f"motore sconosciuto: {engine}"]
    try:
        _run(run, [str(_python(cfg)), "-c", "import mlx_audio, soundfile, numpy"], "import", 120)
    except VoiceError as e:
        probs.append(f"ambiente dei vocali: {e}")
    md = model_dir(cfg.get("model") or DEFAULT_MODEL, cfg)
    if not any((md / "snapshots").glob("*/*")):
        probs.append(f"modello non scaricato: {md}")
    env_hf = os.environ.get("HF_HOME")
    if not cfg.get("hf_home") and env_hf and Path(env_hf).expanduser() != _hf_home(cfg):
        probs.append(f"HF_HOME della shell ({env_hf}) non arriva al servizio (launchd): mettilo in voice.hf_home")
    return probs


def install(venv: Path, model: str, hf_home: str | None, run: Runner = subprocess.run) -> Path:
    py = venv / "bin" / "python"
    if not py.exists():
        venv.parent.mkdir(parents=True, exist_ok=True)
        run([sys.executable, "-m", "venv", str(venv)], check=True)
    run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
    run([str(py), "-m", "pip", "install", "-q", *PACKAGES], check=True)
    env = _hf_env({"hf_home": hf_home} if hf_home else {})
    env.pop("HF_HUB_OFFLINE", None)
    run([str(py), "-c", f"from huggingface_hub import snapshot_download; snapshot_download({model!r})"],
        check=True, env=env)
    return py


def main() -> int:
    ap = argparse.ArgumentParser(description="Vocali di Hṛdaya")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover")
    sub.add_parser("check")
    m = sub.add_parser("make")
    m.add_argument("-t", "--text")
    m.add_argument("-f", "--file")
    m.add_argument("-o", "--out")
    m.add_argument("-p", "--profile", help="voce (profilo) da usare")
    i = sub.add_parser("install")
    i.add_argument("--venv", default=str(DEFAULT_VENV))
    i.add_argument("--model", default=DEFAULT_MODEL)
    i.add_argument("--hf-home")
    j = sub.add_parser("run-job")
    j.add_argument("id")
    a = ap.parse_args()
    if a.cmd == "discover":
        print(json.dumps(discover(), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "check":
        cfg = config()
        probs = []
        for name in (profiles(cfg) if cfg else [None]):
            probs += [f"[{name}] {p}" if name else p for p in check(with_profile(cfg, name) if cfg else None)]
        print("\n".join(probs) if probs else f"vocali pronti ({', '.join(profiles(cfg))})")
        return 1 if probs else 0
    if a.cmd == "install":
        py = install(Path(a.venv).expanduser(), a.model, a.hf_home)
        print(f"pronto: python {py}, modello {a.model}")
        return 0
    if a.cmd == "run-job":
        try:
            job = run_job(a.id)
        except Exception as e:  # noqa: BLE001
            print(f"[{datetime.now():%H:%M:%S}] {a.id} fallito: {e}", flush=True)
            return 2
        print(f"[{datetime.now():%H:%M:%S}] {a.id} {job['status']}: {job.get('file')}", flush=True)
        return 0
    cfg = config()
    if not cfg:
        print("vocali spenti (config/hridaya.json → voice.enabled)", file=sys.stderr)
        return 1
    text = a.text if a.text else Path(a.file).read_text(encoding="utf-8") if a.file else sys.stdin.read()
    try:
        out = Path(a.out) if a.out else export_dir("voice") / f"{datetime.now(cc.tz()):%Y-%m-%d-%H%M%S}-prova.ogg"
        r = synth(text, out, with_profile(cfg, a.profile))
    except VoiceError as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
