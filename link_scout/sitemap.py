"""XML sitemap generation (sitemaps.org protocol).

Produces a ``<urlset>`` document with one ``<url>`` entry per crawled
page: ``<loc>`` plus ``<lastmod>`` (today's date, since the crawl just
happened). The output is well-formed XML with the standard namespace.
"""

from __future__ import annotations

import datetime
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def build_sitemap(urls, lastmod: str | None = None) -> str:
    """Return a sitemap.xml document (as a string) for ``urls``.

    ``lastmod`` defaults to today's date (``YYYY-MM-DD``).
    URLs are sorted and deduplicated for a stable, diff-friendly output.
    """
    if lastmod is None:
        lastmod = datetime.date.today().isoformat()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<urlset xmlns="{SITEMAP_NS}">',
    ]
    for url in sorted(set(urls)):
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(url)}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def write_sitemap(urls, path: str, lastmod: str | None = None) -> str:
    """Write the sitemap for ``urls`` to ``path``; returns the XML string."""
    xml = build_sitemap(urls, lastmod=lastmod)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(xml)
    return xml


def parse_sitemap(xml: str) -> list[str]:
    """Read back a sitemap document and return its ``<loc>`` values."""
    root = ET.fromstring(xml)
    ns = {"s": SITEMAP_NS}
    return [el.text for el in root.findall("s:url/s:loc", ns) if el.text]
