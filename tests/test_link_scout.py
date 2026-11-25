"""Tests for link-scout — stdlib unittest only, no network beyond localhost.

A tiny HTTP server runs in a thread on 127.0.0.1 and serves:
    /            index page (links to /ok, /missing, /redir, /sub/page,
                 a mailto: link and a javascript: link)
    /ok          plain 200 page
    /missing     404
    /redir       301 redirect to /ok
    /sub/page    200 page linking back to / and to /ok
    /private     200 page, but disallowed in robots.txt
    /slow        sleeps 2 s before answering (timeout test)
    /robots.txt  disallows /private
"""

import http.server
import socketserver
import threading
import unittest
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from link_scout.checker import check_url, classify_status, summarise
from link_scout.cli import main as cli_main
from link_scout.crawler import Crawler
from link_scout.sitemap import build_sitemap, parse_sitemap
from link_scout.urls import extract_links, normalise_url

INDEX_HTML = """<!doctype html><html><head>
<link rel="stylesheet" href="/style.css">
<script src="/app.js"></script>
</head><body>
<a href="/ok">ok page</a>
<a href="sub/page">relative sub page</a>
<a href="/missing">gone</a>
<a href="/redir">redirect</a>
<a href="https://example.com:443/outside">outside</a>
<a href="mailto:hello@example.com">mail me</a>
<a href="javascript:void(0)">do nothing</a>
<img src="/logo.png" alt="logo">
</body></html>"""

SUB_HTML = """<!doctype html><html><body>
<a href="/">home again</a>
<a href="/ok">ok again</a>
</body></html>"""

ROBOTS_TXT = "User-agent: *\nDisallow: /private\n"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    def _route(self):
        routes = {
            "/": (200, "text/html", INDEX_HTML.encode()),
            "/ok": (200, "text/html", b"<html><body>fine</body></html>"),
            "/sub/page": (200, "text/html", SUB_HTML.encode()),
            "/private": (200, "text/html", b"<html><body>secret</body></html>"),
            "/robots.txt": (200, "text/plain", ROBOTS_TXT.encode()),
            "/style.css": (200, "text/css", b"body{}"),
            "/app.js": (200, "application/javascript", b""),
            "/logo.png": (200, "image/png", b"\x89PNG"),
        }
        if self.path == "/missing":
            return 404, "text/html", b"not found"
        if self.path == "/redir":
            return 301, "text/html", b""  # Location header added below
        if self.path == "/slow":
            import time
            time.sleep(2)
            return 200, "text/html", b"slow"
        return routes.get(self.path, (404, "text/html", b"not found"))

    def _serve(self, head_only: bool):
        status, ctype, body = self._route()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if self.path == "/redir":
            self.send_header("Location", "/ok")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_GET(self):
        self._serve(head_only=False)

    def do_HEAD(self):
        self._serve(head_only=True)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ServerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = _Server(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"


# ---------------------------------------------------------------- URLs
class TestUrlNormalisation(unittest.TestCase):
    def test_relative_resolves_against_base(self):
        self.assertEqual(
            normalise_url("sub/page", "http://example.com/a/b"),
            "http://example.com/a/sub/page")
        self.assertEqual(
            normalise_url("/abs", "http://example.com/a/b"),
            "http://example.com/abs")

    def test_fragment_stripped(self):
        self.assertEqual(
            normalise_url("http://example.com/page#section"),
            "http://example.com/page")

    def test_default_port_dropped(self):
        self.assertEqual(normalise_url("http://example.com:80/x"),
                         "http://example.com/x")
        self.assertEqual(normalise_url("https://example.com:443/x"),
                         "https://example.com/x")
        # Non-default ports are kept.
        self.assertEqual(normalise_url("http://example.com:8080/x"),
                         "http://example.com:8080/x")

    def test_scheme_and_host_lowercased(self):
        self.assertEqual(normalise_url("HTTP://EXAMPLE.COM/Path"),
                         "http://example.com/Path")

    def test_duplicate_slashes_collapsed(self):
        self.assertEqual(normalise_url("http://example.com//a///b"),
                         "http://example.com/a/b")

    def test_query_kept(self):
        self.assertEqual(normalise_url("http://example.com/s?q=1"),
                         "http://example.com/s?q=1")

    def test_empty_returns_empty(self):
        self.assertEqual(normalise_url(""), "")


class TestLinkExtraction(unittest.TestCase):
    BASE = "http://example.com/dir/page.html"

    def test_extracts_all_link_kinds(self):
        links, skipped = extract_links(INDEX_HTML, "http://127.0.0.1:9/")
        self.assertIn("http://127.0.0.1:9/ok", links)
        self.assertIn("http://127.0.0.1:9/sub/page", links)
        self.assertIn("http://127.0.0.1:9/missing", links)
        self.assertIn("http://127.0.0.1:9/redir", links)
        self.assertIn("http://127.0.0.1:9/style.css", links)   # link href
        self.assertIn("http://127.0.0.1:9/app.js", links)      # script src
        self.assertIn("http://127.0.0.1:9/logo.png", links)    # img src
        # Default https port is dropped during normalisation.
        self.assertIn("https://example.com/outside", links)

    def test_skipped_schemes_listed_not_crawled(self):
        links, skipped = extract_links(INDEX_HTML, "http://127.0.0.1:9/")
        self.assertIn("mailto:hello@example.com", skipped)
        self.assertIn("javascript:void(0)", skipped)
        self.assertTrue(all(not l.startswith(("mailto:", "javascript:"))
                            for l in links))

    def test_fragment_only_links_ignored(self):
        links, _ = extract_links('<a href="#top">top</a>', self.BASE)
        self.assertEqual(links, set())


# ------------------------------------------------------------- checker
class TestClassification(unittest.TestCase):
    def test_classify_status(self):
        self.assertEqual(classify_status(200), "ok")
        self.assertEqual(classify_status(204), "ok")
        self.assertEqual(classify_status(301), "redirect")
        self.assertEqual(classify_status(404), "broken")
        self.assertEqual(classify_status(500), "broken")
        self.assertEqual(classify_status(None), "error")


class TestCheckerAgainstServer(ServerTestCase):
    def test_200_is_ok(self):
        result = check_url(self.url("/ok"))
        self.assertEqual(result.classification, "ok")
        self.assertEqual(result.status, 200)
        self.assertEqual(result.method, "HEAD")

    def test_404_is_broken(self):
        result = check_url(self.url("/missing"))
        self.assertEqual(result.classification, "broken")
        self.assertEqual(result.status, 404)

    def test_301_redirect_followed_to_ok(self):
        result = check_url(self.url("/redir"))
        self.assertEqual(result.classification, "ok")
        self.assertEqual(result.status, 200)
        self.assertEqual(result.redirects, 1)
        self.assertEqual(result.final_url, self.url("/ok"))

    def test_timeout_classified(self):
        result = check_url(self.url("/slow"), timeout=0.5)
        self.assertEqual(result.classification, "timeout")
        self.assertIsNone(result.status)

    def test_dns_error_classified(self):
        result = check_url("http://nonexistent.invalid/", timeout=5)
        self.assertEqual(result.classification, "error")
        self.assertIsNone(result.status)

    def test_summarise_counts(self):
        results = [check_url(self.url(p)) for p in ("/ok", "/missing", "/redir")]
        counts = summarise(results)
        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["ok"], 2)
        self.assertEqual(counts["broken"], 1)


