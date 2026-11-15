"""Gira nel Python di ACE-Step 1.5: testo + stile → wav. Legge da stdin un JSON:
  {"repo", "out_dir", "lyrics", "style", "duration_s", "bpm"?, "key"?, "language", "seed", "dit", "lm"}
Stampa per ultima una riga «SONG_RESULT {json}»: {"ok", "path", "duration", "seed"} o {"ok": false, "error"}.
Le inizializzazioni di ACE-Step non sollevano: ne restituiscono l'esito, che qui si controlla (un LM
non caricato darebbe una canzone molto peggiore senza errore).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


class Fail(Exception):
    pass


def _ok(res, ok_first: bool, what: str) -> None:
    """ACE-Step: (ok, msg) per i download, (msg, ok) per le inizializzazioni."""
    ok, msg = (res[0], res[1]) if ok_first else (res[1], res[0])
    if not ok:
        raise Fail(f"{what}: {str(msg)[:200]}")


def main() -> int:
    spec = json.loads(sys.stdin.read())
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    try:
        from acestep.handler import AceStepHandler
        from acestep.inference import GenerationConfig, GenerationParams, generate_music
        from acestep.llm_inference import LLMHandler
        from acestep.model_downloader import ensure_lm_model, ensure_main_model

        repo = Path(spec["repo"])
        ck = repo / "checkpoints"
        _ok(ensure_main_model(ck), True, "modello principale")
        _ok(ensure_lm_model(spec["lm"], ck), True, "modello linguistico")
        dit = AceStepHandler()
        _ok(dit.initialize_service(project_root=str(repo), config_path=spec["dit"], device="mps"), False, "DiT")
        llm = LLMHandler()
        _ok(llm.initialize(checkpoint_dir=str(ck), lm_model_path=spec["lm"], backend="mlx", device="mps"),
            False, "modello linguistico")
        seed = int(spec.get("seed", -1))
        p = GenerationParams(caption=spec["style"], lyrics=spec["lyrics"], bpm=spec.get("bpm"),
                             keyscale=spec.get("key") or "", timesignature="4", duration=spec["duration_s"],
                             vocal_language=spec.get("language") or "it", thinking=True, use_cot_lyrics=False,
                             seed=seed)
        cfg = GenerationConfig(batch_size=1, audio_format="wav", use_random_seed=seed < 0,
                               seeds=[seed] if seed >= 0 else None)
        r = generate_music(dit, llm, p, cfg, save_dir=spec["out_dir"])
        if not r.success or not r.audios:
            raise Fail(f"generazione: {str(r.error)[:300]}")
        a = r.audios[0]
        path = a.get("path") or ""
        if not path or not Path(path).exists():
            raise Fail("ACE-Step non ha salvato il wav")
        out = {"ok": True, "path": path, "duration": spec["duration_s"],
               "seed": (a.get("params") or {}).get("seed", seed)}
    except Fail as e:
        out = {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001 — l'errore torna al chiamante, non un traceback muto
        out = {"ok": False, "error": f"{e.__class__.__name__}: {e}"[:300]}
    print("\nSONG_RESULT " + json.dumps(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
