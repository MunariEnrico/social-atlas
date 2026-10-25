"""Polite HTTP fetching: robots.txt, per-host rate limiting, timeouts, bounded retries."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = (
    "SocialAtlasBot/1.0 (+personal, non-commercial event digest; "
    "respects robots.txt; one request per host every few seconds)"
)
# Some sites serve 403 to unknown bots but publish feeds explicitly for readers.
# We still check robots.txt against our own agent token.
ROBOTS_AGENT = "SocialAtlasBot"
MAX_BYTES = 4_000_000
TRANSIENT = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    url: str
    status: int | None = None
    text: str | None = None
    content_type: str | None = None
    final_url: str | None = None
    error: str | None = None
    robots_allowed: bool | None = None
    attempts: int = 0
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 300


class Fetcher:
    def __init__(self, min_delay: float = 3.0, timeout: float = 20.0, retries: int = 2,
                 respect_robots: bool = True):
        self.min_delay = min_delay
        self.timeout = timeout
        self.retries = retries
        self.respect_robots = respect_robots
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml,application/rss+xml,"
                      "application/atom+xml,text/calendar,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en,fr;q=0.8,it;q=0.8,de;q=0.6",
        })
        self._last_hit: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self.request_count = 0

    # -- politeness -----------------------------------------------------
    def _host_lock(self, host: str) -> threading.Lock:
        with self._lock:
            return self._host_locks.setdefault(host, threading.Lock())

    def _wait_turn(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.min_delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def robots_allows(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = RobotFileParser()
            try:
                r = self.session.get(base + "/robots.txt", timeout=self.timeout)
                self.request_count += 1
                if r.status_code in (401, 403):
                    # robots.txt itself forbidden: treat as disallow-all per RFC 9309 guidance
                    rp.parse(["User-agent: *", "Disallow: /"])
                elif r.status_code >= 500:
                    rp = None  # server error: treat as unreachable (disallow this run)
                elif r.status_code >= 400:
                    rp.parse([])  # no robots.txt -> everything allowed
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                # RFC 9309: if robots.txt cannot be reached, assume everything is disallowed.
                # The source is skipped for this run and retried on the next one.
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return False if rp is None else rp.can_fetch(ROBOTS_AGENT, url)

    # -- fetch ----------------------------------------------------------
    def get(self, url: str, params: dict | None = None, accept_json: bool = False) -> FetchResult:
        res = FetchResult(url=url)
        host = urlparse(url).netloc
        with self._host_lock(host):
            try:
                res.robots_allowed = self.robots_allows(url)
            except Exception as exc:  # pragma: no cover
                res.robots_allowed = None
                res.error = f"robots check failed: {exc}"
                return res
            if res.robots_allowed is False:
                base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                res.error = "robots.txt unreachable — skipped this run" if self._robots.get(base) is None else "disallowed by robots.txt"
                return res
            t0 = time.monotonic()
            for attempt in range(self.retries + 1):
                res.attempts = attempt + 1
                res.error = None
                self._wait_turn(host)
                try:
                    headers = {"Accept": "application/json"} if accept_json else None
                    r = self.session.get(url, params=params, timeout=self.timeout,
                                         stream=True, headers=headers, allow_redirects=True)
                    self.request_count += 1
                    raw = r.raw.read(MAX_BYTES + 1, decode_content=True)
                    if len(raw) > MAX_BYTES:
                        res.error = "response too large"
                        res.status = r.status_code
                        break
                    res.status = r.status_code
                    res.final_url = r.url
                    res.content_type = r.headers.get("Content-Type")
                    enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else None
                    if enc is None:
                        enc = requests.utils.get_encodings_from_content(raw[:3000].decode("ascii", "ignore"))
                        enc = enc[0] if enc else "utf-8"
                    res.text = raw.decode(enc, errors="replace")
                    if r.status_code in TRANSIENT and attempt < self.retries:
                        retry_after = r.headers.get("Retry-After")
                        delay = min(float(retry_after), 30.0) if (retry_after or "").isdigit() else 4.0 * (attempt + 1)
                        time.sleep(delay)
                        continue
                    if r.status_code >= 400:
                        res.error = f"HTTP {r.status_code}"
                    break
                except requests.Timeout:
                    res.error = "timeout"
                except requests.ConnectionError as exc:
                    res.error = f"connection error: {type(exc).__name__}"
                except requests.RequestException as exc:
                    res.error = f"request error: {type(exc).__name__}"
                    break
                if attempt < self.retries:
                    time.sleep(3.0 * (attempt + 1))
            res.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return res
