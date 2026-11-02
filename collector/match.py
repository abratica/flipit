"""Pair the same show across Ticketmaster and SeatGeek: same date and state, similar venue and artist."""
from collections import defaultdict
from difflib import SequenceMatcher

from .util import jaccard, norm


def _artist_sim(a, b):
    names_a = [n for n in (a.get("all_artists") or a["artist"]).split("; ") if n] or [a["artist"]]
    names_b = [n for n in (b.get("all_artists") or b["artist"]).split("; ") if n] or [b["artist"]]
    best = 0.0
    for x in names_a:
        for y in names_b:
            best = max(best, SequenceMatcher(None, norm(x), norm(y)).ratio())
    # event titles often carry the headliner even when performer lists differ
    best = max(best, SequenceMatcher(None, norm(a["name"]), norm(b["name"])).ratio() * 0.9)
    return best


def _time_close(a, b):
    ta, tb = a.get("time", "")[:5], b.get("time", "")[:5]
    if not ta or not tb:
        return True
    ha, hb = int(ta[:2]) * 60 + int(ta[3:5]), int(tb[:2]) * 60 + int(tb[3:5])
    return abs(ha - hb) <= 120


def match(tm_events, sg_events):
    """Return {tm_id: sg_id}, each SeatGeek event used at most once."""
    by_day = defaultdict(list)
    for sg in sg_events.values():
        by_day[(sg["date"], sg["state"])].append(sg)
    scored = []
    for tm in tm_events.values():
        for sg in by_day.get((tm["date"], tm["state"]), []):
            if not _time_close(tm, sg):
                continue
            venue = jaccard(tm["venue_name"], sg["venue_name"])
            if norm(tm["city"]) == norm(sg["city"]):
                venue = max(venue, 0.3)
            artist = _artist_sim(tm, sg)
            if artist < 0.6 or venue < 0.3:
                continue
            scored.append((0.6 * artist + 0.4 * venue, tm["tm_id"], sg["sg_id"]))
    pairs, used = {}, set()
    for _, tm_id, sg_id in sorted(scored, reverse=True):
        if tm_id in pairs or sg_id in used:
            continue
        pairs[tm_id] = sg_id
        used.add(sg_id)
    return pairs
