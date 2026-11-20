"""Helpers for the daily StubHub check, which runs as a scheduled Claude task using the StubHub connector.

  python -m collector.stubhub_task prepare
      prints the worklist as JSON lines: one show per line, with its StubHub event id if already known

  python -m collector.stubhub_task record results.jsonl
      reads the raw results the task collected and writes:
        data/stubhub/YYYY-MM-DD.csv   one row per watchlist show checked today
        data/stubhub/ids.csv          FlipIt show -> StubHub event id, so later days skip the search

Each line of results.jsonl is one show:
  {"show_id": "...", "stubhub_event_id": "123" or "", "status": "ok" | "not_found" | "no_listings" | "error",
   "min_price": 87.0, "listings": [{"id": "1466...", "price": 134.0, "section": "101", "quantity": "1 ticket"}, ...],
   "matched_name": "...", "matched_venue": "...", "matched_date": "...", "note": "..."}
"""
import datetime as dt
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

from .store import read_csv, write_csv

ROOT = "data"
DAY_FIELDS = ["date", "show_id", "stubhub_event_id", "status", "min_price", "listings_returned",
              "cheapest_price", "cheapest_ids", "cheapest_prices", "checked_at", "note"]
ID_FIELDS = ["show_id", "stubhub_event_id", "matched_name", "matched_venue", "matched_date", "first_matched"]


def _path(*p):
    return os.path.join(ROOT, "stubhub", *p)


def _money(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[\d,]+(?:\.\d+)?", str(v))
    return float(m.group(0).replace(",", "")) if m else None


def prepare():
    ids = {r["show_id"]: r for r in read_csv(_path("ids.csv"))}
    for r in read_csv(os.path.join(ROOT, "watchlist.csv")):
        known = ids.get(r["show_id"], {})
        print(json.dumps({"show_id": r["show_id"], "artist": r["artist"], "event_name": r["name"],
                          "venue": r["venue_name"], "city": r["city"], "state": r["state"],
                          "date": r["date"], "time": r["time"], "reason": r["reason"],
                          "stubhub_event_id": known.get("stubhub_event_id", "")}))


def record(results_path):
    today = dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    ids = {r["show_id"]: r for r in read_csv(_path("ids.csv"))}
    rows = []
    with open(results_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            listings = r.get("listings") or []
            prices = [p for p in (_money(x.get("price")) for x in listings) if p is not None]
            eid = str(r.get("stubhub_event_id") or "")
            if eid and r["show_id"] not in ids:
                ids[r["show_id"]] = {"show_id": r["show_id"], "stubhub_event_id": eid,
                                     "matched_name": r.get("matched_name", ""),
                                     "matched_venue": r.get("matched_venue", ""),
                                     "matched_date": r.get("matched_date", ""), "first_matched": today}
            rows.append({
                "date": today, "show_id": r["show_id"], "stubhub_event_id": eid, "status": r.get("status", ""),
                "min_price": _money(r.get("min_price")), "listings_returned": len(listings),
                "cheapest_price": min(prices) if prices else None,
                "cheapest_ids": ";".join(str(x.get("id", "")) for x in listings),
                "cheapest_prices": ";".join(str(_money(x.get("price"))) for x in listings),
                "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "note": (r.get("note") or "")[:200],
            })
    os.makedirs(_path(), exist_ok=True)
    write_csv(_path(f"{today}.csv"), rows, DAY_FIELDS)
    write_csv(_path("ids.csv"), sorted(ids.values(), key=lambda r: r["show_id"]), ID_FIELDS)
    ok = sum(1 for r in rows if r["status"] == "ok")
    print(f"recorded {len(rows)} shows for {today}: {ok} with prices, {len(ids)} StubHub ids known")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "prepare":
        prepare()
    elif len(sys.argv) >= 3 and sys.argv[1] == "record":
        record(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(2)
