"""Vocali: testo per l'orecchio, sintesi (runner finto), scoperta, tool MCP (sintesi finta)."""
import json
import subprocess
from pathlib import Path

import pytest

import telegram_queue as tq
import voice_note as vn
from test_mcp_server import call, payload, run


def _voice_cfg(data, **kw):
    cfg = {"enabled": True, "engine": "mlx-audio", "python": str(data / "py"), "model": "org/Voce-TTS",
           "voice": "it_male", "hf_home": str(data / "hf"), **kw}
    (data / "config" / "hridaya.json").write_text(json.dumps({"voice": cfg}))
    return cfg


def test_testo_per_la_voce_senza_html_emoji_firme():
    paras = vn.spoken("<b>🕉️ Kaula</b>\n\nSiediti... <i>respira</i>.\nAncora &amp; ancora 🔥\n\n\n Resta qui. ")
    assert paras == ["Siediti... respira. Ancora & ancora.", "Resta qui."]
    assert vn.spoken("Respira per meno di <4 secondi e poi> resta.") == ["Respira per meno di <4 secondi e poi> resta."]
    assert vn.spoken("**Siediti**\n- inspira\n# Fine\n— Kaula · Candela") == ["Siediti. inspira. Fine."]
    with pytest.raises(vn.VoiceError):
        vn.spoken("<b></b> 🔥")
    with pytest.raises(vn.VoiceError):
        vn.spoken("a" * (vn.MAX_CHARS + 1))


def test_spenti_senza_config(data):
    assert vn.config() is None
    assert vn.check(None) and "spenti" in vn.check(None)[0]


def test_sintesi_mlx_passa_al_worker_e_converte(data, monkeypatch, tmp_path):
    cfg = _voice_cfg(data)
    (data / "py").write_text("")
    monkeypatch.setattr(vn, "_ffmpeg", lambda: "ffmpeg")
    seen = {}

    def runner(cmd, **kw):
        if cmd[1].endswith("voice_worker.py"):
            spec = json.loads(kw["input"])
            seen.update(spec=spec, env=kw["env"])
            Path(spec["out"]).write_bytes(b"RIFF")
            return subprocess.CompletedProcess(cmd, 0, stdout='{"duration": 12.5, "sample_rate": 24000}\n', stderr="")
        Path(cmd[-1]).write_bytes(b"OggS")                       # ffmpeg
        assert "libopus" in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    out = tmp_path / "v.ogg"
    r = vn.synth("Siediti.\n\nResta.", out, cfg, run=runner)
    assert r == {"path": str(out), "duration": 12.5} and out.read_bytes() == b"OggS"
    assert seen["spec"]["paragraphs"] == ["Siediti.", "Resta."]
    assert seen["spec"]["model"] == "org/Voce-TTS" and seen["spec"]["voice"] == "it_male"
    assert seen["env"]["HF_HOME"] == str(data / "hf") and seen["env"]["HF_HUB_OFFLINE"] == "1"


def test_hf_home_della_shell_non_vale_per_il_servizio(data, monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "shell-hf"))
    cfg = {"enabled": True, "model": "org/Voce-TTS"}
    assert vn.model_dir("org/Voce-TTS", cfg) == Path.home() / ".cache" / "huggingface" / "hub" / "models--org--Voce-TTS"
    monkeypatch.setattr(vn, "_ffmpeg", lambda: "ffmpeg")
    ok = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")  # noqa: E731
    assert any("non arriva al servizio" in p for p in vn.check({**cfg, "python": "/bin/sh"}, run=ok))


def test_config_malformata_non_rompe(data):
    (data / "config" / "hridaya.json").write_text(json.dumps({"voice": True}))
    assert vn.config() is None


def test_timeout_della_sintesi_diventa_errore_del_vocale(data, monkeypatch, tmp_path):
    cfg = _voice_cfg(data)
    (data / "py").write_text("")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    with pytest.raises(vn.VoiceError, match="oltre"):
        vn.synth("Ciao.", tmp_path / "v.ogg", cfg, run=slow)


def test_sintesi_fallita_errore_chiaro(data, monkeypatch, tmp_path):
    cfg = _voice_cfg(data)
    (data / "py").write_text("")
    monkeypatch.setattr(vn, "_ffmpeg", lambda: "ffmpeg")
    boom = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="OOM")  # noqa: E731
    with pytest.raises(vn.VoiceError, match="OOM"):
        vn.synth("Ciao.", tmp_path / "v.ogg", cfg, run=boom)
    with pytest.raises(vn.VoiceError, match="python dei vocali"):
        vn.synth("Ciao.", tmp_path / "v.ogg", {**cfg, "python": str(tmp_path / "manca")}, run=boom)


