"""Meditazioni lunghe da ascoltare in cuffia: copione a tempo → voce + campane + musica → m4a.

Il copione lo scrive lo specialista (il Kaula). Ogni segmento comincia con una riga marcatore:

  @00:00 campana
  Siediti comodo... (paragrafi; riga vuota = pausa lunga)

  @04:00
  ...poche frasi, poi silenzio fino al marcatore dopo.

  @27:00 campana
  ...il ritorno.

  @30:00 fine

`campana` suona un colpo prima della voce; `@mm:ss fine` è la durata totale (chiude con la
campana). Fra un segmento e l'altro c'è solo la musica: il silenzio è la pratica.

Musica (config voice.music_dirs, voice.meditation_music): una parola che compare nel nome di un
file audio delle cartelle (es. «tanpura», «bansuri»), «drone» (bordone sintetico, sempre
disponibile) o «nessuna». La musica sta sotto la voce e si abbassa da sola quando la voce parla.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import voice_note as vn

MARK = re.compile(r"^@\s*(\d{1,2}):([0-5]\d)(?:\s+(campana|fine))?\s*(?:[—–-].*)?$", re.I)
SPEECH_CPS = 14           # caratteri al secondo della voce, per stimare quanto parla
MIN_TOTAL_S, MAX_TOTAL_S = 5 * 60, 60 * 60
MAX_SCRIPT_CHARS = 15000
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".aiff"}
MEDITATION_WORKER = vn.HERE / "meditation_worker.py"
MUSIC_LUFS = -32          # sotto la voce (~-18): si sente, non copre
TG_MAX_BYTES = 49_000_000
# grafie diverse dello stesso strumento nei nomi dei file
ALIASES = {"tanpura": ("tanpura", "tampura", "tambura", "tamboura"), "bansuri": ("bansuri", "bansri"),
           "campane": ("campane", "bowl", "bowls", "singing")}


def parse(script: str) -> tuple[list[dict], int]:
    """→ (segmenti [{"at", "bell", "paragraphs"}], durata totale in secondi). Errori chiari."""
    segs: list[dict] = []
    total, body = None, []

    def close():
        if segs:
            text = "\n".join(body).strip()
            segs[-1]["paragraphs"] = vn.spoken(text, MAX_SCRIPT_CHARS) if text else []

    for ln in (script or "").splitlines():
        line = ln.strip().strip("*`")
        m = MARK.match(line)
        if not m and line.startswith("@"):
            raise vn.VoiceError(f"marcatore non valido: {line[:40]!r} (forma: @mm:ss, @mm:ss campana, @mm:ss fine)")
        if not m:
            if total is not None and ln.strip():
                raise vn.VoiceError("testo dopo il marcatore «fine»")
            body.append(ln)
            continue
        at = int(m.group(1)) * 60 + int(m.group(2))
        if segs and at <= segs[-1]["at"]:
            raise vn.VoiceError(f"marcatori non in ordine: @{m.group(1)}:{m.group(2)}")
        if not segs and "".join(body).strip():
            raise vn.VoiceError("il copione deve cominciare con un marcatore (@00:00)")
        close()
        body = []
        if (m.group(3) or "").lower() == "fine":
            total = at
            continue
        segs.append({"at": at, "bell": (m.group(3) or "").lower() == "campana", "paragraphs": []})
    if total is None:      # con «fine» l'ultimo segmento è già chiuso: non va svuotato
        close()
    if not segs or segs[0]["at"] != 0:
        raise vn.VoiceError("serve un primo segmento a @00:00")
    if total is None:
        raise vn.VoiceError("manca la riga finale «@mm:ss fine» (la durata totale)")
    if not MIN_TOTAL_S <= total <= MAX_TOTAL_S:
        raise vn.VoiceError("durata fra 5 e 60 minuti")
    if total <= segs[-1]["at"]:
        raise vn.VoiceError("«fine» deve venire dopo l'ultimo segmento")
    chars = sum(len(p) for s in segs for p in s["paragraphs"])
    if not chars:
        raise vn.VoiceError("copione senza parole")
    if chars > MAX_SCRIPT_CHARS:
        raise vn.VoiceError(f"copione troppo lungo (> {MAX_SCRIPT_CHARS} caratteri): in una meditazione parla il silenzio")
    speech = chars / SPEECH_CPS + 2 * sum(max(0, len(s["paragraphs"]) - 1) for s in segs)
    if speech > 0.6 * total:
        raise vn.VoiceError(f"troppo parlato: ~{int(speech // 60)}′ di voce su {total // 60}′ (al massimo il 60%)")
    return segs, total


def music_source(cfg: dict, choice: str | None) -> Path | str | None:
    """File audio scelto, «drone», o None (nessuna musica)."""
    want = (choice or cfg.get("meditation_music") or "drone").strip().lower()
    if want in ("nessuna", "none", "no", "silenzio"):
        return None
    if want == "drone":
        return "drone"
    names = next((v for v in ALIASES.values() if want in v), (want,))
    files = []
    for d in cfg.get("music_dirs") or []:
        p = Path(d).expanduser()
        if p.is_dir():
            files += [f for f in p.rglob("*") if f.suffix.lower() in AUDIO_EXT and any(n in f.name.lower() for n in names)]
    for f in sorted(files, key=lambda f: f.stat().st_size, reverse=True):   # il più lungo: meno ripetizioni
        if _duration(f) >= 20:
            return f
    return "drone"                          # chiesta una musica che non c'è (o rotta): il bordone, non il vuoto


def _duration(f: Path) -> float:
    try:
        r = subprocess.run([vn._ffmpeg().replace("ffmpeg", "ffprobe"), "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(f)], capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError, vn.VoiceError):
        return 0.0


def _drone(total: float) -> list[str]:
    """Bordone sintetico (Do grave, Sol, Do): sinusoidi con un respiro lento, filtrate."""
    expr = ("0.30*sin(2*PI*65.41*t)*(0.8+0.2*sin(2*PI*0.07*t))"
            "+0.20*sin(2*PI*98.00*t)*(0.8+0.2*sin(2*PI*0.05*t+1))"
            "+0.14*sin(2*PI*130.81*t)*(0.8+0.2*sin(2*PI*0.09*t+2))"
            "+0.05*sin(2*PI*196.00*t)*(0.7+0.3*sin(2*PI*0.11*t+3))")
    return ["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={total:.1f}"]


def mix_cmd(voice_wav: Path, total: float, music: Path | str | None, out: Path, bitrate: str = "96k",
            vfilter: str = "") -> list[str]:
    """.m4a → AAC (brano); .ogg → Opus (vocale di Telegram). `vfilter`: timbro della voce."""
    cmd = [vn._ffmpeg(), "-loglevel", "error", "-y", "-i", str(voice_wav)]
    voice = f"[0:a]aresample=48000,{vfilter + ',' if vfilter else ''}pan=stereo|c0=c0|c1=c0[v]"
    if music is None:
        fc = f"{voice};[v]alimiter=limit=0.9:level=0[out]"
    else:
        cmd += _drone(total) if music == "drone" else ["-stream_loop", "-1", "-i", str(music)]
        fade_out = max(0.0, total - 25)
        fc = (f"{voice};"
              f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.1f},asetpts=PTS-STARTPTS,"
              f"{'lowpass=f=900,' if music == 'drone' else ''}loudnorm=I={MUSIC_LUFS}:TP=-8:LRA=7,"
              f"afade=t=in:d=12,afade=t=out:st={fade_out:.1f}:d=25[m0];"
              "[v]asplit=2[v1][vk];"
              "[m0][vk]sidechaincompress=threshold=0.02:ratio=3:attack=300:release=2000[m];"
              "[v1][m]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.9:level=0[out]")
    codec = (["-c:a", "libopus", "-b:a", bitrate, "-application", "audio"] if out.suffix == ".ogg"
             else ["-c:a", "aac", "-b:a", bitrate, "-movflags", "+faststart"])
    return cmd + ["-filter_complex", fc, "-map", "[out]", *codec, str(out)]


def build(script: str, out: Path, cfg: dict, music: str | None = None,
          run: vn.Runner = subprocess.run) -> dict:
    """Copione → `out` (.m4a brano, .ogg vocale). → {"path", "duration", "voice_s", "shifted", "music"}"""
    segs, total = parse(script)
    src = music_source(cfg, music)
    label = "nessuna" if src is None else ("drone" if src == "drone" else Path(src).name)
    out.parent.mkdir(parents=True, exist_ok=True)
    if vn.fake_mode():
        out.write_bytes(b"m4a-fake")
        return {"path": str(out), "duration": float(total), "voice_s": 0.0, "shifted": [], "music": label}
    if cfg.get("engine", "mlx-audio") != "mlx-audio":
        raise vn.VoiceError("le meditazioni lunghe richiedono il motore mlx-audio")
    with tempfile.TemporaryDirectory(prefix="hridaya-medit-") as d:
        wav = Path(d) / "voce.wav"
        res = vn.run_worker(MEDITATION_WORKER, {**vn.worker_spec(cfg), "segments": segs, "total_s": total,
                                                "end_bell": True, "out": str(wav)},
                            cfg, run, cfg.get("meditation_timeout_s", 1800))
        dur = float(res.get("duration") or total)
        for rate in (("64k", "48k") if out.suffix == ".ogg" else ("96k", "64k")):
            try:
                vn._run(run, mix_cmd(wav, dur, src, out, rate, vn.voice_filter(cfg)), "mix", 900)
            except vn.VoiceError:
                if src in (None, "drone"):
                    raise
                src, label = "drone", "drone (la musica scelta non si è aperta)"   # ripiego, non fallimento
                vn._run(run, mix_cmd(wav, dur, src, out, rate, vn.voice_filter(cfg)), "mix", 900)
            if not out.exists() or out.stat().st_size <= TG_MAX_BYTES:
                break
        if not out.exists():
            raise vn.VoiceError("il mix non ha scritto il file")
        if out.stat().st_size > TG_MAX_BYTES:
            raise vn.VoiceError("file oltre i 50 MB di Telegram anche al bitrate più basso")
    return {"path": str(out), "duration": dur, "voice_s": res.get("voice_s"), "shifted": res.get("shifted") or [],
            "music": label}