# ------------------------------------------------------------- crawler
class TestCrawler(ServerTestCase):
    def test_crawl_finds_pages_and_broken_links(self):
        report = Crawler(self.url("/"), max_depth=1, max_pages=10).crawl()
        crawled = {p.url for p in report.pages}
        self.assertIn(self.url("/"), crawled)
        self.assertIn(self.url("/sub/page"), crawled)
        # Off-site link is checked but never crawled.
        self.assertNotIn("https://example.com/outside", crawled)
        # The index page links to a 404 — it must show up as broken.
        index = next(p for p in report.pages if p.url == self.url("/"))
        by_url = {r.url: r for r in index.links}
        self.assertEqual(by_url[self.url("/missing")].classification, "broken")
        self.assertEqual(by_url[self.url("/redir")].classification, "ok")
        # mailto:/javascript: are reported as skipped, not as links.
        self.assertIn("mailto:hello@example.com", index.skipped)
        self.assertEqual(report.summary["pages_crawled"], len(report.pages))
        self.assertGreaterEqual(report.summary["broken"], 1)

    def test_depth_limit_respected(self):
        # depth 0: only the seed page is fetched.
        report = Crawler(self.url("/"), max_depth=0, max_pages=10).crawl()
        self.assertEqual([p.url for p in report.pages], [self.url("/")])

    def test_max_pages_limit_respected(self):
        report = Crawler(self.url("/"), max_depth=2, max_pages=1).crawl()
        self.assertEqual(len(report.pages), 1)

    def test_robots_txt_blocks_private(self):
        report = Crawler(self.url("/private"), max_depth=0, max_pages=10).crawl()
        self.assertEqual(report.pages, [])
        self.assertIn(self.url("/private"), report.robots_blocked)

    def test_report_serialises_to_json(self):
        import json
        report = Crawler(self.url("/"), max_depth=0, max_pages=5).crawl()
        json.dumps(report.to_dict())  # must not raise


# ------------------------------------------------------------- sitemap
class TestSitemap(unittest.TestCase):
    def test_valid_xml_contains_urls(self):
        urls = ["http://example.com/", "http://example.com/about?x=1&y=2"]
        xml = build_sitemap(urls, lastmod="2026-11-25")
        root = ET.fromstring(xml)  # raises if not well-formed
        self.assertEqual(parse_sitemap(xml), sorted(urls))
        self.assertIn("<lastmod>2026-11-25</lastmod>", xml)

    def test_empty_url_list(self):
        xml = build_sitemap([])
        self.assertEqual(parse_sitemap(xml), [])


# ----------------------------------------------------------------- CLI
class TestCli(ServerTestCase):
    def test_check_command_exits_zero(self):
        rc = cli_main(["check", self.url("/ok"), self.url("/missing")])
        self.assertEqual(rc, 0)

    def test_crawl_command_writes_json_report(self):
        import json
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            rc = cli_main(["crawl", self.url("/"), "--depth", "1",
                           "--max-pages", "5", "--output", out])
            self.assertEqual(rc, 0)
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["seed_url"], self.url("/"))
            self.assertGreaterEqual(data["summary"]["broken"], 1)

    def test_sitemap_command_writes_file(self):
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "sitemap.xml")
            rc = cli_main(["sitemap", self.url("/"), "--depth", "1",
                           "--max-pages", "5", "--output", out])
            self.assertEqual(rc, 0)
            with open(out, encoding="utf-8") as fh:
                xml = fh.read()
            locs = parse_sitemap(xml)
            self.assertIn(self.url("/"), locs)
            # Only HTML pages belong in the sitemap — not CSS/JS/images.
            self.assertNotIn(self.url("/app.js"), locs)
            self.assertNotIn(self.url("/logo.png"), locs)


if __name__ == "__main__":
    unittest.main()
