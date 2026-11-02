"""Spotify Web API: artist followers, popularity and genres, captured the first time an artist is seen."""
import base64
import time
from difflib import SequenceMatcher

from .util import Api, log, norm

TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"


class Spotify:
    def __init__(self, cid, secret):
        self.api = Api("spotify", min_interval=0.35)  # roughly 170 a minute, under the reported limit
        self.cid, self.secret = cid, secret
        self.token, self.token_at = None, 0.0
        self.found = self.not_found = 0
        self.fields_missing = 0

    def _auth(self):
        if self.token and time.monotonic() - self.token_at < 3000:
            return
        basic = base64.b64encode(f"{self.cid}:{self.secret}".encode()).decode()
        data = self.api.request(TOKEN_URL, headers={
            "Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded",
        }, data=b"grant_type=client_credentials")
        self.token, self.token_at = data["access_token"], time.monotonic()

    def _get(self, path, params=None):
        self._auth()
        return self.api.request(API + path, params, headers={"Authorization": f"Bearer {self.token}"})

    SAMPLES = []

    def _record(self, a):
        if len(Spotify.SAMPLES) < 1:
            Spotify.SAMPLES.append(a)
        followers = (a.get("followers") or {}).get("total")
        popularity = a.get("popularity")
        if followers is None and popularity is None:
            self.fields_missing += 1
        return {
            "spotify_id": a.get("id", ""),
            "spotify_name": a.get("name", ""),
            "spotify_followers": "" if followers is None else followers,
            "spotify_popularity": "" if popularity is None else popularity,
            "spotify_genres": "; ".join(a.get("genres") or [])[:300],
        }

    def lookup(self, name, spotify_id=""):
        """Return Spotify fields for an artist, or None when there's no confident match."""
        if spotify_id:
            try:
                rec = self._record(self._get(f"/artists/{spotify_id}"))
                self.found += 1
                return rec
            except Exception:
                pass
        data = self._get("/search", {"q": name, "type": "artist", "limit": 5})
        items = (data.get("artists") or {}).get("items") or []
        target = norm(name)
        best, best_score = None, 0.0
        for a in items:
            s = SequenceMatcher(None, target, norm(a.get("name", ""))).ratio()
            if s > best_score:
                best, best_score = a, s
        if best is None or best_score < 0.9:
            self.not_found += 1
            return None
        self.found += 1
        return self._record(best)

    def info(self, ok=None, **extra):
        return self.api.info(ok=ok, found=self.found, not_found=self.not_found,
                             missing_follower_fields=self.fields_missing, **extra)


def capture(sp, queue, deadline):
    """Look up queued artists until the queue or the time runs out. Returns {artist_key: fields}."""
    out = {}
    for key, name, spotify_id in queue:
        if time.monotonic() > deadline:
            log(f"spotify: time budget reached, {len(queue) - len(out)} artists left for tomorrow")
            break
        try:
            rec = sp.lookup(name, spotify_id)
            out[key] = rec if rec else {"status": "not_found"}
        except Exception as e:
            log(f"spotify {name}: {e}")
            if str(sp.api.last_error).startswith(("HTTP 401", "HTTP 403")):
                break
    return out
