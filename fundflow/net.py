"""HTTP sessions with retries and polite pacing."""
import os
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
# SEC asks automated clients to identify themselves. Set the SEC_USER_AGENT
# repository secret (e.g. "Your Name your@email") - see README.
SEC_UA = os.environ.get("SEC_USER_AGENT") or "FundFlowMonitor personal-research"

TIMEOUT = 60


def make_session(user_agent=BROWSER_UA):
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=2,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST", "HEAD"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": user_agent,
                      "Accept-Language": "en-GB,en;q=0.9"})
    return s


class Paced:
    """Wraps a session so consecutive requests are at least `gap` seconds apart."""

    def __init__(self, session, gap):
        self.s, self.gap, self._last = session, gap, 0.0

    def _wait(self):
        dt = time.monotonic() - self._last
        if dt < self.gap:
            time.sleep(self.gap - dt)
        self._last = time.monotonic()

    def get(self, url, **kw):
        self._wait()
        kw.setdefault("timeout", TIMEOUT)
        return self.s.get(url, **kw)

    def post(self, url, **kw):
        self._wait()
        kw.setdefault("timeout", TIMEOUT)
        return self.s.post(url, **kw)


def sec_session():
    s = make_session(SEC_UA)
    s.headers["Accept-Encoding"] = "gzip, deflate"
    return Paced(s, 0.15)  # SEC fair-access limit is 10 requests/second
