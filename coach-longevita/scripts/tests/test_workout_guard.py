"""workout_guard: divieti personali (no_rules) e limiti della fase di vita bloccano la seduta."""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import workout_guard as g

SCRIPT = Path(__file__).resolve().parent.parent / "workout_guard.py"


def repo(tmp_path, no_rules=None, life_phase=None):
    (tmp_path / "data" / "coach-longevita").mkdir(parents=True)
    (tmp_path / "data" / "coach-longevita" / "state.json").write_text(
        json.dumps({"preference_book": {"no": ["testo libero"], "no_rules": no_rules or []}}))
    (tmp_path / "data" / "profile.json").write_text(json.dumps({"life_phase": life_phase} if life_phase else {}))
    return tmp_path


def wod(*blocks):
    return {"title": "t", "blocks": list(blocks)}


RUN_RULE = [{"match": ["running", "run"], "max_min": 30, "why": "ginocchia"}]


def test_corsa_breve_passa_lunga_no(tmp_path):
    r = repo(tmp_path, RUN_RULE)
    short = wod({"type": "amrap", "name": "WOD", "duration_s": 900,
                 "exercises": [{"name": "Run", "reps": "400 m", "img": "running"}, {"name": "Air Squat"}]})
    assert g.check(short, r) == []
    long = wod({"type": "timed", "name": "Z2", "exercises": [{"name": "Run", "time_s": 3600, "img": "running"}]})
    out = g.check(long, r)
    assert len(out) == 1 and "60′ in tutto, oltre 30′" in out[0] and "ginocchia" in out[0]
    by_km = wod({"type": "timed", "name": "Z2", "exercises": [{"name": "Run 8 km"}]})
    assert g.check(by_km, r)                                  # 8 km ≈ 48′ alla stima prudente


def test_durata_ignota_passa(tmp_path):
    r = repo(tmp_path, RUN_RULE)
    mixed = wod({"type": "emom", "name": "E", "minutes": 40,
                 "exercises": [{"name": "Run", "img": "running"}, {"name": "Burpee"}]})
    assert g.check(mixed, r) == []                            # blocco misto: non si attribuiscono i 40′


def test_divieto_secco_per_nome(tmp_path):
    r = repo(tmp_path, [{"match": ["double-under"], "why": "tibie"}])
    w = wod({"type": "emom", "name": "E", "minutes": 10, "exercises": [{"name": "Double Under", "reps": 30}]})
    assert "Double Under vietato" in g.check(w, r)[0]


def test_fase_di_vita_pavimento_pelvico(tmp_path):
    jumps = wod({"type": "amrap", "name": "W", "duration_s": 600,
                 "exercises": [{"name": "Box Jump", "reps": 10}, {"name": "Deadlift", "reps": 5}]})
    r = repo(tmp_path, life_phase={"stage": "perimenopausa", "pelvic_floor": {"symptoms": ["perdite con salti"]}})
    out = g.check(jumps, r)
    assert len(out) == 1 and "Box Jump" in out[0] and "fase di vita" in out[0]


def test_via_libera_della_fisioterapista(tmp_path):
    jumps = wod({"type": "amrap", "name": "W", "duration_s": 600, "exercises": [{"name": "Box Jump"}]})
    r = repo(tmp_path, life_phase={"pelvic_floor": {"symptoms": ["perdite"], "cleared_by_physio": True}})
    assert g.check(jumps, r) == []


def test_postparto_e_gravidanza(tmp_path):
    run = wod({"type": "timed", "name": "R", "exercises": [{"name": "Run", "time_s": 600}]})
    r = repo(tmp_path, life_phase={"stage": "postpartum", "postpartum_since": "2026-10-01"})
    assert g.check(run, r, today=date(2026, 11, 14))          # 6 settimane: niente corsa
    assert g.check(run, r, today=date(2027, 2, 1)) == []      # oltre 12 settimane: decide il coach
    p = tmp_path / "preg"
    p.mkdir()
    assert "gravidanza" in g.check(run, repo(p, life_phase={"stage": "gravidanza"}))[0]


def test_senza_fase_di_vita_nessun_limite(tmp_path):
    w = wod({"type": "amrap", "name": "W", "duration_s": 600, "exercises": [{"name": "Burpee"}, {"name": "Crunch"}]})
    assert g.check(w, repo(tmp_path)) == []


