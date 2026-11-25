"""robots.txt handling, built on ``urllib.robotparser``.

Behaviour:
- Fetched once per host (``<scheme>://<host>/robots.txt``), with a short
  timeout; a missing/unreachable robots.txt means "everything allowed"
  (the standard fallback — a 404 is not a ban).
- ``is_allowed(url)`` answers the crawl question for our user-agent
  (``link-scout``); a parse failure also defaults to allowed.
- ``crawl_delay`` exposes any ``Crawl-delay`` directive the site sets,
  so the crawler can be polite.
"""

from __future__ import annotations

import urllib.robotparser
from urllib.parse import urlparse

USER_AGENT = "link-scout"
TIMEOUT = 5.0


class RobotsPolicy:
    """One host's robots.txt policy (or an empty allow-all policy)."""

    def __init__(self, host_url: str):
        parsed = urlparse(host_url)
        self.base = f"{parsed.scheme}://{parsed.netloc}"
        self.parser = urllib.robotparser.RobotFileParser()
        self.parser.set_url(f"{self.base}/robots.txt")
        self.fetched = False
        self.fetch()

    def fetch(self) -> None:
        """Download and parse robots.txt; any failure means allow-all."""
        try:
            self.parser.read()
            self.fetched = True
        except Exception:
            # Unreachable / unparseable robots.txt: standard behaviour is
            # to treat everything as allowed rather than refuse the crawl.
            self.parser = urllib.robotparser.RobotFileParser()
            self.fetched = False

    def is_allowed(self, url: str) -> bool:
        try:
            return bool(self.parser.can_fetch(USER_AGENT, url))
        except Exception:
            return True

    def crawl_delay(self) -> float | None:
        """Crawl-delay in seconds if the site declares one, else None."""
        try:
            delay = self.parser.crawl_delay(USER_AGENT)
        except Exception:
            return None
        return float(delay) if delay is not None else None


class RobotsCache:
    """Cache one :class:`RobotsPolicy` per host so we fetch robots.txt once."""

    def __init__(self) -> None:
        self._policies: dict[str, RobotsPolicy] = {}

    def policy_for(self, url: str) -> RobotsPolicy:
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._policies:
            self._policies[host] = RobotsPolicy(url)
        return self._policies[host]

    def is_allowed(self, url: str) -> bool:
        return self.policy_for(url).is_allowed(url)
