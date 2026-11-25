"""link-scout — a stdlib-only website link checker and crawler.

Crawl a site from a seed URL (same-host scope, robots.txt aware),
check every unique link's HTTP status, and emit a per-page report
plus an XML sitemap.
"""

__version__ = "0.1.0"
__all__ = ["crawler", "checker", "sitemap", "cli"]
