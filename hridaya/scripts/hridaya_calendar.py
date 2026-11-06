#!/usr/bin/env python3.12
"""Il calendario delle review dei coach, tenuto da Hṛdaya.

`data/hridaya/calendar.json` (creato coi default al primo uso):
    {"jobs": {"<id>": {"plugin", "skill", "run_type", "every_days", "weekday"?, "after",
                       "last_run"?: "YYYY-MM-DD"}}}

Default: weekly_review di Coach Longevità e di DreamAgent la domenica dalle 18:00;
monthly_review di entrambi ogni 28 giorni. Un job è dovuto se è passata l'ora `after`,
se oggi è il `weekday` (quando c'è) e se dall'ultimo giro sono passati `every_days`
giorni (o non ha mai girato). Hṛdaya lo fa partire con la skill dello specialista,
consegna l'esito firmato (dal cancello) e lo segna fatto.

    hridaya_calendar.py due [--plugins coach-longevita,dream-agent]
    hridaya_calendar.py done <job-id> [--date YYYY-MM-DD]
    hridaya_calendar.py list
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DEFAULT_JOBS = {
    "coach-longevita:weekly_review": {"plugin": "coach-longevita", "skill": "coach-longevita",
                                      "run_type": "weekly_review", "every_days": 7, "weekday": "sun",
                                      "after": "18:00"},
    "dream-agent:weekly_review": {"plugin": "dream-agent", "skill": "dream-agent",
                                  "run_type": "weekly_review", "every_days": 7, "weekday": "sun",
                                  "after": "18:00"},
    "coach-longevita:monthly_review": {"plugin": "coach-longevita", "skill": "coach-longevita",
                                       "run_type": "monthly_review", "every_days": 28, "after": "18:00"},
    "dream-agent:monthly_review": {"plugin": "dream-agent", "skill": "dream-agent",
                                   "run_type": "monthly_review", "every_days": 28, "after": "18:00"},
}


def path() -> Path:
    return Path(os.environ.get("WELLNESS_DATA") or Path.cwd()) / "data" / "hridaya" / "calendar.json"


def load() -> dict:
    try:
        cal = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cal = {}
    jobs = cal.setdefault("jobs", {})
    for k, v in DEFAULT_JOBS.items():
        jobs.setdefault(k, dict(v))
    return cal


def save(cal: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cal, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def due(now: datetime, cal: dict | None = None, plugins: set[str] | None = None) -> list[dict]:
    cal = cal or load()
    out = []
    for jid, j in cal["jobs"].items():
        if plugins is not None and j.get("plugin") not in plugins:
            continue
        if now.strftime("%H:%M") < j.get("after", "00:00"):
            continue
        if j.get("weekday") and WEEKDAYS[now.weekday()] != j["weekday"]:
            continue
        last = j.get("last_run")
        if last:
            gap = (now.date() - date.fromisoformat(last)).days
            # settimanale col giorno fisso: basta non averla fatta negli ultimi 6 giorni
            need = j["every_days"] - 1 if j.get("weekday") else j["every_days"]
            if gap < need:
                continue
        out.append({"id": jid, **j})
    return out


def mark_done(job_id: str, day: str) -> bool:
    cal = load()
    if job_id not in cal["jobs"]:
        return False
    cal["jobs"][job_id]["last_run"] = day
    save(cal)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Calendario delle review dei coach")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("due")
    d.add_argument("--plugins", default=None, help="solo questi plugin (installati)")
    m = sub.add_parser("done")
    m.add_argument("job")
    m.add_argument("--date", default=date.today().isoformat())
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "due":
        plugins = set(a.plugins.split(",")) if a.plugins else None
        print(json.dumps(due(datetime.now(), plugins=plugins), ensure_ascii=False, indent=1))
    elif a.cmd == "done":
        if not mark_done(a.job, a.date):
            print(f"job sconosciuto: {a.job}", file=sys.stderr)
            return 1
        print(f"OK {a.job} {a.date}")
    else:
        print(json.dumps(load(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
