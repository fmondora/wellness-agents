"""Meditazioni lunghe: copione a tempo, musica, mix, tool MCP (montaggio finto)."""
import json
from pathlib import Path

import pytest

import meditation as md
import telegram_queue as tq
import voice_note as vn
from test_mcp_server import call, payload, run
from test_voice import _voice_cfg, _wait_sent

SCRIPT = """@00:00 campana
Siediti comodo... chiudi gli occhi.

Lascia che il respiro trovi il suo passo.

@05:00
Torna al respiro.

@27:00 campana
Lentamente, torna nella stanza.

@30:00 fine
"""


def test_copione_a_tempo():
    segs, total = md.parse(SCRIPT)
    assert total == 1800
    assert [(s["at"], s["bell"]) for s in segs] == [(0, True), (300, False), (1620, True)]
    assert segs[0]["paragraphs"] == ["Siediti comodo... chiudi gli occhi.", "Lascia che il respiro trovi il suo passo."]
    assert segs[-1]["paragraphs"] == ["Lentamente, torna nella stanza."]      # l'ultimo prima di «fine»


@pytest.mark.parametrize("bad, msg", [
    ("Ciao\n@00:00\nx\n@10:00 fine", "cominciare"),
    ("@00:00\nx\n@10:00\ny\n@05:00\nz\n@20:00 fine", "ordine"),
    ("@00:00\nx\n@10:00\ny", "fine"),
    ("@00:00\nx\n@02:00 fine", "5 e 60"),
    ("@00:00\n\n@10:00 fine", "senza parole"),
    ("@00:00\nx\n@10:00 fine\ndopo", "dopo il marcatore"),
])
def test_copioni_sbagliati(bad, msg):
    with pytest.raises(vn.VoiceError, match=msg):
        md.parse(bad)


def test_scelta_della_musica(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "_duration", lambda f: 0.0 if "rotto" in f.name else 600.0)
    d = tmp_path / "music"
    d.mkdir()
    (d / "tampura_do.mp3").write_bytes(b"x" * 100)
    (d / "bansuri_des.mp3").write_bytes(b"x" * 10)
    (d / "note.txt").write_text("tampura")
    cfg = {"music_dirs": [str(d)], "meditation_music": "tampura"}
    assert md.music_source(cfg, None) == d / "tampura_do.mp3"
    assert md.music_source(cfg, "bansuri") == d / "bansuri_des.mp3"
    assert md.music_source(cfg, "tanpura") == d / "tampura_do.mp3"        # grafie diverse dello stesso strumento
    assert md.music_source(cfg, "sitar") == "drone"           # non c'è: il bordone, non il vuoto
    assert md.music_source(cfg, "nessuna") is None
    assert md.music_source({}, None) == "drone"
    (d / "sitar_rotto.mp3").write_bytes(b"x" * 1000)
    assert md.music_source(cfg, "sitar") == "drone"           # brano illeggibile: il bordone


def test_mix_con_musica_bordone_e_senza(tmp_path, monkeypatch):
    monkeypatch.setattr(vn, "_ffmpeg", lambda: "ffmpeg")
    c = md.mix_cmd(tmp_path / "v.wav", 1814.0, tmp_path / "t.mp3", tmp_path / "o.m4a")
    fc = c[c.index("-filter_complex") + 1]
    assert "-stream_loop" in c and "sidechaincompress" in fc and "afade=t=out:st=1789.0" in fc
    assert c[-1].endswith("o.m4a") and "aac" in c
    d = md.mix_cmd(tmp_path / "v.wav", 600.0, "drone", tmp_path / "o.m4a")
    assert "lavfi" in d and "lowpass" in d[d.index("-filter_complex") + 1]
    n = md.mix_cmd(tmp_path / "v.wav", 600.0, None, tmp_path / "o.m4a")
    assert "amix" not in n[n.index("-filter_complex") + 1]


def test_tool_meditazione_in_background(data, tmp_path, monkeypatch):
    _voice_cfg(data, music_dirs=[], meditation_music="drone")
    monkeypatch.setenv("HRIDAYA_VOICE_FAKE", "1")
    mid = tq.enqueue(42, "mi prepari una meditazione di mezz'ora?")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_send_meditation", {"script": "@00:00\nx", "title": "t", "in_reply_to": mid}),
                     call(2, "telegram_send_meditation", {"script": SCRIPT, "title": "Il buio di Amavasya",
                                                          "music": "tanpura", "in_reply_to": mid,
                                                          "caption": "🕉️ <b>Kaula</b> · 30′ in cuffia"})], log)
    assert out[0]["result"]["isError"] and "fine" in out[0]["result"]["content"][0]["text"]
    assert payload(out[1])["status"] == "preparing"
    sent = _wait_sent(log, "sendAudio")[0]["params"]
    assert sent["title"] == "Il buio di Amavasya" and sent["performer"] == "Kaula" and sent["duration"] == 1800
    assert sent["_files"]["audio"].endswith("-il-buio-di-amavasya.m4a")
    assert "/data/exports/meditazioni/" in sent["_files"]["audio"]