def test_cli_exit_3(tmp_path):
    r = repo(tmp_path, RUN_RULE)
    f = tmp_path / "x.player.json"
    f.write_text(json.dumps(wod({"type": "timed", "name": "Z2", "exercises": [{"name": "Run", "time_s": 3600}]})))
    res = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True,
                         env={"WELLNESS_DATA": str(r), "PATH": "/usr/bin"})
    assert res.returncode == 3 and "Seduta bloccata" in res.stderr


def test_plurali_qualificatori_e_alias(tmp_path):
    r = repo(tmp_path, RUN_RULE, life_phase={"pelvic_floor": {"symptoms": ["perdite"]},
                                             "bone": {"vertebral_fracture": True}})
    for name in ("Burpees", "Box Jumps", "Double-Unders", "DUs", "Bar-Facing Burpee",
                 "Sit-ups", "AbMat Sit-up", "Hanging Toes-to-Bar", "T2B"):
        w = wod({"type": "emom", "name": "E", "minutes": 10, "exercises": [{"name": name}]})
        assert g.check(w, r), name
    for name in ("Easy Run", "Treadmill Run", "Zone 2 Run", "Jogging"):
        w = wod({"type": "timed", "name": "Z2", "exercises": [{"name": name, "time_s": 3600}]})
        assert g.check(w, repo(tmp_path / name.replace(" ", ""), RUN_RULE + [{"match": ["jog"], "max_min": 30}])), name
    ok = wod({"type": "sets", "name": "S", "rounds": 3, "exercises": [{"name": "Deadlift"}, {"name": "Box Step-up"},
                                                                      {"name": "Strict Press"}]})
    assert g.check(ok, r) == []


def test_durate_dalla_struttura_del_blocco(tmp_path):
    r = repo(tmp_path, RUN_RULE)
    cases = [
        {"type": "amrap", "name": "A", "duration_s": 3600, "exercises": [{"name": "Run", "reps": "400 m"}]},
        {"type": "emom", "name": "E", "minutes": 60, "exercises": [{"name": "Run", "reps": "200 m"}]},
        {"type": "emom", "name": "E", "minutes": 60, "exercises": [{"name": "Run", "time_s": 45}]},
        {"type": "timed", "name": "T", "exercises": [{"name": "Run", "reps": "2 x 5 km"}]},
        {"type": "timed", "name": "T", "exercises": [{"name": "Run", "reps": "60 min"}]},
        {"type": "sets", "name": "S", "rounds": "3", "exercises": [{"name": "Run", "time_s": 900}]},
        {"type": "interval", "name": "I", "work_s": 300, "rounds": 8, "exercises": [{"name": "Run"}, {"name": "Bike"}]},
        {"type": "fortime", "name": "F", "cap_s": 3600, "exercises": [{"name": "Run"}]},
    ]
    for b in cases:
        assert g.check(wod(b), r), b


def test_limite_sulla_seduta_intera(tmp_path):
    r = repo(tmp_path, RUN_RULE)
    b = {"type": "timed", "name": "R", "exercises": [{"name": "Run", "time_s": 1500}]}
    out = g.check(wod(b, dict(b), dict(b)), r)
    assert len(out) == 1 and "75′ in tutto" in out[0]


def test_file_illeggibile_blocca(tmp_path):
    r = repo(tmp_path, RUN_RULE)
    (r / "data" / "coach-longevita" / "state.json").write_text('{"preference_book": {"no_rules": [ ,]}}')
    w = wod({"type": "timed", "name": "T", "exercises": [{"name": "Air Squat", "time_s": 60}]})
    assert "illeggibile" in g.check(w, r)[0]


def test_fase_di_vita_scritta_a_parole(tmp_path):
    w = wod({"type": "timed", "name": "R", "exercises": [{"name": "Run", "time_s": 600}]})
    for i, stage in enumerate(("Gravidanza (2° trimestre)", "incinta", "pregnant")):
        assert g.check(w, repo(tmp_path / str(i), life_phase={"stage": stage})), stage
    assert g.check(w, repo(tmp_path / "pp", life_phase={"stage": "postpartum"}))   # senza data: prudenza
    assert g.check(w, repo(tmp_path / "s", life_phase="gravidanza"))              # stringa al posto dell'oggetto


def test_regola_scritta_male(tmp_path):
    r = repo(tmp_path, [{"match": "running", "max_min": "30", "why": "ginocchia"}])
    w = wod({"type": "timed", "name": "Z2", "exercises": [{"name": "Running", "time_s": 3600}]})
    assert g.check(w, r)
