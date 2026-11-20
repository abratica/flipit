"""The daily StubHub watchlist: a mostly stable set of upcoming shows, chosen on purpose.

Four groups, each a quarter of the list:
  second_show  the original date of an artist who just added a nearby date (likely sold out)
  climber      SeatGeek demand score rising fastest over the past week
  onsale_soon  high-demand shows going on sale in the next 10 days (full price lifecycle)
  random       a deterministic random draw of ordinary shows, the comparison group

Shows stay on the list until they happen, so each one builds a price history. Every row records
why it was picked and how big the pool was, so results can be read per group.
"""
import datetime as dt
import hashlib

from .signals import added_dates, climbers
from .store import read_csv, write_csv
from .util import num

SIZE = 60
GROUPS = ["second_show", "climber", "onsale_soon", "random"]
FIELDS = ["show_id", "artist", "name", "venue_name", "city", "state", "date", "time", "reason",
          "pool_size", "sg_score_at_add", "added"]
MIN_DAYS_OUT = 3  # don't add shows that are about to happen
MAX_PER_ARTIST = 2  # one hot tour shouldn't fill the list


def _hash(sid, salt):
    return hashlib.sha1(f"{salt}:{sid}".encode()).hexdigest()


def build(store, today_rows, hist, today):
    path = store.path("watchlist.csv")
    live = {r["show_id"]: r for r in today_rows}
    shows = store.shows
    kept = [r for r in read_csv(path) if r["show_id"] in live]
    taken = {r["show_id"] for r in kept}
    soon_cut = (today + dt.timedelta(days=MIN_DAYS_OUT)).isoformat()

    nights = {(shows[r["show_id"]].get("artist_key"), r["date"]) for r in kept}
    per_artist = {}
    for r in kept:
        k = shows[r["show_id"]].get("artist_key")
        per_artist[k] = per_artist.get(k, 0) + 1

    def ok(sid):
        s = shows.get(sid)
        return (s and sid in live and sid not in taken and s["date"] >= soon_cut
                and per_artist.get(s.get("artist_key"), 0) < MAX_PER_ARTIST
                and (s.get("artist_key"), s["date"]) not in nights)  # same show listed twice

    score = {sid: num(r.get("sg_score")) or 0 for sid, r in live.items()}
    pools = {}
    pools["second_show"] = sorted({o["show_id"] for o, _ in added_dates(shows, since="2026-11-03")
                                   if score.get(o["show_id"], 0) >= 0.3}, key=lambda sid: -score[sid])
    rising = climbers(hist, today)
    pools["climber"] = [sid for sid, (a, b) in sorted(rising.items(), key=lambda kv: kv[1][0] - kv[1][1])
                        if b >= 0.3 and b - a > 0]
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    horizon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).isoformat()
    pools["onsale_soon"] = sorted(
        (sid for sid in live if now <= shows[sid].get("onsale_at", "") <= horizon and score.get(sid, 0) >= 0.3),
        key=lambda sid: -score[sid])
    salt = "flipit-random-v1"
    pools["random"] = sorted((sid for sid in live if score.get(sid, 0) > 0 and shows[sid].get("sg_id")),
                             key=lambda sid: _hash(sid, salt))

    out = list(kept)

    def add(group, limit):
        for sid in pools[group]:
            if limit <= 0 or len(out) >= SIZE:
                return
            if not ok(sid):
                continue
            s = shows[sid]
            out.append({"show_id": sid, "artist": s["artist"], "name": s["name"], "venue_name": s["venue_name"],
                        "city": s["city"], "state": s["state"], "date": s["date"], "time": s.get("time", ""),
                        "reason": group, "pool_size": len(pools[group]),
                        "sg_score_at_add": score.get(sid), "added": today.isoformat()})
            taken.add(sid)
            nights.add((s.get("artist_key"), s["date"]))
            per_artist[s.get("artist_key")] = per_artist.get(s.get("artist_key"), 0) + 1
            limit -= 1

    quota = SIZE // len(GROUPS)
    for group in GROUPS:
        add(group, quota - sum(1 for r in out if r["reason"] == group))
    for group in ["climber", "second_show", "random"]:  # slots a thin group couldn't fill
        add(group, SIZE - len(out))
    out.sort(key=lambda r: (GROUPS.index(r["reason"]), r["date"]))
    write_csv(path, out, FIELDS)
    return out
