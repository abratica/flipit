"""SeatGeek Platform API: US concerts with resale price stats (lowest, median, listing count)."""
import datetime as dt

from .util import Api, log

BASE = "https://api.seatgeek.com/2/events"
PAGE_SIZE = 100
MAX_RESULTS = 5000  # split a window before paging this deep


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S")


def parse(ev):
    venue = ev.get("venue") or {}
    performers = ev.get("performers") or []
    primary = next((p for p in performers if p.get("primary")), performers[0] if performers else {})
    stats = ev.get("stats") or {}
    local = ev.get("datetime_local") or ""
    return {
        "sg_id": str(ev["id"]),
        "name": ev.get("title", ""),
        "artist": primary.get("name", "") or ev.get("title", ""),
        "all_artists": "; ".join(p.get("name", "") for p in performers),
        "sg_performer_score": primary.get("score"),
        "date": local[:10],
        "time": local[11:19] if not ev.get("time_tbd") else "",
        "announce_date": (ev.get("announce_date") or "")[:10],
        "score": ev.get("score"),
        "popularity": ev.get("popularity"),
        "venue_name": venue.get("name", ""),
        "sg_venue_id": str(venue.get("id", "")),
        "city": venue.get("city", ""),
        "state": venue.get("state", ""),
        "capacity": venue.get("capacity") or 0,
        "listing_count": stats.get("listing_count") or stats.get("visible_listing_count") or 0,
        "lowest": stats.get("lowest_price"),
        "lowest_base": stats.get("lowest_sg_base_price"),
        "median": stats.get("median_price"),
        "average": stats.get("average_price"),
        "highest": stats.get("highest_price"),
        "url": ev.get("url", ""),
    }


def _query(api, cid, secret, state, start, end, page):
    params = {
        "client_id": cid, "taxonomies.name": "concert", "venue.state": state,
        "datetime_utc.gte": _iso(start), "datetime_utc.lte": _iso(end),
        "per_page": PAGE_SIZE, "page": page, "sort": "datetime_utc.asc",
    }
    if secret:
        params["client_secret"] = secret
    return api.request(BASE, params)


def _add(data, out):
    for ev in data.get("events") or []:
        if ev.get("datetime_local"):
            row = parse(ev)
            out[row["sg_id"]] = row


def _window(api, cid, secret, state, start, end, out):
    data = _query(api, cid, secret, state, start, end, 1)
    total = (data.get("meta") or {}).get("total", 0)
    if total > MAX_RESULTS and end - start > dt.timedelta(hours=12):
        mid = start + (end - start) / 2
        _window(api, cid, secret, state, start, mid, out)
        _window(api, cid, secret, state, mid, end, out)
        return
    _add(data, out)
    pages = min(-(-total // PAGE_SIZE), MAX_RESULTS // PAGE_SIZE)
    for p in range(2, pages + 1):
        _add(_query(api, cid, secret, state, start, end, p), out)


def sweep(cid, secret, states, start, end):
    """Return ({sg_id: event}, health info)."""
    api = Api("seatgeek", min_interval=0.25)
    out, failed = {}, []
    for state in states:
        try:
            _window(api, cid, secret, state, start, end, out)
        except Exception as e:
            failed.append(state)
            log(f"seatgeek {state}: {e}")
        if api.errors and str(api.last_error).startswith(("HTTP 401", "HTTP 403")):
            break
    log(f"seatgeek: {len(out)} events, {api.calls} calls, failed states: {failed}")
    ok = len(failed) <= max(1, len(states) // 10) and bool(out)
    return out, api.info(ok=ok, events=len(out), failed_states=failed)
