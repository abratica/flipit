"""Demand signals that don't need resale prices."""
import datetime as dt
from collections import defaultdict

from .util import num

# skip names that are recurring nights rather than tours
_RECURRING = ("tribute", "night", "party", "brunch", "karaoke", "open mic", "bingo", "jam session")


def added_dates(shows, since):
    """'Second show added': an artist with 2-3 dates in a city gets a new date within 10 days of an
    existing one, first seen after `since`. Returns [(original_show, added_show)], newest first.
    The original is the show most likely to have sold out."""
    by = defaultdict(list)
    for s in shows.values():
        if s.get("artist_key"):
            by[(s["artist_key"], s.get("city", "").lower(), s.get("state"))].append(s)
    out = []
    for group in by.values():
        if not 2 <= len(group) <= 3:
            continue
        if any(w in group[0]["artist"].lower() for w in _RECURRING):
            continue
        group.sort(key=lambda s: (s["first_seen"], s["date"]))
        first = group[0]
        for s in group[1:]:
            if s["first_seen"] <= since or s["first_seen"] == first["first_seen"] or s["date"] == first["date"]:
                continue
            gap = abs((dt.date.fromisoformat(s["date"]) - dt.date.fromisoformat(first["date"])).days)
            if gap <= 10:
                out.append((first, s))
    out.sort(key=lambda p: p[1]["first_seen"], reverse=True)
    return out


def climbers(hist, today, days=7):
    """SeatGeek score change over the last `days` days, per show: {show_id: (then, now)}."""
    then_day = (today - dt.timedelta(days=days)).isoformat()
    out = {}
    for sid, h in hist.items():
        dates = sorted(h)
        if not dates:
            continue
        now = num(h[dates[-1]].get("sg_score"))
        earlier = [d for d in dates if d <= then_day]
        then = num(h[earlier[-1]].get("sg_score")) if earlier else None
        if now and then is not None:
            out[sid] = (then, now)
    return out
