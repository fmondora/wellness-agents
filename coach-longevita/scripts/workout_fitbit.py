#!/usr/bin/env python3.12
"""Incrocia il log del workout player con FC e passi del Fitbit, blocco per blocco.

    python3.12 workout_fitbit.py YYYY-MM-DD [--json] [--file PATH.session.json]

Repo dati: cwd o WELLNESS_DATA. FC e passi dal plugin health (health_sync, meditation_detect).

FC: rollup a 10 s sulla finestra della seduta (l'API Google Health accetta
finestre sotto il minuto; verificato il 2026-11-06). Se fallisce, ricade sulla
FC al minuto di meditation_detect._fetch_minutes. Passi: sempre al minuto
(il dato grezzo è per minuto: a 10 s finisce tutto nel primo bucket).
SpO2 diurna il Fitbit non la dà: non c'è.

Scrive data/coach-longevita/daily/YYYY-MM-DD.session-hr.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("WELLNESS_DATA") or Path.cwd())
DAILY = ROOT / "data" / "coach-longevita" / "daily"
TZ = ZoneInfo(os.environ.get("WELLNESS_TZ", "Europe/Rome"))
HR_RES = 10
THRESHOLDS = (120, 150)
END_EVENTS = {"end", "stop"}
ENTRY_EVENTS = {"start", "step"}


# --- segmentazione del log ----------------------------------------------------

def segments(session: dict) -> list[dict]:
    """Un segmento per ogni passo vissuto: dall'ingresso al passo successivo (o fine).
    Uno stop seguito da una continuazione chiude solo il segmento: il buco non conta."""
    evs = sorted(session["events"], key=lambda e: datetime.fromisoformat(e["t"]))
    marks = [(datetime.fromisoformat(e["t"]), e) for e in evs if e["e"] in ENTRY_EVENTS | END_EVENTS]
    out = []
    for (t, e), (t2, _) in zip(marks, marks[1:]):
        if e["e"] == "end":
            break
        if e["e"] == "stop":
            continue
        out.append({"step": e["step"], "block": e.get("block"), "block_name": e.get("block_name"),
                    "kind": e.get("kind"), "label": e.get("label"), "start": t, "end": t2})
    return out


# --- statistiche ----------------------------------------------------------------

def stats(a: datetime, b: datetime, hr: list[dict], res_s: int, steps: dict[datetime, int],
          windows: list[tuple[datetime, datetime]] | None = None) -> dict:
    """hr: [{t, avg, max, min}] a passo res_s; steps: {inizio minuto: passi}.
    windows: finestre effettive dentro [a, b] (seduta ripresa dopo uno stop: il buco non conta)."""
    windows = windows or [(a, b)]
    win = [p for p in hr if any(x <= p["t"] < y for x, y in windows)]
    out: dict = {"start": a.isoformat(timespec="seconds"), "end": b.isoformat(timespec="seconds"),
                 "duration_s": round(sum((y - x).total_seconds() for x, y in windows))}
    if win:
        out["hr_avg"] = round(sum(p["avg"] for p in win) / len(win), 1)
        out["hr_max"] = round(max(p.get("max") or p["avg"] for p in win))
        out["hr_min"] = round(min(p.get("min") or p["avg"] for p in win))
        for thr in THRESHOLDS:
            out[f"min_over_{thr}"] = round(sum(res_s for p in win if p["avg"] > thr) / 60, 1)
    else:
        out.update(hr_avg=None, hr_max=None, hr_min=None, **{f"min_over_{t}": None for t in THRESHOLDS})
    tot = 0.0
    for m, n in steps.items():
        for x, y in windows:
            ov = (min(y, m + timedelta(minutes=1)) - max(x, m)).total_seconds()
            if ov > 0:
                tot += n * ov / 60
    out["steps"] = round(tot)
    return out


def _windows(segs: list[dict]) -> list[tuple[datetime, datetime]]:
    """Segmenti contigui fusi in finestre: restano separati solo dove c'è un buco."""
    out: list[list[datetime]] = []
    for s in segs:
        if out and s["start"] <= out[-1][1]:
            out[-1][1] = max(out[-1][1], s["end"])
        else:
            out.append([s["start"], s["end"]])
    return [(x, y) for x, y in out]


def aggregate(session: dict, hr: list[dict], res_s: int, steps: dict[datetime, int]) -> dict:
    segs = segments(session)
    if not segs:
        raise ValueError("nessun passo nel log")
    rows = []
    for s in segs:
        r = {"step": s["step"], "block": s["block"], "block_name": s["block_name"], "kind": s["kind"],
             "label": s["label"]}
        r.update(stats(s["start"], s["end"], hr, res_s, steps))
        rows.append(r)
    blocks = []
    for b in sorted({s["block"] for s in segs if s["block"] is not None}):
        mine = [s for s in segs if s["block"] == b and s["kind"] != "prep"]
        if not mine:
            blocks.append({"block": b, "block_name": session["blocks"][b] if b < len(session["blocks"]) else None,
                           "skipped": True})
            continue
        r = {"block": b, "block_name": mine[0]["block_name"]}
        r.update(stats(mine[0]["start"], mine[-1]["end"], hr, res_s, steps, _windows(mine)))
        blocks.append(r)
    whole = stats(segs[0]["start"], segs[-1]["end"], hr, res_s, steps, _windows(segs))
    if len(session.get("segments") or []) > 1:
        whole["parts"] = len(session["segments"])
    return {"session": whole, "blocks": blocks, "steps": rows}


