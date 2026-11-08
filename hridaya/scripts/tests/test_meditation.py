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
