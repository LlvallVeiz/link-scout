"""URL normalisation and HTML link extraction helpers.

Rules (documented in the README too):
- Resolve relative URLs against the page URL with ``urllib.parse.urljoin``.
- Strip the fragment (``#...``) — fragments never reach the server.
- Lowercase scheme and host.
- Drop default ports (``:80`` for http, ``:443`` for https).
- Collapse duplicate slashes in the path (``//`` -> ``/``).
- Keep the query string as-is (it changes the resource).
- ``javascript:`` and ``mailto:`` (and friends) are not crawlable links:
  they are reported as *skipped* so the user can see they were seen.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse

# Schemes that never point at a fetchable web resource.
SKIPPED_SCHEMES = {"javascript", "mailto", "tel", "data", "ftp", "file"}

# (tag, attribute) pairs whose attribute value is a link.
LINK_ATTRS = {
    ("a", "href"),
    ("img", "src"),
    ("link", "href"),
    ("script", "src"),
    ("source", "src"),
    ("iframe", "src"),
}

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalise_url(url: str, base: str | None = None) -> str:
    """Resolve ``url`` against ``base`` (if given) and normalise it.

    Returns the normalised absolute URL, or ``""`` for an empty value.
    """
    if not url or not url.strip():
        return ""
    url = url.strip()
    if base:
        url = urljoin(base, url)
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower() if parsed.hostname else ""
    port = parsed.port
    if port and _DEFAULT_PORTS.get(scheme) == port:
        port = None
    netloc = host
    if parsed.username:
        netloc = parsed.username + ("@" if not parsed.password else f":{parsed.password}@") + netloc
    if port:
        netloc = f"{netloc}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path) or "/"
    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))


def is_skipped_scheme(url: str) -> bool:
    """True if ``url`` uses a scheme we never fetch (mailto:, javascript:, ...)."""
    return urlparse(url).scheme.lower() in SKIPPED_SCHEMES


def is_http_url(url: str) -> bool:
    return urlparse(url).scheme.lower() in {"http", "https"}


class LinkExtractor(HTMLParser):
    """Collects links from an HTML document.

    ``links`` holds normalised, fetchable (http/https) URLs found.
    ``skipped`` holds raw values that were seen but are not fetchable
    (javascript:, mailto:, ...), so the caller can report them.
    """

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: set[str] = set()
        self.skipped: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for attr, value in attrs:
            if (tag, attr) not in LINK_ATTRS or not value:
                continue
            value = value.strip()
            if not value or value.startswith("#"):
                continue
            if is_skipped_scheme(value):
                self.skipped.add(value)
                continue
            absolute = normalise_url(value, base=self.base_url)
            if absolute and is_http_url(absolute):
                self.links.add(absolute)


def extract_links(html: str, base_url: str) -> tuple[set[str], set[str]]:
    """Parse ``html`` and return ``(links, skipped)`` for page ``base_url``."""
    extractor = LinkExtractor(base_url)
    extractor.feed(html)
    extractor.close()
    return extractor.links, extractor.skipped