def test_check_segnala_modello_mancante(data, monkeypatch):
    cfg = _voice_cfg(data)
    (data / "py").write_text("")
    monkeypatch.setattr(vn, "_ffmpeg", lambda: "ffmpeg")
    ok = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")  # noqa: E731
    assert any("modello non scaricato" in p for p in vn.check(cfg, run=ok))
    snap = data / "hf" / "hub" / "models--org--Voce-TTS" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    assert vn.check(cfg, run=ok) == []


def test_scoperta_modelli_e_ambienti(tmp_path, monkeypatch):
    hf = tmp_path / "hf"
    for name, f in [("models--mlx-community--Voxtral-4B-TTS", "w.safetensors"),
                    ("models--openai--whisper-large", "w.bin"), ("models--Qwen--Qwen3-7B", "w.bin"),
                    ("models--hexgrad--Kokoro-82M", None)]:
        d = hf / "hub" / name / "snapshots" / "s"
        d.mkdir(parents=True)
        if f:
            (d / f).write_bytes(b"x" * 10)
    monkeypatch.setenv("HF_HOME", str(hf))
    monkeypatch.setattr(vn.Path, "home", lambda: tmp_path / "home")
    names = [m["model"] for m in vn.find_models()]
    assert names == ["mlx-community/Voxtral-4B-TTS"]            # niente ASR, niente LLM, niente download a metà
    venv = tmp_path / "wip" / "progetto" / ".venv"
    (venv / "lib" / "python3.12" / "site-packages" / "mlx_audio").mkdir(parents=True)
    (venv / "lib" / "python3.12" / "site-packages" / "mlx_audio-0.6.3.dist-info").mkdir()
    (venv / "bin").mkdir()
    (venv / "bin" / "python").write_text("")
    (venv / "pyvenv.cfg").write_text("")
    other = tmp_path / "wip" / "altro" / ".venv"
    (other / "bin").mkdir(parents=True)
    (other / "pyvenv.cfg").write_text("")
    assert vn.find_envs([tmp_path / "wip"]) == [{"python": str(venv / "bin" / "python"), "mlx_audio": "0.6.3", "ok": True}]


def _wait_sent(log, method, n=1, timeout=15):
    import time
    end = time.time() + timeout
    while time.time() < end:
        if log.exists():
            rows = [json.loads(x) for x in log.read_text().splitlines()]
            hits = [r for r in rows if r["method"] == method]
            if len(hits) >= n:
                return hits
        time.sleep(0.2)
    raise AssertionError(f"{method} non spedito")


def test_tool_vocale_in_background_senza_doppioni(data, tmp_path, monkeypatch):
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_send_voice", {"text": "Siediti."})], log)
    assert out[0]["result"]["isError"] and "spenti" in out[0]["result"]["content"][0]["text"]
    _voice_cfg(data)
    monkeypatch.setenv("HRIDAYA_VOICE_FAKE", "1")
    mid = tq.enqueue(42, "me la mandi in vocale?")
    args = {"text": "Siediti.\n\nResta.", "title": "Candela di Amavasya", "caption": "🕉️ <b>Kaula</b>", "in_reply_to": mid}
    out = run(data, [call(1, "telegram_send_voice", args), call(2, "hridaya_service", {"action": "status"})], log)
    r = payload(out[0])
    assert r["status"] == "preparing" and r["done"]
    assert any(x.startswith("vocali: accesi") for x in payload(out[1])["listening"])
    sent = _wait_sent(log, "sendVoice")
    assert sent[0]["params"]["chat_id"] == 42 and sent[0]["params"]["caption"] == "🕉️ <b>Kaula</b>"
    assert "-candela-di-amavasya.ogg" in sent[0]["params"]["_files"]["voice"]
    assert sent[0]["params"]["_files"]["voice"].startswith(str((data / "data" / "exports" / "voce").resolve()))
    assert tq.list_pending() == []
    again = run(data, [call(1, "telegram_send_voice", args)], log)          # Claude ritenta
    assert payload(again[0])["status"] == "duplicate"
    assert len(_wait_sent(log, "sendVoice")) == 1


def test_vocale_d_iniziativa_solo_dopo_la_sera(data, tmp_path, monkeypatch):
    _voice_cfg(data)
    monkeypatch.setenv("HRIDAYA_VOICE_FAKE", "1")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_send_voice", {"text": "Siediti."}),
                     call(2, "telegram_send_voice", {"text": "Siediti.", "after": "evening"})], log)
    assert out[0]["result"]["isError"] and "in_reply_to" in out[0]["result"]["content"][0]["text"]
    assert out[1]["result"]["isError"] and "non è ancora partito" in out[1]["result"]["content"][0]["text"]


