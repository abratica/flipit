"""The data tables, kept as CSV files in the repo.

shows.csv      one row per show; first-sighting fields never change
artists.csv    one row per artist; Spotify numbers as of the day first captured
venues.csv     one row per venue; capacity and where that number came from
snapshots/     one gzipped CSV per day, one row per upcoming show
"""
import csv
import datetime as dt
import gzip
import os

from .util import norm

SHOW_FIELDS = [
    "show_id", "tm_id", "sg_id", "name", "artist", "artist_key", "all_artists", "venue_key", "venue_name",
    "city", "state", "date", "time", "day_of_week", "face_min", "face_max", "currency", "face_first_seen",
    "onsale_at", "presale", "presale_names", "primary_platform", "genre", "subgenre", "announce_date",
    "sg_score_first", "sg_popularity_first", "city_dates", "status", "first_seen", "last_seen",
    "tm_url", "sg_url",
]
ARTIST_FIELDS = [
    "artist_key", "name", "spotify_id", "spotify_name", "spotify_followers", "spotify_popularity",
    "spotify_genres", "sg_performer_score", "tm_attraction_id", "status", "first_seen", "captured_date",
]
VENUE_FIELDS = [
    "venue_key", "name", "city", "state", "tm_venue_id", "sg_venue_id", "capacity", "capacity_source",
    "first_seen",
]
SNAPSHOT_FIELDS = [
    "date", "show_id", "days_until", "status", "face_min", "face_max", "listing_count",
    "lowest", "lowest_base", "median", "average", "highest", "sg_score",
]
# fields filled at first sighting and never overwritten afterwards
FIRST_ONLY = {"first_seen", "sg_score_first", "sg_popularity_first", "announce_date", "artist", "artist_key"}


def read_csv(path):
    if not os.path.exists(path):
        return []
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    opener = gzip.open if path.endswith(".gz") else open
    with opener(tmp, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})
    os.replace(tmp, path)


def _blank(v):
    return v in (None, "")


