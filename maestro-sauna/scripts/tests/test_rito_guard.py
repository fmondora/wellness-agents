"""La soglia: forma del rito, tetti della persona letti in modo stretto, condizioni del giorno."""
import copy
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

import rito_guard as g

HERE = Path(__file__).resolve().parent
FIX = HERE.parents[1] / "apps" / "rito" / "fixtures"
DEMO = json.loads((FIX / "demo.rito.json").read_text(encoding="utf-8"))
CASES = json.loads((FIX / "cases.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 19, 17, 30, tzinfo=g.tz())
RULES = {"heat_round_max_min": 15, "heat_total_max_min": 30, "rounds_max": 2, "temp_max_c": 70,
         "cold": {"allowed": True, "max_min": 5, "optional": True}, "rest_ratio_min": 1.0, "latest_end": "20:00"}


def rito(**over):
    r = copy.deepcopy(DEMO)
    r["date"] = "2026-11-19"
    r["demo"] = False
    r.update(over)
    return r


def repo(tmp_path, rules=RULES):
    d = tmp_path / "data" / "sauna"
    d.mkdir(parents=True)
    (tmp_path / "data" / "profile.json").write_text("{}")
    if rules is not None:
        (d / "rules.json").write_text(json.dumps(rules) if not isinstance(rules, str) else rules)
    return tmp_path


def moment(r, mid):
    return next(m for m in r["moments"] if m["id"] == mid)


def test_la_partitura_di_esempio_passa(tmp_path):
    assert g.validate(DEMO) == []
    assert g.check(rito(), repo(tmp_path), NOW) == []
    p = g.planned(DEMO)
    assert (p["rounds"], p["heat_s"], p["heat_max_s"], p["rest_s"]) == (2, 1440, 1680, 2700)
    # traguardi e minimi (doccia 3′, dopo 5′) più i passaggi; quello del calore no (conta dal tocco)
    assert p["total_s"] == 4440 + 180 + 300 + 180
    assert p["longest_s"] == p["total_s"] + 240 + 120         # caldo e freddo fino al massimo


def test_i_due_validatori_dicono_la_stessa_cosa():
    for why, r in CASES["invalid"]:
        assert g.validate(r), f"doveva essere rifiutato: {why}"
    for why, r in CASES["valid"]:
        assert g.validate(r) == [], f"doveva passare: {why}"
    assert "partitura non valida" in g.check({"v": 2}, None, NOW)[0]


def test_niente_numeri_impossibili(tmp_path):
    f = tmp_path / "x.rito.json"
    f.write_text('{"v": 1, "moments": [{"id": "x", "name": "X", "type": "heat", "max_s": Infinity}]}')
    with pytest.raises(ValueError):
        g.read_rito(f)
    assert g.validate({"v": 1, "moments": [{"id": "x", "name": "X", "type": "heat", "max_s": float("inf")}]})


def test_tetti_del_calore(tmp_path):
    root = repo(tmp_path)
    r = rito()
    moment(r, "calore-1")["max_s"] = 1000                    # 16′40″ in un passaggio
    out = g.check(r, root, NOW)
    assert any("tetto è 15′ a passaggio" in x for x in out) and any("in tutto" in x for x in out)
    r = rito()
    moment(r, "calore-2")["temp_c"] = 85
    assert any("85 °C" in x for x in g.check(r, root, NOW))
    r = rito()
    del moment(r, "calore-2")["temp_c"]
    assert any("manca temp_c" in x for x in g.check(r, root, NOW))
    r = rito()
    r["moments"].insert(6, {"id": "calore-3", "name": "Terzo", "type": "heat", "target_s": 60, "max_s": 60, "temp_c": 60})
    r["moments"].insert(7, {"id": "riposo-3", "name": "Riposo", "type": "rest", "target_s": 600})
    assert any("3 passaggi" in x for x in g.check(r, root, NOW))
    none = repo(tmp_path / "zero", {**RULES, "rounds_max": 0})
    assert any("nessun calore" in x for x in g.check(rito(), none, NOW))


def test_freddo_facoltativo_e_limitato(tmp_path):
    r = rito()
    moment(r, "acqua-1")["optional"] = False
    assert any("facoltativo" in x for x in g.check(r, repo(tmp_path), NOW))
    r = rito()
    moment(r, "acqua-1")["max_s"] = 600
    assert any("nel freddo" in x for x in g.check(r, repo(tmp_path / "b"), NOW))
    no_cold = {**RULES, "cold": {"allowed": False}}
    assert any("non è ammessa" in x for x in g.check(rito(), repo(tmp_path / "c", no_cold), NOW))
    late = {**RULES, "cold": {"not_after": "17:00"}}
    assert any("dopo le 17:00" in x for x in g.check(rito(), repo(tmp_path / "d", late), NOW))
    partial = {**RULES, "cold": {"allowed": True}}            # il resto di cold resta prudente (2′), non sparisce
    r = rito()
    moment(r, "acqua-1")["max_s"] = 1800
    assert any("il tetto è 2′" in x for x in g.check(r, repo(tmp_path / "e", partial), NOW))


def test_ordine_del_rito_e_riposo_per_ogni_calore(tmp_path):
    root = repo(tmp_path)
    r = rito()
    r["moments"] = [m for m in r["moments"] if m["id"] != "riposo-1"]
    out = g.check(r, root, NOW)
    assert any("manca il riposo" in x and "Primo calore" in x for x in out)
    r = rito()
    r["moments"] = [m for m in r["moments"] if m["type"] != "prep"]
    assert any("soglia" in x for x in g.check(r, root, NOW))
    r = rito()
    moment(r, "riposo-1")["target_s"] = 60                    # un minuto dopo dieci di calore…
    moment(r, "riposo-1")["min_s"] = 60
    moment(r, "riposo-2")["target_s"] = 2400                  # …non lo compensa il riposo finale
    out = g.check(r, root, NOW)
    assert any("Primo calore" in x and "almeno quanto il calore" in x for x in out)


def test_ora_ultima_seduta_picco_e_blocco(tmp_path):
    root = repo(tmp_path, {**RULES, "min_hours_between": 20, "wod_peak_max_bpm": 165, "earliest_start": "07:00"})
    late = datetime(2026, 11, 19, 19, 30, tzinfo=g.tz())
    assert any("potrebbe finire alle 21:01, oltre le 20:00" in x for x in g.check(rito(), root, late))
    after = datetime(2026, 11, 19, 21, 0, tzinfo=g.tz())
    assert any("oltre le 20:00: oggi il rito non comincia più" in x for x in g.check(rito(), root, after))
    night = datetime(2026, 11, 19, 0, 15, tzinfo=g.tz())      # dopo mezzanotte non «passa» perché 01:09 < 20:00
    assert any("non comincia prima delle 07:00" in x for x in g.check(rito(), root, night))
    s = root / "data" / "sauna" / "sessions"
    s.mkdir()
    (s / "2026-11-19.session.json").write_text(json.dumps({"ended_at": "2026-11-19T08:10:00", "heat_s": 900}))   # senza fuso
    (s / "2026-11-18.demo.session.json").write_text(json.dumps({"ended_at": "2026-11-19T12:00:00+01:00", "heat_s": 900, "demo": True}))
    assert any("almeno 20 ore" in x and "08:10" in x for x in g.check(rito(), root, NOW))
    (s / "2026-11-19.session.json").unlink()
    d = root / "data" / "coach-longevita" / "daily"
    d.mkdir(parents=True)
    (d / "2026-11-19.session-hr.json").write_text(json.dumps({"hr_recovery": {"peak": 171}}))
    assert any("171 battiti" in x for x in g.check(rito(), root, NOW))
    (d / "2026-11-19.session-hr.json").write_text(json.dumps({"hr_recovery": {"peak": 151}}))
    assert g.check(rito(), root, NOW) == []
    assert any("riscrive per oggi" in x for x in g.check(rito(date="2026-11-18"), repo(tmp_path / "o"), NOW))
    r = rito()
    del r["date"]
    assert any("non ha la data" in x for x in g.check(r, repo(tmp_path / "nd"), NOW))


def test_sospensione(tmp_path):
    for k, hold in enumerate([{"until": "2026-11-21", "why": "febbre"}, {"why": "lo dice il medico"}, True]):
        out = g.check(rito(), repo(tmp_path / str(k), {**RULES, "hold": hold}), NOW)
        assert any("sauna sospesa" in x for x in out), hold
    assert any("finché non viene tolto" in x for x in g.check(rito(), repo(tmp_path / "s", {**RULES, "hold": {}}), NOW))
    past = repo(tmp_path / "p", {**RULES, "hold": {"until": "2026-11-10"}})
    assert g.check(rito(), past, NOW) == []
    assert g.check(rito(), repo(tmp_path / "n", {**RULES, "hold": None}), NOW) == []


def test_soglia_giudicata_va_dichiarata(tmp_path):
    root = repo(tmp_path, {**RULES, "judgement": [{"id": "uscita-lunga", "text": "nessuna uscita lunga con sudorazione nelle 24-36 h"}]})
    assert any("non dichiarata" in x for x in g.check(rito(), root, NOW))
    no = rito(threshold=[{"id": "uscita-lunga", "ok": False, "note": "ieri 5 h in montagna"}])
    assert any("non passata" in x and "5 h in montagna" in x for x in g.check(no, root, NOW))
    assert any("non passata" in x for x in g.check(rito(threshold=[{"id": "uscita-lunga", "ok": "true"}]), root, NOW))
    assert g.check(rito(threshold=[{"id": "uscita-lunga", "ok": True}]), root, NOW) == []


@pytest.mark.parametrize("bad", [
    {"heat_round_max_min": "15"}, {"heat_total_max_min": None}, {"heat_round_max_min": 0}, {"temp_max_c": "70"},
    {"rounds_max": "2"}, {"rounds_max": 1.5}, {"rounds_max": True}, {"cold": "no"}, {"cold": {"allowed": "false"}},
    {"cold": {"max_min": "5"}}, {"cold": {"not_after": "19.00"}}, {"latest_end": "20.00"}, {"latest_end": "25:99"},
    {"earliest_start": 7}, {"hold": "sì"}, {"hold": {"until": "01/12/2026"}}, {"hold": {"until": "2026-13-45"}},
    {"judgement": {"id": "x"}}, {"judgement": [{"text": "senza id"}]}, {"min_hours_between": "20"},
    {"wod_peak_max_bpm": 0}, {"rest_ratio_min": "1"},
])
def test_regole_scritte_male_chiudono_la_soglia(tmp_path, bad):
    """Un tetto del tipo sbagliato non spegne il suo controllo: chiude tutto."""
    out = g.check(rito(), repo(tmp_path, {**RULES, **bad}), NOW)
    assert len(out) == 1 and "rules.json" in out[0] and "la soglia resta chiusa" in out[0], (bad, out)


def test_senza_regole_la_soglia_resta_chiusa(tmp_path):
    assert "manca data/sauna/rules.json" in g.check(rito(), repo(tmp_path, None), NOW)[0]
    assert "illeggibile" in g.check(rito(), repo(tmp_path / "x", "{rotto"), NOW)[0]
    assert "deve essere un oggetto" in g.check(rito(), repo(tmp_path / "l", "[1]"), NOW)[0]
    minimal = repo(tmp_path / "m", {})                        # file vuoto ma valido: valgono i prudenti (12′, 24′, 80 °C)
    out = g.check(rito(), minimal, NOW)
    assert any("tetto è 12′ a passaggio" in x for x in out) and any("il tetto è 24′" in x for x in out)


def test_cli(tmp_path):
    root = repo(tmp_path)
    f = tmp_path / "oggi.rito.json"
    r = rito(date=datetime.now(g.tz()).date().isoformat())
    moment(r, "calore-1")["max_s"] = 3000
    f.write_text(json.dumps(r))
    script = str(HERE.parent / "rito_guard.py")
    res = subprocess.run([sys.executable, script, str(f)], capture_output=True, text=True,
                         env={"WELLNESS_DATA": str(root), "PATH": "/usr/bin"})
    assert res.returncode == 3 and "soglia resta chiusa" in res.stderr and "tetto" in res.stderr
    res = subprocess.run([sys.executable, script, str(f)], capture_output=True, text=True,
                         env={"WELLNESS_DATA": str(tmp_path / "altrove"), "PATH": "/usr/bin"})
    assert res.returncode == 3 and "non è un repo dati" in res.stderr


def test_riapertura_a_meta_rito(tmp_path):
    """Riaprire il bottone alle 19:10 di un rito cominciato alle 18:15: l'ora di fine non si ricalcola."""
    root = repo(tmp_path, {**RULES, "min_hours_between": 20,
                           "judgement": [{"id": "uscita-lunga", "text": "nessuna uscita lunga"}]})
    r = rito(threshold=[{"id": "uscita-lunga", "ok": True}])
    late = datetime(2026, 11, 19, 19, 10, tzinfo=g.tz())
    assert any("potrebbe finire" in x for x in g.check(r, root, late))
    assert g.check(r, root, late, reopen=True) == []
    moment(r, "calore-1")["max_s"] = 3000                     # ma i tetti valgono sempre
    assert any("tetto" in x for x in g.check(r, root, late, reopen=True))
    assert any("non dichiarata" in x for x in g.check(rito(), root, late, reopen=True))
    assert any("riscrive per oggi" in x for x in g.check(rito(date="2026-11-18"), root, late, reopen=True))
