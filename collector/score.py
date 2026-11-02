"""Turn the daily snapshots into show outcomes, venue scorecards and the app's morning brief."""
import datetime as dt
import glob
import json
import os
import statistics
from collections import defaultdict

from .store import read_csv, write_csv
from .util import num

# Fee assumptions: what it costs to buy at face, and what a resale seller keeps.
BUY_FEE = 0.20   # primary service fees on top of face value
SELL_FEE = 0.15  # marketplace seller fee taken out of the resale price
BREAKEVEN = round((1 + BUY_FEE) / (1 - SELL_FEE), 2)  # resale ask / face needed to break even

AFTER_ONSALE = [1, 3, 7, 14, 30]
BEFORE_SHOW = [30, 14, 7, 3, 1, 0]
PRIMARY = [7, 3, 14, 1]  # the venue scorecard uses the first of these "days before show" that exists
TIERS = [(20, "confirmed"), (10, "ranked"), (5, "provisional")]

OUTCOME_FIELDS = (["show_id", "venue_key", "artist_key", "date", "onsale_at", "face_min", "completed"]
                  + [f"after_{d}" for d in AFTER_ONSALE] + [f"before_{d}" for d in BEFORE_SHOW]
                  + ["primary_markup", "primary_checkpoint", "profitable"])
VENUE_STAT_FIELDS = ["venue_key", "name", "city", "state", "capacity", "capacity_source", "tier",
                     "completed", "hits", "hit_rate", "avg_markup", "median_markup", "upcoming",
                     "upcoming_avg_markup"]


def _ask(r):
    """Cheapest resale ask before buyer fees, or None when nothing is listed."""
    if not r or (num(r.get("listing_count")) or 0) <= 0:
        return None
    return num(r.get("lowest_base")) or num(r.get("lowest"))


def load_history(root):
    hist = defaultdict(dict)
    files = sorted(glob.glob(os.path.join(root, "snapshots", "*.csv.gz")))
    for path in files:
        for r in read_csv(path):
            hist[r["show_id"]][r["date"]] = r
    return hist, len(files)


def _on(h, day):
    for delta in (0, -1, 1):
        r = h.get((day + dt.timedelta(days=delta)).isoformat())
        if r:
            return r
    return None


def _tier(n):
    for floor, name in TIERS:
        if n >= floor:
            return name
    return "tracking"


def _r2(v):
    return None if v is None else round(v, 2)


def outcomes(shows, hist, today):
    out = []
    for sid, h in hist.items():
        show = shows.get(sid)
        face = num(show.get("face_min")) if show else None
        if not show or not face:
            continue
        show_day = dt.date.fromisoformat(show["date"])
        row = {"show_id": sid, "venue_key": show["venue_key"], "artist_key": show["artist_key"],
               "date": show["date"], "onsale_at": show.get("onsale_at", ""), "face_min": face,
               "completed": "yes" if show_day < today else "no"}
        onsale = show.get("onsale_at", "")[:10]
        for d in AFTER_ONSALE:
            ask = _ask(_on(h, dt.date.fromisoformat(onsale) + dt.timedelta(days=d))) if onsale else None
            row[f"after_{d}"] = _r2(ask / face) if ask else None
        for d in BEFORE_SHOW:
            ask = _ask(_on(h, show_day - dt.timedelta(days=d)))
            row[f"before_{d}"] = _r2(ask / face) if ask else None
        for d in PRIMARY:
            if row[f"before_{d}"] is not None:
                row["primary_markup"], row["primary_checkpoint"] = row[f"before_{d}"], f"before_{d}"
                row["profitable"] = "yes" if row[f"before_{d}"] >= BREAKEVEN else "no"
                break
        out.append(row)
    return out


def venue_stats(venues, shows, outs, today_rows):
    done = defaultdict(list)
    for o in outs:
        if o["completed"] == "yes" and o.get("primary_markup") is not None:
            done[o["venue_key"]].append(o["primary_markup"])
    live = defaultdict(list)
    for r in today_rows:
        show = shows.get(r["show_id"])
        face, ask = num(show.get("face_min")) if show else None, _ask(r)
        if show:
            live[show["venue_key"]].append(ask / face if face and ask else None)
    stats = []
    for key, v in venues.items():
        m = done.get(key, [])
        up = [x for x in live.get(key, []) if x is not None]
        hits = sum(1 for x in m if x >= BREAKEVEN)
        stats.append({
            "venue_key": key, "name": v.get("name"), "city": v.get("city"), "state": v.get("state"),
            "capacity": v.get("capacity"), "capacity_source": v.get("capacity_source"),
            "tier": _tier(len(m)), "completed": len(m), "hits": hits,
            "hit_rate": _r2(hits / len(m)) if m else None,
            "avg_markup": _r2(statistics.mean(m)) if m else None,
            "median_markup": _r2(statistics.median(m)) if m else None,
            "upcoming": len(live.get(key, [])),
            "upcoming_avg_markup": _r2(statistics.mean(up)) if up else None,
        })
    return stats


