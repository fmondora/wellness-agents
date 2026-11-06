#!/usr/bin/env python3.12
"""Configurazione del canale di Hṛdaya: repo dati, segreti, ritmo della giornata.

Tutto ciò che è personale vive nel repo dati (cwd o WELLNESS_DATA):
  .env                   ALLOWED_CHAT_IDS, WORKOUT_PLAYER_URL, (TELEGRAM_BOT_TOKEN solo come fallback)
  portachiavi macOS      il token del bot (servizio `wellness-agents.telegram`,
                         account TELEGRAM_KEYCHAIN_ACCOUNT del .env o nome della cartella del repo dati)
  config/hridaya.json    ritmo: messaggio della sera, ora di letto, alzata (facoltativo, default sotto)
  config/insights.json   se `bedtime` non è dato: ora di letto = target_wake − cicli·durata − latenza
                         (stessa regola di circadian_plan di DreamAgent)

Ordine del token: variabile d'ambiente → portachiavi (se TELEGRAM_TOKEN_SOURCE=keychain
o se il .env non ce l'ha) → .env.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

KEYCHAIN_SERVICE = "wellness-agents.telegram"

DEFAULTS: dict = {
    "evening_message": "22:00",          # la sessione manda la meditazione del Kaula + ora di letto
    "evening_fallback_delay_min": 10,    # senza sessione: fallback deterministico dopo tanti minuti
    "bedtime": None,                     # None → da config/insights.json (circadian)
    "wake_grace_min": 15,                # alzata vista, sessione attiva: attesa del suo messaggio
    "merge_window_s": 60,                # push arrivati entro questa finestra escono in un messaggio
    "session_heartbeat_max_age_s": 150,  # oltre, la sessione è considerata spenta
    "wake": {
        "earliest": "05:00",       # pavimento: mai un'alzata prima di quest'ora
        "watch_from": "04:30",     # da quando si scaricano i dati al minuto
        "fallback": "09:30",       # alzata non vista entro quest'ora → messaggio comunque
        "fallback_max": "11:30",   # se i dati dicono che dorme ancora, si rimanda fino a qui
        "late_cutoff": "14:00",    # dopo, il messaggio del mattino non parte più (bot fermo al mattino)
        "fetch_every_min": 5,
        # con la sessione di sonno del wearable chiusa: movimento dopo la fine
        "session_window_min": 10, "session_steps": 30,
        # senza sessione: blocco quieto prima, movimento che dura dopo
        "quiet_block_min": 120, "quiet_max_steps": 60,
        "confirm_min": 20, "confirm_steps": 100, "confirm_active_min": 5,
        "confirm_tail_active_min": 2, "hr_rise_bpm": 5,
        # dorme ancora? (rinvio del fallback)
        "asleep_still_min": 45, "asleep_fresh_min": 20,
    },
}


def data_root() -> Path:
    return Path(os.environ.get("WELLNESS_DATA") or Path.cwd())


def tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("WELLNESS_TZ", "Europe/Rome"))


def is_data_repo(root: Path | None = None) -> bool:
    return ((root or data_root()) / "data" / "profile.json").exists()


def load_env(root: Path | None = None) -> dict[str, str]:
    env: dict[str, str] = {}
    path = (root or data_root()) / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def set_env_value(key: str, value: str | None, root: Path | None = None) -> None:
    """Imposta (o toglie, con value=None) una riga KEY=... nel .env, preservando il resto."""
    path = (root or data_root()) / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, found = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key and not line.lstrip().startswith("#"):
            found = True
            if value is not None:
                out.append(f"{key}={value}")
            continue
        out.append(line)
    if not found and value is not None:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# --- portachiavi macOS --------------------------------------------------------

Runner = Callable[..., subprocess.CompletedProcess]


def keychain_account(env: dict[str, str] | None = None, root: Path | None = None) -> str:
    env = env if env is not None else load_env(root)
    return env.get("TELEGRAM_KEYCHAIN_ACCOUNT") or (root or data_root()).resolve().name


def keychain_get(account: str, runner: Runner = subprocess.run) -> str | None:
    try:
        r = runner(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
                   capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def keychain_set(account: str, token: str, runner: Runner = subprocess.run) -> bool:
    """Salva (o aggiorna, -U) il token nel portachiavi di login.

    Il token NON va in argv (sarebbe visibile in `ps`): `-w` ultimo e senza valore fa
    chiedere a `security` la password, che legge da stdin (password + conferma).
    """
    if "\n" in token or "\r" in token:
        return False
    try:
        r = runner(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", account,
                    "-l", "Telegram bot (wellness-agents)", "-w"],
                   input=f"{token}\n{token}\n", capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def bot_token(env: dict[str, str] | None = None, root: Path | None = None,
              runner: Runner = subprocess.run) -> str:
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return os.environ["TELEGRAM_BOT_TOKEN"]
    env = env if env is not None else load_env(root)
    from_env = env.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_TOKEN") or ""
    if env.get("TELEGRAM_TOKEN_SOURCE", "").lower() == "keychain" or not from_env:
        tok = keychain_get(keychain_account(env, root), runner)
        if tok:
            return tok
    return from_env


def allowed_chat_ids(env: dict[str, str] | None = None) -> set[int]:
    env = env if env is not None else load_env()
    out = set()
    for part in env.get("ALLOWED_CHAT_IDS", "").replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return out


def primary_chat_id(env: dict[str, str] | None = None) -> int | None:
    env = env if env is not None else load_env()
    for part in env.get("ALLOWED_CHAT_IDS", "").replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            return int(part)
    return None


def apply_ca_bundle(root: Path | None = None) -> None:
    """Rete con ispezione TLS: se il repo dati ha config/ca-bundle.pem, Python lo usa."""
    pem = (root or data_root()) / "config" / "ca-bundle.pem"
    if pem.exists():
        os.environ.setdefault("SSL_CERT_FILE", str(pem))
        os.environ.setdefault("REQUESTS_CA_BUNDLE", str(pem))


# --- ritmo della giornata -------------------------------------------------------

def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif not str(k).startswith("_"):
            out[k] = v
    return out


def _hm(x: str) -> int:
    h, m = x.split(":")
    return int(h) * 60 + int(m)


def _fmt(minutes: int) -> str:
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def derived_bedtime(root: Path | None = None) -> tuple[str, str | None]:
    """(ora di letto, sveglia target) da config/insights.json → circadian; default 22:30."""
    try:
        c = json.loads(((root or data_root()) / "config" / "insights.json").read_text(encoding="utf-8"))
        c = c.get("circadian") or {}
        wake = c.get("target_wake", "06:00")
        cycles = (c.get("cycles_options") or [5])[0]
        bed = _hm(wake) - cycles * c.get("cycle_min", 90) - c.get("onset_latency_min", 15)
        return _fmt(bed), wake
    except (OSError, ValueError, KeyError, TypeError):
        return "22:30", None


def rhythm(root: Path | None = None) -> dict:
    root = root or data_root()
    over = {}
    f = root / "config" / "hridaya.json"
    if f.exists():
        try:
            over = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            over = {}
    cfg = _merge(DEFAULTS, over)
    bed, wake = derived_bedtime(root)
    cfg["target_wake"] = wake
    if not cfg.get("bedtime"):
        cfg["bedtime"] = bed
    return cfg


# --- confini dei file che possono uscire sul canale ------------------------------------
#
# Allowlist stretta per uso (difesa dal prompt injection: nel repo dati ci sono anche token
# OAuth, chiavi, service account, log). Un path si risolve (symlink compresi) e deve cadere
# in una delle cartelle ammesse per quell'uso; i nomi sensibili sono rifiutati comunque.
#
#   file    (telegram_send_file, spec delle schede): data/coach-longevita/daily/, data/reports/,
#           data/reviews/, data/dream-agent/reviews/, data/exports/
#   image   (foto delle schede): le stesse + asset dei plugin (coach-longevita/assets/),
#           solo .png .jpg .jpeg .webp .gif
#   player  (telegram_send_player): data/coach-longevita/daily/*.player.json

import fnmatch  # noqa: E402

FILE_DIRS = ("data/coach-longevita/daily", "data/reports", "data/reviews",
             "data/dream-agent/reviews", "data/exports")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DENY = ("*.key", "*.pem", "*token*.json", "*credentials*", "service-account*.json",
        ".env*", "*.log", "*secret*", "id_rsa*", "*.p12")


class PathNotAllowed(ValueError):
    pass


def allowed_roots(kind: str = "file", root: Path | None = None) -> list[Path]:
    base = (root or data_root()).resolve()
    if kind == "player":
        return [base / "data" / "coach-longevita" / "daily"]
    roots = [base / d for d in FILE_DIRS]
    if kind == "image":
        try:
            from _plugins import plugin_scripts
            d = plugin_scripts("coach-longevita")
            if d:
                roots.append((d.parent / "assets").resolve())
        except Exception:  # noqa: BLE001
            pass
    return roots


def safe_path(p: str | Path, base: Path | None = None, kind: str = "file", dir_ok: bool = False) -> Path:
    """Path risolto e ammesso per `kind` (file | image | player), o PathNotAllowed."""
    q = Path(p).expanduser()
    q = q if q.is_absolute() else (base or data_root()) / q
    r = q.resolve()
    names = {q.name.lower(), r.name.lower()}
    if any(fnmatch.fnmatch(n, pat) for n in names for pat in DENY):
        raise PathNotAllowed(f"{p}: nome riservato (segreti, chiavi, log): non esce sul canale")
    if not any(r == a or r.is_relative_to(a) for a in allowed_roots(kind)):
        raise PathNotAllowed(f"{p}: fuori dalle cartelle ammesse per {kind} ("
                             + ", ".join(FILE_DIRS if kind != "player" else ("data/coach-longevita/daily",))
                             + (", asset dei plugin" if kind == "image" else "") + ")")
    if r.is_dir() and not dir_ok:
        raise PathNotAllowed(f"{p}: è una cartella")
    if kind == "image" and not r.is_dir() and r.suffix.lower() not in IMAGE_EXT:
        raise PathNotAllowed(f"{p}: non è un'immagine ({', '.join(sorted(IMAGE_EXT))})")
    if kind == "player" and not r.name.endswith(".player.json"):
        raise PathNotAllowed(f"{p}: non è un player.json")
    return r


def safe_card(steps: list[dict], base: Path) -> list[dict]:
    """Scheda con le foto risolte e verificate (path assoluti)."""
    if not isinstance(steps, list):
        raise PathNotAllowed("la scheda deve essere una lista di passi")
    out = []
    for st in steps:
        if not isinstance(st, dict):
            raise PathNotAllowed("passo della scheda non valido")
        if "photos" in st:
            st = {**st, "photos": [str(safe_path(ph, base=base, kind="image")) for ph in st["photos"]]}
        out.append(st)
    return out