class Store:
    def __init__(self, root):
        self.root = root
        self.shows = {r["show_id"]: r for r in read_csv(self.path("shows.csv"))}
        self.artists = {r["artist_key"]: r for r in read_csv(self.path("artists.csv"))}
        self.venues = {r["venue_key"]: r for r in read_csv(self.path("venues.csv"))}
        self.overrides = {r["venue_key"]: r for r in read_csv(self.path("venue_overrides.csv"))}
        self.by_tm = {r["tm_id"]: k for k, r in self.shows.items() if r.get("tm_id")}
        self.by_sg = {r["sg_id"]: k for k, r in self.shows.items() if r.get("sg_id")}
        self.sg_venue = {r["sg_venue_id"]: k for k, r in self.venues.items() if r.get("sg_venue_id")}
        self.new_shows = 0
        self.new_venues = 0

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    # ---- venues -------------------------------------------------------------------------------
    def _venue(self, tm, sg, today):
        if tm:
            key = f"{tm['state']}|{norm(tm['venue_name'])}"
        elif sg.get("sg_venue_id") in self.sg_venue:
            key = self.sg_venue[sg["sg_venue_id"]]
        else:
            key = f"{sg['state']}|{norm(sg['venue_name'])}"
        v = self.venues.get(key)
        if v is None:
            src = tm or sg
            v = {"venue_key": key, "name": src["venue_name"], "city": src["city"], "state": src["state"],
                 "first_seen": today}
            self.venues[key] = v
            self.new_venues += 1
        if tm and _blank(v.get("tm_venue_id")):
            v["tm_venue_id"] = tm.get("tm_venue_id", "")
        if sg:
            if _blank(v.get("sg_venue_id")):
                v["sg_venue_id"] = sg.get("sg_venue_id", "")
                self.sg_venue[v["sg_venue_id"]] = key
            if sg.get("capacity") and v.get("capacity_source") in (None, "", "seatgeek"):
                v["capacity"], v["capacity_source"] = sg["capacity"], "seatgeek"
        o = self.overrides.get(key)
        if o and o.get("capacity"):
            v["capacity"], v["capacity_source"] = o["capacity"], o.get("source") or "manual"
        return key

    # ---- shows --------------------------------------------------------------------------------
    def upsert(self, tm_events, sg_events, pairs, today):
        """Merge today's events into shows. Returns {show_id: (tm_event, sg_event)} seen today."""
        seen = {}
        matched_sg = set(pairs.values())
        for tm_id, tm in tm_events.items():
            sg = sg_events.get(pairs.get(tm_id, ""))
            sid = self.by_tm.get(tm_id) or (self.by_sg.get(sg["sg_id"]) if sg else None)
            seen[self._apply(sid, tm, sg, today)] = (tm, sg)
        for sg_id, sg in sg_events.items():
            if sg_id in matched_sg:
                continue
            seen[self._apply(self.by_sg.get(sg_id), None, sg, today)] = (None, sg)
        self._city_dates()
        return seen

    def _apply(self, sid, tm, sg, today):
        src = tm or sg
        if sid is None:
            sid = f"tm:{tm['tm_id']}" if tm else f"sg:{sg['sg_id']}"
            self.shows[sid] = {"show_id": sid, "first_seen": today}
            self.new_shows += 1
        row = self.shows[sid]
        fresh = {
            "name": src["name"], "artist": src["artist"], "artist_key": norm(src["artist"]),
            "all_artists": src.get("all_artists", ""), "venue_key": self._venue(tm, sg, today),
            "venue_name": src["venue_name"], "city": src["city"], "state": src["state"],
            "date": src["date"], "time": src.get("time", ""),
            "day_of_week": dt.date.fromisoformat(src["date"]).strftime("%a"),
            "primary_platform": "ticketmaster" if tm else "other (seatgeek listing)",
            "last_seen": today,
        }
        if tm:
            fresh.update({
                "tm_id": tm["tm_id"], "status": tm["status"], "onsale_at": tm["onsale_at"],
                "presale": tm["presale"], "presale_names": tm["presale_names"], "genre": tm["genre"],
                "subgenre": tm["subgenre"], "currency": tm["currency"], "tm_url": tm["url"],
            })
            if tm["face_min"] is not None:
                if _blank(row.get("face_min")):
                    fresh["face_first_seen"] = today
                fresh["face_min"], fresh["face_max"] = tm["face_min"], tm["face_max"]
        if sg:
            fresh.update({"sg_id": sg["sg_id"], "sg_url": sg["url"], "announce_date": sg["announce_date"],
                          "sg_score_first": sg["score"], "sg_popularity_first": sg["popularity"]})
            if not tm:
                fresh["status"] = "listed"
        for k, v in fresh.items():
            if k in FIRST_ONLY and not _blank(row.get(k)):
                continue
            if _blank(v) and not _blank(row.get(k)):
                continue  # never erase something we knew
            row[k] = v
        if row.get("tm_id"):
            self.by_tm[row["tm_id"]] = sid
        if row.get("sg_id"):
            self.by_sg[row["sg_id"]] = sid
        return sid

    def _city_dates(self):
        """How many dates the same artist has in the same city (a supply signal)."""
        counts = {}
        for r in self.shows.values():
            k = (r.get("artist_key"), norm(r.get("city", "")), r.get("state"))
            counts[k] = counts.get(k, 0) + 1
        for r in self.shows.values():
            r["city_dates"] = counts[(r.get("artist_key"), norm(r.get("city", "")), r.get("state"))]

    # ---- artists ------------------------------------------------------------------------------
    def note_artists(self, seen, today):
        """Add artists seen today; return the Spotify lookup queue, most urgent first."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        priority = {}
        for sid, (tm, sg) in seen.items():
            src = tm or sg
            key = norm(src["artist"])
            if not key:
                continue
            a = self.artists.get(key)
            if a is None:
                a = {"artist_key": key, "name": src["artist"], "first_seen": today}
                self.artists[key] = a
            if tm and _blank(a.get("tm_attraction_id")):
                a["tm_attraction_id"] = tm.get("tm_attraction_id", "")
            if tm and tm.get("spotify_id") and _blank(a.get("spotify_id")):
                a["spotify_id"] = tm["spotify_id"]
            if sg and _blank(a.get("sg_performer_score")) and sg.get("sg_performer_score") is not None:
                a["sg_performer_score"] = sg["sg_performer_score"]
            if a.get("captured_date") or a.get("status") == "not_found":
                continue
            upcoming_sale = bool(tm and tm.get("onsale_at") and tm["onsale_at"] >= now)
            p = priority.setdefault(key, [0, 0])
            p[0] = max(p[0], 1 if upcoming_sale else 0)
            p[1] += 1
        order = sorted(priority, key=lambda k: (-priority[k][0], -priority[k][1]))
        return [(k, self.artists[k]["name"], self.artists[k].get("spotify_id", "")) for k in order]

    def save_spotify(self, results, today):
        for key, rec in results.items():
            a = self.artists[key]
            if rec.get("status") == "not_found":
                a["status"], a["captured_date"] = "not_found", today
            else:
                a.update(rec)
                a["status"], a["captured_date"] = "ok", today

    # ---- snapshots ----------------------------------------------------------------------------
    def snapshot(self, seen, today):
        t = dt.date.fromisoformat(today)
        rows = []
        for sid, (tm, sg) in seen.items():
            show = self.shows[sid]
            days = (dt.date.fromisoformat(show["date"]) - t).days
            if days < 0:
                continue
            rows.append({
                "date": today, "show_id": sid, "days_until": days, "status": show.get("status", ""),
                "face_min": tm["face_min"] if tm else "", "face_max": tm["face_max"] if tm else "",
                "listing_count": sg["listing_count"] if sg else "", "lowest": sg["lowest"] if sg else "",
                "lowest_base": sg["lowest_base"] if sg else "", "median": sg["median"] if sg else "",
                "average": sg["average"] if sg else "", "highest": sg["highest"] if sg else "",
                "sg_score": sg["score"] if sg else "",
            })
        write_csv(self.path("snapshots", f"{today}.csv.gz"), rows, SNAPSHOT_FIELDS)
        return rows

    def save(self):
        write_csv(self.path("shows.csv"), sorted(self.shows.values(), key=lambda r: (r["date"], r["show_id"])),
                  SHOW_FIELDS)
        write_csv(self.path("artists.csv"), sorted(self.artists.values(), key=lambda r: r["artist_key"]),
                  ARTIST_FIELDS)
        write_csv(self.path("venues.csv"), sorted(self.venues.values(), key=lambda r: r["venue_key"]),
                  VENUE_FIELDS)
