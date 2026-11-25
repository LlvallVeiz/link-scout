"""Breadth-first crawler: same-host scope, depth/page limits, robots.txt.

Algorithm:
- Start from the seed URL, fetch pages breadth-first (shallow pages first).
- Only follow links whose host matches the seed host, and only up to
  ``max_depth`` hops from the seed (seed is depth 0).
- Stop after ``max_pages`` pages have been fetched.
- Before fetching a URL, ask robots.txt (via :mod:`link_scout.robots`);
  disallowed URLs are recorded as ``robots_blocked`` and never fetched.
- Every page's outgoing links are extracted (a/img/link/script/source/
  iframe) and every unique http(s) link found anywhere is checked with
  :mod:`link_scout.checker` — including off-site links, which are checked
  but never crawled.
- Non-HTML responses (images, PDFs, ...) are not parsed for links, but
  their HTTP status is still recorded from the fetch itself.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .checker import LinkResult, check_url, summarise
from .robots import RobotsCache
from .urls import extract_links, is_http_url, normalise_url

USER_AGENT = "link-scout/0.1.0 (+https://github.com/LlvallVeiz/link-scout)"


@dataclass
class PageReport:
    """What one crawled page linked to, with each link's check result."""

    url: str
    depth: int
    status: int | None = None
    content_type: str = ""               # e.g. "text/html" ("" if fetch failed)
    links: list[LinkResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # mailto:/javascript:/...
    error: str = ""                                    # fetch failure, if any

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "depth": self.depth,
            "status": self.status,
            "content_type": self.content_type,
            "error": self.error,
            "links": [r.to_dict() for r in self.links],
            "skipped": self.skipped,
        }


@dataclass
class CrawlReport:
    """The full result of a crawl: per-page reports plus summary stats."""

    seed_url: str
    pages: list[PageReport] = field(default_factory=list)
    robots_blocked: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "seed_url": self.seed_url,
            "pages": [p.to_dict() for p in self.pages],
            "robots_blocked": self.robots_blocked,
            "summary": self.summary,
        }


def _same_host(url: str, host: str) -> bool:
    return urlparse(url).hostname == host


class Crawler:
    """Breadth-first, same-host, robots-aware site crawler."""

    def __init__(self, seed_url: str, max_depth: int = 2, max_pages: int = 50,
                 timeout: float = 10.0, respect_robots: bool = True,
                 polite_delay: float = 0.0):
        self.seed_url = normalise_url(seed_url)
        self.host = urlparse(self.seed_url).hostname or ""
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.polite_delay = polite_delay
        self.robots = RobotsCache()
        self._checked: dict[str, LinkResult] = {}

    # -- fetching ---------------------------------------------------------
    def _fetch(self, url: str) -> tuple[int | None, str, str]:
        """Fetch ``url``; return (status, content_type, body_text_or_"")."""
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content_type = resp.headers.get_content_type()
                body = ""
                if content_type == "text/html":
                    charset = resp.headers.get_content_charset("utf-8")
                    body = resp.read(2_000_000).decode(charset, errors="replace")
                return resp.status, content_type, body
        except urllib.error.HTTPError as exc:
            return exc.code, "", ""
        except Exception as exc:  # timeout, DNS, refused, ...
            raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc

    def _check(self, url: str) -> LinkResult:
        if url not in self._checked:
            self._checked[url] = check_url(url, timeout=self.timeout)
        return self._checked[url]

    # -- main crawl -------------------------------------------------------
    def crawl(self) -> CrawlReport:
        report = CrawlReport(seed_url=self.seed_url)
        queue: deque[tuple[str, int]] = deque([(self.seed_url, 0)])
        visited: set[str] = set()

        while queue and len(report.pages) < self.max_pages:
            url, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            if self.respect_robots and not self.robots.is_allowed(url):
                report.robots_blocked.append(url)
                continue

            page = PageReport(url=url, depth=depth)
            report.pages.append(page)
            try:
                status, content_type, body = self._fetch(url)
            except RuntimeError as exc:
                page.error = str(exc)
                continue
            page.status = status
            page.content_type = content_type

            if content_type != "text/html" or not body:
                continue
            links, skipped = extract_links(body, base_url=url)
            page.skipped = sorted(skipped)
            page.links = [self._check(link) for link in sorted(links)]

            if depth < self.max_depth:
                for link in sorted(links):
                    if (is_http_url(link) and _same_host(link, self.host)
                            and link not in visited):
                        queue.append((link, depth + 1))
            if self.polite_delay:
                time.sleep(self.polite_delay)

        all_results = [r for page in report.pages for r in page.links]
        counts = summarise(all_results)
        report.summary = {
            "pages_crawled": len(report.pages),
            "total_links": len(all_results),
            "unique_links": len(self._checked),
            "robots_blocked": len(report.robots_blocked),
            **counts,
        }
        return report


def crawl(seed_url: str, **kwargs) -> CrawlReport:
    """Convenience wrapper: ``crawl(seed, max_depth=2, max_pages=50, ...)``."""
    return Crawler(seed_url, **kwargs).crawl()
