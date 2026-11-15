#!/usr/bin/env python3.12
"""Canzoni cantate: testo (scritto dal Kaula o da chi parla) + stile → ACE-Step in locale → brano m4a.

Facoltative: servono ACE-Step 1.5 installato sul Mac (repo con il suo ambiente, `uv sync`) e la
config in config/hridaya.json:

  "song": {"enabled": true, "acestep_dir": "<cartella del repo ACE-Step-1.5>",
           "hf_home": "<cache di Hugging Face>", "dit": "acestep-v15-turbo",
           "lm": "acestep-5Hz-lm-1.7B", "timeout_s": 1800}

Il testo usa i tag di sezione di ACE-Step ([Intro], [Verse 1], [Chorus], [Bridge], [Outro], con
indicazioni facoltative dopo il trattino: «[Bridge - almost whispered]»). Lo stile è una riga in
inglese (strumenti, voce, atmosfera, tempo): i nomi di artisti non servono, si descrive il suono.

L'invio è un lavoro in background come le meditazioni (voice_note.py run-job, kind «song»): il
worker gira nel Python di ACE-Step, poi ffmpeg fa l'm4a in data/exports/canzoni/.

    song.py check                       la configurazione regge?
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import channel_config as cc  # noqa: E402
import voice_note as vn  # noqa: E402

WORKER = Path(__file__).resolve().parent / "song_worker.py"
MAX_LYRICS = 4000
MAX_STYLE = 500
MIN_S, MAX_S, DEFAULT_S = 30, 480, 240
LANGS = {"it", "en", "sa", "hi", "es", "fr", "de", "pt", "unknown"}
SECTION = re.compile(r"^\s*\[(intro|verse|chorus|pre-chorus|bridge|outro|hook|interlude|instrumental)"
                     r"(\s*\d+)?\b[^\]]*\]\s*$", re.I | re.M)
KEY = re.compile(r"([A-Ga-g])\s*([#b♯♭]?)\s*(major|maj|minor|min|m)?", re.I)


class SongError(vn.VoiceError):
    pass


def normalize_key(key: str | None) -> str:
    """«Am» → «A minor», «d» → «D major», «F♯ minor» resta: le 70 forme che ACE-Step conosce."""
    if not key or not key.strip():
        return ""
    m = KEY.fullmatch(key.strip())
    if not m:
        raise SongError("key: es. «D major», «A minor», «F# minor»")
    note, acc, mode = m.group(1).upper(), m.group(2), (m.group(3) or "").lower()
    if mode == "m" and m.group(3) == "M":       # «AM»: maiuscolo ambiguo, vale maggiore
        mode = "major"
    mode = "minor" if mode in ("m", "min", "minor") else "major"
    return f"{note}{acc} {mode}"


def config(root: Path | None = None) -> dict | None:
    root = root or cc.data_root()
    try:
        cfg = json.loads((root / "config" / "hridaya.json").read_text(encoding="utf-8")).get("song")
    except (OSError, ValueError, AttributeError):
        return None
    return cfg if isinstance(cfg, dict) and cfg.get("enabled") else None


def validate(lyrics: str, style: str, duration_s: int | None = None, bpm: int | None = None,
             key: str | None = None, language: str | None = None) -> dict:
    """Parametri puliti o SongError."""
    lyrics, style = (lyrics or "").strip(), " ".join((style or "").split())
    if not lyrics:
        raise SongError("lyrics: il testo da cantare")
    if len(lyrics) > MAX_LYRICS:
        raise SongError(f"lyrics: al massimo {MAX_LYRICS} caratteri")
    if not SECTION.search(lyrics):
        raise SongError("lyrics: servono i tag di sezione ([Verse 1], [Chorus], [Bridge]…)")
    if not style:
        raise SongError("style: una riga che descrive il suono (voce, strumenti, atmosfera)")
    if len(style) > MAX_STYLE:
        raise SongError(f"style: al massimo {MAX_STYLE} caratteri")
    d = DEFAULT_S if duration_s is None else duration_s
    if not (isinstance(d, int) and not isinstance(d, bool) and MIN_S <= d <= MAX_S):
        raise SongError(f"duration_s: da {MIN_S} a {MAX_S} secondi")
    if bpm is not None and not (isinstance(bpm, int) and not isinstance(bpm, bool) and 40 <= bpm <= 200):
        raise SongError("bpm: da 40 a 200")
    key = normalize_key(key)
    lang = (language or "it").strip().lower()
    if lang not in LANGS:
        raise SongError(f"language: {', '.join(sorted(LANGS))}")
    return {"lyrics": lyrics, "style": style, "duration_s": d, "bpm": bpm, "key": key, "language": lang}


def _python(cfg: dict) -> Path:
    d = Path(cfg.get("acestep_dir") or "").expanduser()
    py = d / ".venv" / "bin" / "python"
    if not d.is_dir() or not py.exists():
        raise SongError(f"ACE-Step non trovato: {d} (serve il repo con l'ambiente, `uv sync`)")
    return py


def build(params: dict, out: Path, cfg: dict, run: vn.Runner = subprocess.run, seed: int = -1) -> dict:
    """Testo + stile → `out` (.m4a) + `out.json` (testo, stile, seed: per rifarla). → {"path", "duration", "seed"}"""
    p = validate(**params)
    out.parent.mkdir(parents=True, exist_ok=True)
    if vn.fake_mode():
        out.write_bytes(b"m4a-fake")
        res = {"path": str(out), "duration": float(p["duration_s"]), "seed": seed}
        _sidecar(out, p, res)
        return res
    py = _python(cfg)
    with tempfile.TemporaryDirectory(prefix="hridaya-song-") as d:
        spec = {**p, "repo": str(Path(cfg["acestep_dir"]).expanduser()), "out_dir": d, "seed": seed,
                "dit": cfg.get("dit") or "acestep-v15-turbo", "lm": cfg.get("lm") or "acestep-5Hz-lm-1.7B"}
        env = vn._hf_env(cfg)
        env.pop("HF_HUB_OFFLINE", None)          # al primo giro ACE-Step può completare i checkpoint
        env.setdefault("HF_HUB_DISABLE_XET", "1")   # il trasferimento xet si pianta: download HTTP classico
        r = vn._run(run, [str(py), str(WORKER)], "canzone", cfg.get("timeout_s", 1800),
                    input=json.dumps(spec), env=env, cwd=spec["repo"])
        lines = [x.strip() for x in (r.stdout or "").splitlines() if "SONG_RESULT " in x]
        try:
            res = json.loads(lines[-1].split("SONG_RESULT ", 1)[1])
        except (IndexError, ValueError):
            raise SongError(f"risposta inattesa da ACE-Step: {(r.stdout or '')[-200:]!r}") from None
        if not res.get("ok") or not res.get("path"):
            raise SongError(f"ACE-Step: {res.get('error') or 'nessun file'}")
        vn._run(run, [vn._ffmpeg(), "-loglevel", "error", "-y", "-i", res["path"], "-c:a", "aac", "-b:a", "192k",
                      str(out)], "ffmpeg", 300)
    if not out.exists():
        raise SongError("ffmpeg non ha scritto il file")
    out_res = {"path": str(out), "duration": float(res.get("duration") or p["duration_s"]),
               "seed": res.get("seed", seed)}
    _sidecar(out, p, out_res)
    return out_res


def _sidecar(out: Path, p: dict, res: dict) -> None:
    """Accanto al brano: testo, stile e seed (una canzone piaciuta si può rifare, o rifare più lenta)."""
    out.with_suffix(".json").write_text(json.dumps({**p, "seed": res.get("seed")}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")


def check(cfg: dict | None = None) -> list[str]:
    cfg = cfg if cfg is not None else config()
    if not cfg:
        return ["canzoni spente: config/hridaya.json → song.enabled"]
    errs = []
    try:
        _python(cfg)
    except SongError as e:
        errs.append(str(e))
    ck = Path(cfg.get("acestep_dir") or "").expanduser() / "checkpoints"
    for m in (cfg.get("dit") or "acestep-v15-turbo", cfg.get("lm") or "acestep-5Hz-lm-1.7B"):
        if not (ck / m).exists():
            errs.append(f"checkpoint mancante: {m} (il worker prova a scaricarlo al primo giro)")
    try:
        vn._ffmpeg()
    except vn.VoiceError as e:
        errs.append(str(e))
    return errs


if __name__ == "__main__":
    if sys.argv[1:] == ["check"]:
        e = check()
        print("\n".join(e) or "OK — canzoni pronte")
        raise SystemExit(1 if e else 0)
    print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
    raise SystemExit(1)