def test_di_notte_niente_vocali(data, tmp_path, monkeypatch):
    cfg = {"voice": {"enabled": True, "engine": "mlx-audio", "python": "/x"},
           "bedtime": "00:01", "wake": {"fallback": "23:59", "fallback_max": "23:59", "late_cutoff": "23:59"}}
    (data / "config" / "hridaya.json").write_text(json.dumps(cfg))
    monkeypatch.setenv("HRIDAYA_VOICE_FAKE", "1")
    mid = tq.enqueue(42, "vocale?")
    out = run(data, [call(1, "telegram_send_voice", {"text": "Siediti.", "in_reply_to": mid})], tmp_path / "log.jsonl")
    assert payload(out[0])["status"] == "silent" and not (tmp_path / "log.jsonl").exists()


def test_lavoro_fallito_avvisa_la_sessione(data, monkeypatch, tmp_path):
    _voice_cfg(data)
    monkeypatch.setenv("HRIDAYA_TRANSPORT_LOG", str(tmp_path / "log.jsonl"))
    spawned = []
    r = vn.create_job("voice", "k1", {"chat_id": 42, "text": "Ciao.", "title": "prova"},
                      spawn=lambda *a, **kw: spawned.append(a))
    assert r["status"] == "preparing" and spawned
    with pytest.raises(vn.VoiceError):          # python dei vocali inesistente
        vn.run_job(r["job"])
    assert vn.read_job(r["job"])["status"] == "failed"
    ev = [x for x in tq.list_pending() if x.get("event") == "voice_failed"]
    assert ev and "prova" in ev[0]["text"]
    again = vn.create_job("voice", "k1", {"chat_id": 42, "text": "Ciao.", "title": "prova"},
                          spawn=lambda *a, **kw: None)
    assert again["status"] == "preparing"        # fallito → si può rifare


def test_lavoro_vivo_non_si_rilancia_morto_si(data, monkeypatch):
    import os
    _voice_cfg(data)
    calls = []
    spawn = lambda *a, **kw: calls.append(a)  # noqa: E731
    r = vn.create_job("voice", "k2", {"chat_id": 42, "text": "Ciao."}, spawn=spawn)
    job = vn.read_job(r["job"])
    job.update(status="running", pid=os.getpid())               # processo vivo
    vn.write_job(job)
    assert vn.create_job("voice", "k2", {"chat_id": 42, "text": "Ciao."}, spawn=spawn)["status"] == "running"
    job.update(pid=999999)                                       # processo morto
    vn.write_job(job)
    assert vn.create_job("voice", "k2", {"chat_id": 42, "text": "Ciao."}, spawn=spawn)["status"] == "preparing"
    assert len(calls) == 2


def test_voice_filter_solo_filtri():
    assert vn.voice_filter({"voice_filter": "bass=g=3:f=160,treble=g=-4:f=5500"}) == "bass=g=3:f=160,treble=g=-4:f=5500"
    with pytest.raises(vn.VoiceError):
        vn.voice_filter({"voice_filter": "volume=2 -i /etc/passwd"})


def test_profili_di_voce(data, tmp_path, monkeypatch):
    cfg = _voice_cfg(data, default_name="maschile", voice_filter="bass=g=2",
                     profiles={"femminile": {"model": "org/Design-TTS", "voice": "", "method": "generate_voice_design",
                                             "seed": 7, "generate_kwargs": {"instruct": "calda"}}})
    assert vn.profiles(cfg) == ["maschile", "femminile"]
    assert vn.with_profile(cfg, None) is cfg and vn.with_profile(cfg, "maschile") is cfg
    f = vn.with_profile(cfg, "femminile")
    assert f["model"] == "org/Design-TTS" and f["method"] == "generate_voice_design" and f["python"] == cfg["python"]
    assert "voice_filter" not in f                               # il timbro della principale non passa
    with pytest.raises(vn.VoiceError, match="disponibili: maschile, femminile"):
        vn.with_profile(cfg, "robot")
    monkeypatch.setenv("HRIDAYA_VOICE_FAKE", "1")
    mid = tq.enqueue(42, "con la voce femminile")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_send_voice", {"text": "Ciao.", "in_reply_to": mid, "voice_profile": "robot"}),
                     call(2, "telegram_send_voice", {"text": "Ciao.", "in_reply_to": mid, "voice_profile": "femminile"}),
                     call(3, "hridaya_service", {"action": "status"})], log)
    assert out[0]["result"]["isError"]
    r = payload(out[1])
    assert r["status"] == "preparing" and vn.read_job(r["job"])["voice_profile"] == "femminile"
    assert any("voci: maschile, femminile" in x for x in payload(out[2])["listening"])
