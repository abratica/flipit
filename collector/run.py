"""FlipIt daily collector. Run with: python -m collector.run

Environment:
  TM_KEY, SEATGEEK_ID, SEATGEEK_SECRET, SPOTIFY_ID, SPOTIFY_SECRET   API keys (GitHub secrets)
  FLIPIT_MODE   "full" (default): nationwide, 6 months, saved to data/
                "test": Massachusetts only, 30 days, saved to data_test/ (not committed)
  SPOTIFY_MINUTES   time budget for Spotify lookups (default 90; the backlog carries over)
"""
import datetime as dt
import json
import os
import sys
import time
from zoneinfo import ZoneInfo

from . import score, seatgeek, spotify, ticketmaster
from .match import match
from .store import Store
from .util import log

ET = ZoneInfo("America/New_York")


def main():
    mode = os.environ.get("FLIPIT_MODE", "full")
    test = mode == "test"
    started = time.monotonic()
    today = dt.datetime.now(ET).date()
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    end = now + dt.timedelta(days=30 if test else 183)
    states = ["MA"] if test else ticketmaster.STATES
    store = Store("data_test" if test else "data")
    health = {"mode": mode, "sources": {}, "notes": []}

    tm_events, sg_events = {}, {}
    try:
        tm_events, health["sources"]["ticketmaster"] = ticketmaster.sweep(os.environ["TM_KEY"], states, now, end)
    except Exception as e:
        health["sources"]["ticketmaster"] = {"ok": False, "error": str(e)[:300]}
    try:
        sg_events, health["sources"]["seatgeek"] = seatgeek.sweep(
            os.environ["SEATGEEK_ID"], os.environ.get("SEATGEEK_SECRET", ""), states, now, end)
    except Exception as e:
        health["sources"]["seatgeek"] = {"ok": False, "error": str(e)[:300]}

    if not tm_events and not sg_events:
        log("no events from either source; nothing saved")
        print(json.dumps(health, indent=1))
        sys.exit(1)

    pairs = match(tm_events, sg_events)
    seen = store.upsert(tm_events, sg_events, pairs, today.isoformat())

    queue = store.note_artists(seen, today.isoformat())
    if test:
        queue = queue[:40]
    minutes = float(os.environ.get("SPOTIFY_MINUTES", "5" if test else "90"))
    try:
        sp = spotify.Spotify(os.environ["SPOTIFY_ID"], os.environ["SPOTIFY_SECRET"])
        results = spotify.capture(sp, queue, time.monotonic() + minutes * 60)
        store.save_spotify(results, today.isoformat())
        health["sources"]["spotify"] = sp.info(queued=len(queue), captured=len(results),
                                               backlog=len(queue) - len(results))
        if sp.found and sp.fields_missing == sp.found:
            health["notes"].append("Spotify returned artists but no follower or popularity numbers.")
    except Exception as e:
        health["sources"]["spotify"] = {"ok": False, "error": str(e)[:300]}

    today_rows = store.snapshot(seen, today.isoformat())
    store.save()

    tm_rows = [tm for tm, _ in seen.values() if tm]
    health["face_value_missing_pct"] = (
        round(100 * sum(1 for t in tm_rows if t["face_min"] is None) / len(tm_rows), 1) if tm_rows else None)
    health["match_rate_pct"] = round(100 * len(pairs) / len(tm_events), 1) if tm_events else None
    health["seatgeek_only_shows"] = len(sg_events) - len(pairs)
    health["onsale_time_known_pct"] = (
        round(100 * sum(1 for t in tm_rows if t["onsale_at"]) / len(tm_rows), 1) if tm_rows else None)
    health["run_minutes"] = round((time.monotonic() - started) / 60, 1)
    health["ok"] = all(s.get("ok") for s in health["sources"].values())

    b = score.run(store, today_rows, health, today)
    summary(b, test)
    if test:
        for label, samples in (("ticketmaster event without priceRanges", ticketmaster.SAMPLES),
                               ("seatgeek event", seatgeek.SAMPLES), ("spotify artist", spotify.Spotify.SAMPLES)):
            for ev in samples:
                log(f"SAMPLE {label}: " + json.dumps(ev)[:6000])
    if not health["ok"]:
        sys.exit(1)


def summary(b, test):
    t, h = b["tracking"], b["health"]
    lines = [
        f"## FlipIt {'TEST ' if test else ''}run, {b['date']}",
        f"- Upcoming shows tracked: **{t['upcoming_shows']:,}** ({t['new_shows_today']:,} new)",
        f"- Venues: {t['venues']:,} · Artists: {t['artists']:,}",
        f"- Shows with resale data: {t['shows_with_resale_data']:,}",
        f"- Face value missing: {h.get('face_value_missing_pct')}% · On-sale time known: "
        f"{h.get('onsale_time_known_pct')}% · Ticketmaster/SeatGeek match rate: {h.get('match_rate_pct')}%",
        f"- On-sales this week: {len(b['onsales_this_week'])} · Movers: {len(b['movers'])}",
        f"- Run time: {h.get('run_minutes')} min",
        "",
        "| Source | OK | Calls | Errors | Detail |",
        "|---|---|---|---|---|",
    ]
    for name, s in h["sources"].items():
        detail = {k: v for k, v in s.items() if k not in ("ok", "calls", "errors")}
        lines.append(f"| {name} | {s.get('ok')} | {s.get('calls', '')} | {s.get('errors', '')} | "
                     f"{json.dumps(detail)[:400]} |")
    for n in h["notes"]:
        lines.append(f"\n- {n}")
    if b["movers"]:
        lines += ["", "### Top movers", "| Show | Venue | Date | Face | Ask | Markup | Listings |",
                  "|---|---|---|---|---|---|---|"]
        for m in b["movers"][:10]:
            lines.append(f"| {m['show']} | {m['venue']}, {m['city']} | {m['date']} | {m['face_min']} | "
                         f"{m['ask']} | {m['markup']}x | {m['listings']} |")
    text = "\n".join(lines)
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
