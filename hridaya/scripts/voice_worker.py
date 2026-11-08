"""Gira nel Python che ha mlx-audio (non in quello di Hṛdaya): paragrafi → un wav con le pause.

Legge da stdin un JSON:
  {"model", "voice", "quant_bits", "method", "seed", "generate_kwargs", "paragraphs": [...], "pause_s",
   "lead_s", "tail_s", "out"}
`method`: "generate" (voci preset, es. Voxtral) o "generate_voice_design" (Qwen3-TTS VoiceDesign: la
voce nasce da `generate_kwargs.instruct`); `seed` la tiene uguale da un paragrafo all'altro.
Scrive il wav (PCM 16 bit) in `out` e stampa su stdout {"duration": secondi, "sample_rate": hz}.
"""
from __future__ import annotations

import json
import sys


def quantize(model, bits: int | None) -> None:
    """Pesi a `bits` bit in memoria: per Voxtral ~2,6× più veloce, la voce all'ascolto non cambia.
    Solo le parti che esistono e solo i Linear con dimensione multipla di 64."""
    if not bits:
        return
    import mlx.core as mx
    import mlx.nn as nn
    fits = lambda _p, m: isinstance(m, nn.Linear) and m.weight.shape[-1] % 64 == 0  # noqa: E731
    parts = [getattr(model, a) for a in ("language_model", "acoustic_transformer") if hasattr(model, a)]
    for part in parts:
        nn.quantize(part, group_size=64, bits=bits, class_predicate=fits)
    if parts:
        mx.eval(model.parameters())


def generate(model, text: str, spec: dict):
    """Un paragrafo → array audio, col metodo e il seed della config."""
    import numpy as np
    kw = dict(spec.get("generate_kwargs") or {})
    if spec.get("voice"):
        kw["voice"] = spec["voice"]
    if spec.get("seed") is not None:
        import mlx.core as mx
        mx.random.seed(int(spec["seed"]))
    fn = getattr(model, spec.get("method") or "generate")
    return np.concatenate([np.asarray(r.audio).reshape(-1) for r in fn(text=text, **kw)]).astype(np.float32)


def main() -> int:
    spec = json.loads(sys.stdin.read())
    import numpy as np
    import soundfile as sf
    from mlx_audio.tts.utils import load_model

    model = load_model(spec["model"])
    quantize(model, spec.get("quant_bits"))
    sr = model.sample_rate
    silence = lambda s: np.zeros(int(s * sr), np.float32)  # noqa: E731
    parts = [silence(spec.get("lead_s", 0.8))]
    for i, p in enumerate(spec["paragraphs"]):
        parts.append(generate(model, p, spec))
        parts.append(silence(spec.get("pause_s", 2.0) if i < len(spec["paragraphs"]) - 1 else spec.get("tail_s", 3.0)))
    audio = np.concatenate(parts)
    sf.write(spec["out"], audio, sr, subtype="PCM_16")
    print(json.dumps({"duration": round(len(audio) / sr, 2), "sample_rate": sr}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
