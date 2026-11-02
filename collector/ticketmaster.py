"""Ticketmaster Discovery API: every US music event in a date window, plus face value and on-sale info."""
import datetime as dt
import re

from .util import Api, log

BASE = "https://app.ticketmaster.com/discovery/v2/events.json"
PAGE_SIZE = 200
MAX_RESULTS = 1000  # Discovery API refuses size * page beyond 1000
STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]
_JUNK = re.compile(r"\bparking\b|\bupgrade\b|gift card|\bvoucher\b|\badd[- ]on\b|\bshuttle\b|\blocker\b", re.I)
_SPOTIFY_ID = re.compile(r"spotify\.com/artist/([A-Za-z0-9]+)")


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(ev):
    name = ev.get("name") or ""
    if _JUNK.search(name):
        return None
    cls = (ev.get("classifications") or [{}])[0]
    if ((cls.get("segment") or {}).get("name") or "Music") != "Music":
        return None
    emb = ev.get("_embedded") or {}
    venue = (emb.get("venues") or [{}])[0]
    atts = emb.get("attractions") or []
    start = (ev.get("dates") or {}).get("start") or {}
    if not start.get("localDate"):
        return None
    prices = ev.get("priceRanges") or []
    std = [p for p in prices if str(p.get("type", "standard")).startswith("standard")] or prices
    mins = [p["min"] for p in std if p.get("min")]
    maxs = [p["max"] for p in std if p.get("max")]
    sales = ev.get("sales") or {}
    public = sales.get("public") or {}
    presales = sales.get("presales") or []
    spotify_id = ""
    if atts:
        for link in ((atts[0].get("externalLinks") or {}).get("spotify") or []):
            m = _SPOTIFY_ID.search(link.get("url", ""))
            if m:
                spotify_id = m.group(1)
                break
    return {
        "tm_id": ev["id"],
        "name": name,
        "artist": atts[0]["name"] if atts else name,
        "all_artists": "; ".join(a.get("name", "") for a in atts),
        "tm_attraction_id": atts[0].get("id", "") if atts else "",
        "spotify_id": spotify_id,
        "date": start.get("localDate", ""),
        "time": start.get("localTime", ""),
        "status": ((ev.get("dates") or {}).get("status") or {}).get("code", ""),
        "face_min": min(mins) if mins else None,
        "face_max": max(maxs) if maxs else None,
        "currency": std[0].get("currency", "") if std else "",
        "onsale_at": public.get("startDateTime", "") if not public.get("startTBD") else "",
        "presale": "yes" if presales else "no",
        "presale_names": "; ".join(p.get("name", "") for p in presales)[:300],
        "genre": (cls.get("genre") or {}).get("name", ""),
        "subgenre": (cls.get("subGenre") or {}).get("name", ""),
        "venue_name": venue.get("name", ""),
        "tm_venue_id": venue.get("id", ""),
        "city": (venue.get("city") or {}).get("name", ""),
        "state": (venue.get("state") or {}).get("stateCode", ""),
        "url": ev.get("url", ""),
    }


def _query(api, key, state, start, end, page):
    return api.request(BASE, {
        "apikey": key, "countryCode": "US", "stateCode": state, "segmentName": "Music",
        "startDateTime": _iso(start), "endDateTime": _iso(end),
        "size": PAGE_SIZE, "page": page, "sort": "date,asc",
    })


SAMPLES = []


def _add(data, out):
    for ev in ((data.get("_embedded") or {}).get("events") or []):
        if len(SAMPLES) < 3 and ev.get("priceRanges") is None:
            SAMPLES.append(ev)
        row = parse(ev)
        if row:
            out[row["tm_id"]] = row


def _window(api, key, state, start, end, out):
    data = _query(api, key, state, start, end, 0)
    page = data.get("page") or {}
    total = page.get("totalElements", 0)
    if total > MAX_RESULTS and end - start > dt.timedelta(hours=12):
        mid = start + (end - start) / 2
        _window(api, key, state, start, mid, out)
        _window(api, key, state, mid, end, out)
        return
    _add(data, out)
    pages = min(page.get("totalPages", 1), MAX_RESULTS // PAGE_SIZE)
    for p in range(1, pages):
        _add(_query(api, key, state, start, end, p), out)


def sweep(key, states, start, end):
    """Return ({tm_id: event}, health info)."""
    api = Api("ticketmaster", min_interval=0.55)  # free tier allows 2 requests a second
    out, failed = {}, []
    for state in states:
        try:
            _window(api, key, state, start, end, out)
        except Exception as e:  # keep going; one state failing shouldn't stop the run
            failed.append(state)
            log(f"ticketmaster {state}: {e}")
        if api.errors and str(api.last_error).startswith("HTTP 401"):
            break
    log(f"ticketmaster: {len(out)} events, {api.calls} calls, failed states: {failed}")
    ok = len(failed) <= max(1, len(states) // 10) and bool(out)
    return out, api.info(ok=ok, events=len(out), failed_states=failed)
