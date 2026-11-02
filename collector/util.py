"""Shared helpers: HTTP with retries, name normalizing, logging."""
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request


def log(*args):
    print(*args, file=sys.stderr, flush=True)


class Api:
    """Small JSON client that paces requests, retries transient errors and counts calls."""

    def __init__(self, name, min_interval=0.0):
        self.name = name
        self.min_interval = min_interval
        self.calls = 0
        self.errors = 0
        self.last_error = None
        self._last = 0.0

    def request(self, url, params=None, headers=None, data=None, retries=4):
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        for attempt in range(retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.calls += 1
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "FlipIt/1.0", **(headers or {})})
            try:
                with urllib.request.urlopen(req, timeout=40) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read()[:300].decode("utf-8", errors="replace")
                if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                    retry_after = e.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt * 2
                    time.sleep(min(delay, 60))
                    continue
                self.errors += 1
                self.last_error = f"HTTP {e.code}: {body}"
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < retries:
                    time.sleep(2 ** attempt * 2)
                    continue
                self.errors += 1
                self.last_error = str(e)[:300]
                raise

    def info(self, ok=None, **extra):
        failed_share = self.errors / self.calls if self.calls else 0
        return {
            "ok": (failed_share <= 0.10) if ok is None else ok,
            "calls": self.calls,
            "errors": self.errors,
            "last_error": self.last_error,
            **extra,
        }


_STOP = re.compile(r"\b(the|at|presents?|live)\b")


def norm(s):
    """Lowercase, ascii, no punctuation, so names from different sources compare."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("theatre", "theater").replace("ctr", "center")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _STOP.sub(" ", s)
    return " ".join(s.split())


def tokens(s):
    return set(norm(s).split())


def jaccard(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def num(v):
    """Parse a number from a CSV cell; None when blank."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None