def _show_card(show, extra):
    return {"show": show.get("name"), "artist": show.get("artist"), "venue": show.get("venue_name"),
            "city": show.get("city"), "state": show.get("state"), "date": show.get("date"),
            "face_min": num(show.get("face_min")), "url": show.get("tm_url") or show.get("sg_url"), **extra}


def brief(store, today_rows, hist, outs, vstats, health, days_collected, today):
    shows, artists = store.shows, store.artists
    now = dt.datetime.now(dt.timezone.utc)
    week = (now + dt.timedelta(days=7)).isoformat()
    seen_ids = {r["show_id"] for r in today_rows}

    onsales = []
    for sid in seen_ids:
        s = shows[sid]
        if s.get("onsale_at") and now.isoformat() <= s["onsale_at"] <= week:
            a = artists.get(s.get("artist_key"), {})
            onsales.append(_show_card(s, {"onsale_at": s["onsale_at"],
                                          "spotify_followers": num(a.get("spotify_followers")),
                                          "city_dates": num(s.get("city_dates"))}))
    onsales.sort(key=lambda x: x["onsale_at"])

    movers = []
    for r in today_rows:
        s = shows[r["show_id"]]
        face, ask = num(s.get("face_min")), _ask(r)
        if face and ask and (num(r.get("listing_count")) or 0) >= 3:
            movers.append(_show_card(s, {"ask": ask, "markup": round(ask / face, 2),
                                         "listings": int(num(r["listing_count"]))}))
    movers.sort(key=lambda x: -x["markup"])

    dropping = []
    for r in today_rows:
        before = _on(hist.get(r["show_id"], {}), today - dt.timedelta(days=3))
        then, nowc = num(before.get("listing_count")) if before else None, num(r.get("listing_count"))
        if then and then >= 20 and nowc is not None and before["date"] != r["date"]:
            drop = (then - nowc) / then
            if drop >= 0.2:
                dropping.append(_show_card(shows[r["show_id"]], {"listings_then": int(then),
                                                                 "listings_now": int(nowc),
                                                                 "drop": round(drop, 2)}))
    dropping.sort(key=lambda x: -x["drop"])

    rank = {"confirmed": 0, "ranked": 1, "provisional": 2}
    board = [v for v in vstats if v["tier"] in rank]
    board.sort(key=lambda v: (rank[v["tier"]], -(v["hit_rate"] or 0), -(v["avg_markup"] or 0)))
    almost = sorted([v for v in vstats if v["tier"] == "tracking" and v["completed"]],
                    key=lambda v: -v["completed"])

    return {
        "generated_at": now.isoformat(), "date": today.isoformat(), "days_collected": days_collected,
        "breakeven_markup": BREAKEVEN,
        "tracking": {
            "upcoming_shows": len(today_rows), "venues": len(store.venues), "artists": len(artists),
            "new_shows_today": store.new_shows, "new_venues_today": store.new_venues,
            "shows_with_resale_data": sum(1 for r in today_rows if _ask(r)),
            "completed_shows_scored": sum(1 for o in outs if o["completed"] == "yes" and o.get("primary_markup")),
        },
        "onsales_this_week": onsales[:30],
        "movers": movers[:15],
        "listings_dropping": dropping[:10],
        "venue_leaderboard": board[:25],
        "venues_closest_to_ranking": almost[:10],
        "health": health,
    }


def run(store, today_rows, health, today):
    hist, days_collected = load_history(store.root)
    outs = outcomes(store.shows, hist, today)
    write_csv(store.path("outcomes.csv"), outs, OUTCOME_FIELDS)
    vstats = venue_stats(store.venues, store.shows, outs, today_rows)
    write_csv(store.path("venue_stats.csv"), sorted(vstats, key=lambda v: v["venue_key"]), VENUE_STAT_FIELDS)
    b = brief(store, today_rows, hist, outs, vstats, health, days_collected, today)
    os.makedirs(store.path("app"), exist_ok=True)
    with open(store.path("app", "brief.json"), "w") as f:
        json.dump(b, f, indent=1)
    keep = [v for v in vstats if v["upcoming"] or v["completed"]]
    with open(store.path("app", "venues.json"), "w") as f:
        json.dump(keep, f, separators=(",", ":"))
    return b
