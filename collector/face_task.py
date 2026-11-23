"""Helpers for the face-value check, run by Claude in Chrome on Ticketmaster event pages (signed out).

  python -m collector.face_task prepare [N]
      prints the worklist as JSON lines: up to N (default 40) upcoming shows at panel venues
      (data/panel.csv) that have a Ticketmaster link, are already on sale, and have no face value yet:
      shows that went on sale in the last 14 days first (newest first), then the rest by show date.
      Shows not on sale yet are left for a later run. New shows the collector adds each morning join automatically.

  python -m collector.face_task record face_results.jsonl
      appends the results to data/face/observations.csv (one row per price tier seen, every reading kept)
      and updates data/face/status.csv (one row per show: done / retry / no_price)

Each line of face_results.jsonl is one show:
  {"show_id": "...", "tm_url": "...", "status": "ok" | "retry" | "no_price",
   "tiers": [{"label": "Section 101", "price": 89.5, "fees_included": false}, ...],
   "page_min": 59.0, "page_max": 250.0, "note": "..."}
Only standard tickets go in tiers: no Platinum, VIP, packages or resale.
"""
import datetime as dt
import json
import os
import re
import sys

from .store import read_csv, write_csv

ROOT = "data"
OBS_FIELDS = ["seen_at", "show_id", "tier", "price", "fees_included", "tm_url"]
STATUS_FIELDS = ["show_id", "status", "face_min", "face_max", "first_seen_at", "last_checked_at", "tries", "note"]
MAX_TRIES = 3


def _path(*p):
    return os.path.join(ROOT, "face", *p)


def _money(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[\d,]+(?:\.\d+)?", str(v))
    return float(m.group(0).replace(",", "")) if m else None


def prepare(n=40):
    today = dt.date.today().isoformat()
    panel = {r["venue_key"] for r in read_csv(os.path.join(ROOT, "panel.csv"))}
    status = {r["show_id"]: r for r in read_csv(_path("status.csv"))}
    todo = []
    for r in read_csv(os.path.join(ROOT, "shows.csv")):
        if r["venue_key"] not in panel or not r.get("tm_url") or r["date"] < today:
            continue
        if r.get("status") in ("offsale", "cancelled") or r.get("face_min"):
            continue
        s = status.get(r["show_id"])
        if s and (s["status"] in ("done", "no_price") or int(s.get("tries") or 0) >= MAX_TRIES):
            continue
        todo.append(r)
    # not on sale yet: leave it for a later run instead of spending a try
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    todo = [r for r in todo if (r.get("onsale_at") or "") <= now]
    # just went on sale first (their first price is the cleanest face value), then the backlog by show date
    recent = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)).isoformat(timespec="seconds")
    fresh = sorted((r for r in todo if (r.get("onsale_at") or "") >= recent), key=lambda r: r["onsale_at"], reverse=True)
    backlog = sorted((r for r in todo if (r.get("onsale_at") or "") < recent), key=lambda r: r["date"])
    todo = fresh + backlog
    for r in todo[:n]:
        print(json.dumps({"show_id": r["show_id"], "artist": r["artist"], "name": r["name"],
                          "venue": r["venue_name"], "city": r["city"], "state": r["state"],
                          "date": r["date"], "onsale_at": r.get("onsale_at", ""), "tm_url": r["tm_url"]}))


def record(path):
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    obs = read_csv(_path("observations.csv"))
    status = {r["show_id"]: r for r in read_csv(_path("status.csv"))}
    counts = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            sid, st = r["show_id"], r.get("status", "")
            prices = []
            for t in r.get("tiers") or []:
                p = _money(t.get("price"))
                if p is None:
                    continue
                prices.append(p)
                obs.append({"seen_at": now, "show_id": sid, "tier": t.get("label", ""), "price": p,
                            "fees_included": "yes" if t.get("fees_included") else "no", "tm_url": r.get("tm_url", "")})
            if st == "ok" and not prices:
                st = "retry"
            old = status.get(sid, {})
            status[sid] = {
                "show_id": sid, "status": "done" if st == "ok" else st,
                "face_min": min(prices) if prices else old.get("face_min", ""),
                "face_max": max(prices) if prices else old.get("face_max", ""),
                "first_seen_at": old.get("first_seen_at") or (now if prices else ""),
                "last_checked_at": now, "tries": int(old.get("tries") or 0) + 1,
                "note": (r.get("note") or "")[:200],
            }
            counts[st] = counts.get(st, 0) + 1
    write_csv(_path("observations.csv"), obs, OBS_FIELDS)
    write_csv(_path("status.csv"), sorted(status.values(), key=lambda r: r["show_id"]), STATUS_FIELDS)
    done = sum(1 for r in status.values() if r["status"] == "done")
    print(f"recorded {sum(counts.values())} shows {counts}; {done} panel shows have face value")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "prepare":
        prepare(int(sys.argv[2]) if len(sys.argv) >= 3 else 40)
    elif len(sys.argv) >= 3 and sys.argv[1] == "record":
        record(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(2)