def test_meditazione_solo_su_richiesta(data, tmp_path, monkeypatch):
    _voice_cfg(data)
    out = run(data, [call(1, "telegram_send_meditation", {"script": SCRIPT, "title": "t"})], tmp_path / "log.jsonl")
    assert out[0]["result"]["isError"]


def test_meditazione_come_vocale(data, tmp_path, monkeypatch):
    _voice_cfg(data, meditation_music="drone")
    monkeypatch.setenv("HRIDAYA_VOICE_FAKE", "1")
    monkeypatch.setattr(vn, "_ffmpeg", lambda: "ffmpeg")
    assert "libopus" in md.mix_cmd(tmp_path / "v.wav", 600.0, "drone", tmp_path / "o.ogg")
    mid = tq.enqueue(42, "mandamela come vocale")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_send_meditation", {"script": SCRIPT, "title": "Buio", "as_voice": True,
                                                          "in_reply_to": mid})], log)
    assert payload(out[0])["status"] == "preparing"
    sent = _wait_sent(log, "sendVoice")[0]["params"]
    assert sent["_files"]["voice"].endswith("-buio.ogg") and sent["duration"] == 1800


def test_marcatori_malformati_e_troppo_parlato():
    with pytest.raises(vn.VoiceError, match="marcatore non valido"):
        md.parse("@00:00\nx\n@4:00:00\ny\n@10:00 fine")
    segs, _ = md.parse("@ 00:00 campana — arrivo\nSiediti.\n@10:00 fine")
    assert segs[0]["bell"] and segs[0]["paragraphs"] == ["Siediti."]
    with pytest.raises(vn.VoiceError, match="troppo parlato"):
        md.parse("@00:00\n" + "Parla sempre. " * 400 + "\n@05:00 fine")


def test_meditazione_con_inizia(data, tmp_path, monkeypatch):
    _voice_cfg(data, meditation_music="drone")
    monkeypatch.setenv("HRIDAYA_VOICE_FAKE", "1")
    mid = tq.enqueue(42, "meditazione?")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_send_meditation", {"script": SCRIPT, "title": "Buio", "in_reply_to": mid})], log)
    jid = payload(out[0])["job"]
    sent = _wait_sent(log, "sendAudio")[0]["params"]
    assert sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"pr:{jid}:start"


SONG = """[Intro - tanpura drone]

[Verse 1]
Il respiro entra, il respiro esce,
resto a guardare l'onda che viene.

[Chorus]
So Ham, So Ham,
Om Namah Shivaya.
"""


def _song_cfg(data, **over):
    p = data / "config" / "hridaya.json"
    cfg = json.loads(p.read_text()) if p.exists() else {}
    cfg["song"] = {"enabled": True, "acestep_dir": str(data / "ace"), **over}
    p.write_text(json.dumps(cfg))
    (data / "ace" / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
    (data / "ace" / ".venv" / "bin" / "python").write_text("")


def test_canzone_validata():
    import song
    assert song.validate(SONG, "devotional, female voice")["duration_s"] == 240
    for kw, msg in [({"lyrics": "senza tag"}, "tag"), ({"style": ""}, "style"),
                    ({"duration_s": 10}, "duration"), ({"key": "Z major"}, "key"), ({"language": "xx"}, "language")]:
        args = {"lyrics": SONG, "style": "devotional", **kw}
        with pytest.raises(song.SongError, match=msg):
            song.validate(**args)


def test_tool_canzone_in_background(data, tmp_path, monkeypatch):
    _song_cfg(data)
    monkeypatch.setenv("HRIDAYA_VOICE_FAKE", "1")
    mid = tq.enqueue(42, "mi fai una canzone della meditazione di oggi?")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_send_song", {"lyrics": "niente tag", "style": "x", "title": "t",
                                                    "in_reply_to": mid}),
                     call(2, "telegram_send_song", {"lyrics": SONG, "style": "devotional mantra, female voice",
                                                    "title": "Il canto del respiro", "duration_s": 200,
                                                    "caption": "🕉️ <b>Kaula</b> · Il canto del respiro",
                                                    "in_reply_to": mid})], log)
    assert out[0]["result"]["isError"]
    assert payload(out[1])["status"] == "preparing"
    sent = _wait_sent(log, "sendAudio")[0]["params"]
    assert sent["title"] == "Il canto del respiro" and sent["performer"] == "Kaula" and sent["duration"] == 200
    assert "/data/exports/canzoni/" in sent["_files"]["audio"] and sent["_files"]["audio"].endswith(".m4a")


