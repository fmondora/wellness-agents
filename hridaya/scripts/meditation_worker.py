"""Gira nel Python che ha mlx-audio: copione a tempo → traccia voce (mono) con campane e silenzi.

Legge da stdin un JSON:
  {"model", "voice", "quant_bits", "generate_kwargs", "pause_s",
   "segments": [{"at": secondi, "bell": bool, "paragraphs": [...]}], "total_s", "end_bell": bool, "out"}
Ogni segmento parte al suo minuto (dopo la campana, se c'è). Se la voce di un segmento sfora
l'inizio del successivo, il successivo slitta (e lo dice in "shifted").
Stampa {"duration", "voice_s", "shifted": [[segmento, secondi]...], "sample_rate"}.
"""
from __future__ import annotations

import json
import sys

from voice_worker import generate, quantize

BELL_GAP_S = 6.0      # dopo il colpo di campana, prima della voce
GAP_S = 3.0           # margine minimo tra la fine di una voce e il segmento dopo


def bell(np, sr: int, f0: float = 196.0, dur: float = 14.0):
    """Campana tibetana: parziali inarmoniche a coppie leggermente stonate (battimento)."""
    t = np.arange(int(sr * dur)) / sr
    out = np.zeros_like(t)
    for ratio, amp, decay in [(1.0, 1.0, 7.0), (2.71, 0.55, 5.0), (5.15, 0.25, 3.0), (8.4, 0.10, 1.6)]:
        for detune in (-0.45, 0.45):
            out += amp * np.exp(-t / decay) * np.sin(2 * np.pi * (f0 * ratio + detune * ratio) * t)
    out *= np.minimum(1, t / 0.004)
    return (out / np.abs(out).max() * 0.45).astype(np.float32)


def main() -> int:
    spec = json.loads(sys.stdin.read())
    import numpy as np
    import soundfile as sf
    from mlx_audio.tts.utils import load_model

    model = load_model(spec["model"])
    quantize(model, spec.get("quant_bits"))
    sr = model.sample_rate
    pause = int(spec.get("pause_s", 2.0) * sr)
    b = bell(np, sr)

    placed, shifted, cursor, voice_s = [], [], 0, 0.0
    for k, seg in enumerate(spec["segments"]):
        start = int(seg["at"] * sr)
        if start < cursor:
            shifted.append([k, round((cursor - start) / sr, 1)])
            start = cursor
        if seg.get("bell"):
            placed.append((start, b))
            start += int(BELL_GAP_S * sr)
        pos = start
        for i, p in enumerate(seg.get("paragraphs") or []):
            a = generate(model, p, spec)
            placed.append((pos, a))
            voice_s += len(a) / sr
            pos += len(a) + (pause if i < len(seg["paragraphs"]) - 1 else 0)
        cursor = max(pos, start) + int(GAP_S * sr)

    total = max(int(spec["total_s"] * sr), cursor)
    if spec.get("end_bell", True):
        placed.append((total, b))
        total += len(b)
    out = np.zeros(total, np.float32)
    for s, a in placed:
        e = min(total, s + len(a))
        out[s:e] += a[: e - s]
    peak = float(np.abs(out).max() or 1.0)
    if peak > 0.98:
        out *= 0.98 / peak
    sf.write(spec["out"], out, sr, subtype="PCM_16")
    print(json.dumps({"duration": round(total / sr, 1), "voice_s": round(voice_s, 1), "shifted": shifted,
                      "sample_rate": sr}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