# --- dati Fitbit ------------------------------------------------------------------

def _utc(x: datetime) -> str:
    return x.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_hr_fine(a: datetime, b: datetime, res_s: int = HR_RES) -> list[dict] | None:
    """FC a res_s secondi dall'API (a blocchi di 2 h). None se rete/token falliscono."""
    try:
        sys.path.insert(0, str(SCRIPTS))
        from _plugins import import_from
        health_sync = import_from("health", "health_sync")
        client = health_sync.HealthClient(ROOT)
        pts = []
        cur = a
        while cur < b:
            nxt = min(b, cur + timedelta(hours=2))
            pts += client.rollup("heart-rate", _utc(cur), _utc(nxt), res_s).get("rollupDataPoints") or []
            cur = nxt
    except Exception as e:  # noqa: BLE001
        print(f"(FC a {res_s}s non disponibile: {e}; uso il minuto)", file=sys.stderr)
        return None
    out = []
    for p in pts:
        h = p.get("heartRate") or {}
        if h.get("beatsPerMinuteAvg") is None:
            continue
        out.append({"t": datetime.fromisoformat(p["startTime"].replace("Z", "+00:00")).astimezone(TZ),
                    "avg": float(h["beatsPerMinuteAvg"]), "max": h.get("beatsPerMinuteMax"),
                    "min": h.get("beatsPerMinuteMin")})
    return sorted(out, key=lambda x: x["t"]) or None


def minutes_series(days: list[str]) -> tuple[list[dict], dict[datetime, int]]:
    sys.path.insert(0, str(SCRIPTS))
    from _plugins import import_from
    _fetch_minutes = import_from("health", "meditation_detect")._fetch_minutes
    hr, steps = [], {}
    for day in days:
        mins = _fetch_minutes(day) or {"hr": {}, "steps": {}}
        base = datetime.fromisoformat(day).replace(tzinfo=TZ)
        at = lambda hhmm: base + timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[3:5]))  # noqa: E731
        hr += [{"t": at(k), "avg": v} for k, v in mins.get("hr", {}).items()]
        steps.update({at(k): v for k, v in mins.get("steps", {}).items()})
    return sorted(hr, key=lambda x: x["t"]), steps


# --- output -------------------------------------------------------------------

def _fmt(r: dict) -> str:
    hr = f"FC {r['hr_avg']:.0f} (max {r['hr_max']}, min {r['hr_min']})" if r.get("hr_avg") else "FC —"
    over = (f" · >120 {r['min_over_120']}′ · >150 {r['min_over_150']}′"
            if r.get("min_over_120") is not None else "")
    return f"{r['start'][11:16]}–{r['end'][11:16]} · {hr}{over} · {r['steps']} passi"


def summary(res: dict) -> str:
    s = res["session"]
    lines = [f"Seduta {s['start'][:10]} · {round(s['duration_s'] / 60)}′ · {_fmt(s)}",
             f"FC: {res['source']['hr']} · passi: {res['source']['steps']}", "", "Blocchi:"]
    for b in res["blocks"]:
        lines.append(f"  {b['block_name']}: saltato" if b.get("skipped") else f"  {b['block_name']}: {_fmt(b)}")
    lines += ["", "Passi di lavoro:"]
    for r in res["steps"]:
        if r["kind"] == "work":
            lines.append(f"  {r['label'] or r['step']}: {_fmt(r)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date")
    ap.add_argument("--file", help="session.json specifico (es. YYYY-MM-DD-2.session.json)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--demo", action="store_true", help="analizza anche le sedute demo (di norma ignorate)")
    a = ap.parse_args()
    path = Path(a.file) if a.file else DAILY / f"{a.date}.session.json"
    if not path.exists():
        print(f"Manca {path}", file=sys.stderr)
        return 1
    session = json.loads(path.read_text(encoding="utf-8"))
    if (session.get("demo") or path.name.endswith(".demo.session.json")) and not a.demo:
        print(f"{path.name} è una seduta demo: ignorata (usa --demo per analizzarla).", file=sys.stderr)
        return 1
    segs = segments(session)
    if not segs:
        print("Log senza passi.", file=sys.stderr)
        return 1
    a0, b0 = segs[0]["start"], segs[-1]["end"]
    days = sorted({a0.strftime("%Y-%m-%d"), b0.strftime("%Y-%m-%d")})
    hr_min, steps = minutes_series(days)
    hr = fetch_hr_fine(a0 - timedelta(minutes=1), b0 + timedelta(minutes=1))
    res_s, src = (HR_RES, f"rollup {HR_RES}s") if hr else (60, "rollup 60s")
    res = aggregate(session, hr or hr_min, res_s, steps)
    res = {"date": a0.strftime("%Y-%m-%d"), "session_file": path.name,
           "source": {"hr": src, "steps": "rollup 60s (ripartiti per sovrapposizione)"}, **res}
    out = path.with_name(path.name.replace(".session.json", ".session-hr.json"))
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1, ensure_ascii=False) if a.json else summary(res))
    print(f"\n→ {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
