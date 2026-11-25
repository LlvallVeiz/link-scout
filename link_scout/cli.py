"""Command-line interface for link-scout.

Subcommands:
    crawl   <seed-url> [--depth N] [--max-pages N] [--timeout S]
            [--output report.json] [--no-robots]
    check   <url>... [--timeout S]
    sitemap <seed-url> [--depth N] [--max-pages N] [--timeout S]
            [--output sitemap.xml]

Exit codes: 0 = finished (even if broken links were found — those are
reported in the output, not hidden in the exit code), 1 = usage/seed error.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .checker import check_urls, summarise
from .crawler import crawl as run_crawl
from .sitemap import write_sitemap
from .urls import normalise_url

_CLASS_LABEL = {
    "ok": "OK      ",
    "redirect": "REDIRECT",
    "broken": "BROKEN  ",
    "timeout": "TIMEOUT ",
    "error": "ERROR   ",
}


def _print_check_table(results) -> None:
    for result in results:
        status = f"HTTP {result.status}" if result.status is not None else "-"
        final = f" -> {result.final_url}" if result.final_url and result.final_url != result.url else ""
        print(f"[{_CLASS_LABEL[result.classification]}] {status:>9}  {result.url}{final}")
        if result.detail and result.classification not in ("ok",):
            print(f"           {result.detail}")


def cmd_check(args: argparse.Namespace) -> int:
    urls = [normalise_url(u) for u in args.urls]
    results = check_urls(urls, timeout=args.timeout)
    _print_check_table(results)
    counts = summarise(results)
    print()
    print(f"{counts['total']} checked: {counts['ok']} ok, {counts['redirect']} redirect, "
          f"{counts['broken']} broken, {counts['timeout']} timeout, {counts['error']} error")
    return 0


def cmd_crawl(args: argparse.Namespace) -> int:
    report = run_crawl(
        args.seed_url,
        max_depth=args.depth,
        max_pages=args.max_pages,
        timeout=args.timeout,
        respect_robots=not args.no_robots,
    )
    summary = report.summary
    for page in report.pages:
        status = f"HTTP {page.status}" if page.status is not None else "fetch failed"
        print(f"\n== {page.url}  (depth {page.depth}, {status}) ==")
        if page.error:
            print(f"   fetch error: {page.error}")
        for result in page.links:
            code = f"HTTP {result.status}" if result.status is not None else "-"
            print(f"   [{_CLASS_LABEL[result.classification]}] {code:>9}  {result.url}")
        for skipped in page.skipped:
            print(f"   [SKIPPED ]           {skipped}")
    if report.robots_blocked:
        print(f"\nrobots.txt blocked {len(report.robots_blocked)} URL(s):")
        for url in report.robots_blocked:
            print(f"   {url}")
    print()
    print(f"Pages crawled: {summary['pages_crawled']}  |  "
          f"Links checked: {summary['total_links']} ({summary['unique_links']} unique)")
    print(f"ok: {summary['ok']}  redirect: {summary['redirect']}  "
          f"broken: {summary['broken']}  timeout: {summary['timeout']}  "
          f"error: {summary['error']}")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(report.to_dict(), fh, indent=2)
        print(f"\nReport written to {args.output}")
    return 0


def cmd_sitemap(args: argparse.Namespace) -> int:
    report = run_crawl(
        args.seed_url,
        max_depth=args.depth,
        max_pages=args.max_pages,
        timeout=args.timeout,
    )
    # Only real HTML pages belong in a sitemap — not CSS/JS/images.
    urls = [page.url for page in report.pages
            if page.status == 200 and page.content_type == "text/html"]
    write_sitemap(urls, args.output)
    print(f"Crawled {len(report.pages)} page(s), wrote {len(urls)} URL(s) to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="link-scout",
        description="Check a website's links: crawl a site, check URLs, "
                    "and generate a sitemap. Stdlib only.",
    )
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_crawl = sub.add_parser("crawl", help="crawl a site and check all its links")
    p_crawl.add_argument("seed_url", help="starting URL, e.g. https://example.com/")
    p_crawl.add_argument("--depth", type=int, default=2,
                         help="max link hops from the seed (default: 2)")
    p_crawl.add_argument("--max-pages", type=int, default=50,
                         help="max pages to fetch (default: 50)")
    p_crawl.add_argument("--timeout", type=float, default=10.0,
                         help="per-request timeout in seconds (default: 10)")
    p_crawl.add_argument("--output", default=None,
                         help="write the full JSON report to this file")
    p_crawl.add_argument("--no-robots", action="store_true",
                         help="ignore robots.txt (not recommended)")
    p_crawl.set_defaults(func=cmd_crawl)

    p_check = sub.add_parser("check", help="check one or more URLs directly")
    p_check.add_argument("urls", nargs="+", help="URL(s) to check")
    p_check.add_argument("--timeout", type=float, default=10.0,
                         help="per-request timeout in seconds (default: 10)")
    p_check.set_defaults(func=cmd_check)

    p_map = sub.add_parser("sitemap", help="crawl a site and write sitemap.xml")
    p_map.add_argument("seed_url", help="starting URL, e.g. https://example.com/")
    p_map.add_argument("--depth", type=int, default=2,
                       help="max link hops from the seed (default: 2)")
    p_map.add_argument("--max-pages", type=int, default=50,
                       help="max pages to fetch (default: 50)")
    p_map.add_argument("--timeout", type=float, default=10.0,
                       help="per-request timeout in seconds (default: 10)")
    p_map.add_argument("--output", default="sitemap.xml",
                       help="output file (default: sitemap.xml)")
    p_map.set_defaults(func=cmd_sitemap)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