def test_canzoni_spente_e_solo_su_richiesta(data, tmp_path):
    mid = tq.enqueue(42, "una canzone?")
    out = run(data, [call(1, "telegram_send_song", {"lyrics": SONG, "style": "x", "title": "t", "in_reply_to": mid}),
                     call(2, "telegram_send_song", {"lyrics": SONG, "style": "x", "title": "t"})],
              tmp_path / "log.jsonl")
    assert out[0]["result"]["isError"] and "spente" in out[0]["result"]["content"][0]["text"]
    assert out[1]["result"]["isError"]


def test_canzone_build_con_ace_step_finto(data, tmp_path, monkeypatch):
    import subprocess
    import song
    ace = tmp_path / "ace"
    (ace / ".venv" / "bin").mkdir(parents=True)
    (ace / ".venv" / "bin" / "python").write_text("")
    monkeypatch.setattr(vn, "_ffmpeg", lambda: "ffmpeg")
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"m4a")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        spec = json.loads(kw["input"])
        wav = Path(spec["out_dir"]) / "x.wav"
        wav.write_bytes(b"wav")
        return subprocess.CompletedProcess(cmd, 0, "log\nSONG_RESULT " + json.dumps(
            {"ok": True, "path": str(wav), "duration": spec["duration_s"]}) + "\n", "")
    res = song.build({"lyrics": SONG, "style": "devotional"}, tmp_path / "o.m4a", {"acestep_dir": str(ace)},
                     run=fake_run)
    assert res["duration"] == 240 and Path(res["path"]).read_bytes() == b"m4a"
    spec = json.loads(calls[0][1]["input"])
    assert spec["language"] == "it" and calls[0][1]["cwd"] == str(ace)

    def failing(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, "SONG_RESULT " + json.dumps({"ok": False, "error": "OOM"}), "")
    with pytest.raises(song.SongError, match="OOM"):
        song.build({"lyrics": SONG, "style": "devotional"}, tmp_path / "p.m4a", {"acestep_dir": str(ace)}, run=failing)


def test_tonalita_normalizzata_e_tag_tolleranti():
    import song
    for k, want in [("Am", "A minor"), ("d", "D major"), ("F♯ minor", "F♯ minor"), ("Bb maj", "Bb major"),
                    ("D major", "D major"), ("", "")]:
        assert song.normalize_key(k) == want, k
    with pytest.raises(song.SongError):
        song.normalize_key("H major")
    assert song.validate("[Verse1] \nciao\n[Chorus]  \nOm", "devotional")["lyrics"]


def test_canzone_tiene_testo_e_seed_e_non_si_pota(data, tmp_path, monkeypatch):
    import subprocess
    import song
    ace = tmp_path / "ace"
    (ace / ".venv" / "bin").mkdir(parents=True)
    (ace / ".venv" / "bin" / "python").write_text("")
    monkeypatch.setattr(vn, "_ffmpeg", lambda: "ffmpeg")

    def fake_run(cmd, **kw):
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"m4a")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        assert kw["env"]["HF_HUB_DISABLE_XET"] == "1"
        spec = json.loads(kw["input"])
        wav = Path(spec["out_dir"]) / "x.wav"
        wav.write_bytes(b"wav")
        return subprocess.CompletedProcess(cmd, 0, "progress 50%SONG_RESULT " + json.dumps(
            {"ok": True, "path": str(wav), "duration": 240, "seed": 1234}), "")
    res = song.build({"lyrics": SONG, "style": "devotional"}, tmp_path / "o.m4a", {"acestep_dir": str(ace)},
                     run=fake_run)
    side = json.loads((tmp_path / "o.json").read_text())
    assert res["seed"] == 1234 and side["seed"] == 1234 and side["lyrics"].startswith("[Intro")

    def no_path(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, "SONG_RESULT " + json.dumps({"ok": True}), "")
    with pytest.raises(song.SongError, match="nessun file"):
        song.build({"lyrics": SONG, "style": "devotional"}, tmp_path / "p.m4a", {"acestep_dir": str(ace)}, run=no_path)

    def killed(cmd, **kw):
        return subprocess.CompletedProcess(cmd, -9, "", "")
    with pytest.raises(vn.VoiceError, match="codice -9"):
        song.build({"lyrics": SONG, "style": "devotional"}, tmp_path / "q.m4a", {"acestep_dir": str(ace)}, run=killed)


def test_ace_step_mancante_errore_subito(data, tmp_path):
    _song_cfg(data, acestep_dir=str(tmp_path / "non-c-e"))
    mid = tq.enqueue(42, "una canzone?")
    out = run(data, [call(1, "telegram_send_song", {"lyrics": SONG, "style": "x", "title": "t", "in_reply_to": mid}),
                     call(2, "hridaya_service", {"action": "status"})], tmp_path / "log.jsonl")
    assert out[0]["result"]["isError"] and "ACE-Step non trovato" in out[0]["result"]["content"][0]["text"]
    assert "canzoni: accese ma ACE-Step non trovato" in json.dumps(payload(out[1]), ensure_ascii=False)
