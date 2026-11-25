# link-scout

A website link checker and crawler written in **Python 3, standard library only**
— no third-party packages to install. Point it at a site and it crawls the
pages, checks every link it finds, reports the broken ones, and can generate
a `sitemap.xml` for the pages it crawled.

## What it does

- **Crawls a site** from a seed URL, breadth-first, **same-host only**,
  with `--depth` (max link hops from the seed) and `--max-pages` limits.
- **Respects `robots.txt`** — fetched once per host via
  `urllib.robotparser`; URLs it disallows are listed as `robots_blocked`
  and never fetched. Pass `--no-robots` to ignore it (not recommended).
- **Extracts links** from every page: `a href`, `img src`, `link href`,
  `script src`, `source src`, `iframe src`. Relative URLs are resolved
  against the page URL.
- **Checks every unique link's HTTP status**: a `HEAD` request first
  (cheap, no body), with a `GET` fallback for servers that reject `HEAD`.
  Redirects are followed and the final URL + redirect-hop count recorded.
- **Reports per page** (which page links to what, with status) **plus
  summary stats** (pages crawled, links checked, counts per class).
- **Generates `sitemap.xml`** for the crawled HTML pages (valid XML,
  `<urlset>` with `<loc>` + `<lastmod>`).

## Install / run

Requires Python 3.10+. No dependencies — just clone and run:

```bash
git clone https://github.com/LlvallVeiz/link-scout.git
cd link-scout
python3 -m link_scout --help
```

or use the top-level entry point:

```bash
python3 link-scout.py --help
```

## Usage

### `crawl` — crawl a site and check all its links

```bash
python3 -m link_scout crawl https://example.com/ --depth 2 --max-pages 50 --output report.json
```

Options: `--depth N` (default 2), `--max-pages N` (default 50),
`--timeout S` (default 10), `--output report.json` (full JSON report),
`--no-robots` (ignore robots.txt).

Sample output:

```
== https://example.com/  (depth 0, HTTP 200) ==
   [OK      ]  HTTP 200  https://example.com/about
   [BROKEN  ]  HTTP 404  https://example.com/old-page
   [OK      ]  HTTP 200  https://example.com/style.css
   [SKIPPED ]           mailto:hello@example.com

Pages crawled: 12  |  Links checked: 87 (64 unique)
ok: 58  redirect: 3  broken: 2  timeout: 0  error: 1
```

### `check` — check individual URLs

```bash
python3 -m link_scout check https://example.com/ https://example.com/missing
```

```
[OK      ]  HTTP 200  https://example.com/
[BROKEN  ]  HTTP 404  https://example.com/missing
           HTTP 404 Not Found

2 checked: 1 ok, 0 redirect, 1 broken, 0 timeout, 0 error
```

### `sitemap` — crawl a site and write `sitemap.xml`

```bash
python3 -m link_scout sitemap https://example.com/ --depth 2 --output sitemap.xml
```

```
Crawled 12 page(s), wrote 12 URL(s) to sitemap.xml
```

## URL normalisation rules

Before a link is checked or compared, it is normalised:

| Rule | Example |
| --- | --- |
| Relative URLs resolved against the page URL | `sub/page` on `https://example.com/a/` → `https://example.com/a/sub/page` |
| Fragment stripped (never sent to the server) | `…/page#section` → `…/page` |
| Scheme and host lowercased | `HTTP://EXAMPLE.COM/` → `http://example.com/` |
| Default ports dropped | `http://example.com:80/x` → `http://example.com/x` |
| Duplicate slashes in the path collapsed | `…//a///b` → `…/a/b` |
| Query string kept (it changes the resource) | `…/s?q=1` stays as-is |

## Status classification

| Class | Meaning |
| --- | --- |
| `ok` | Final HTTP status is 2xx |
| `redirect` | Final status is 3xx (only if the opener stops before a final status) |
| `broken` | Final status is 4xx or 5xx |
| `timeout` | The request exceeded `--timeout` seconds |
| `error` | DNS failure, refused connection, malformed URL, … |

`mailto:`, `javascript:`, `tel:` and `data:` links are never fetched;
they are listed under `skipped` on the page that contains them, so you
can see they were noticed. Off-site (different-host) links are checked
but never crawled.

## robots.txt behaviour

- `robots.txt` is fetched once per host (`<scheme>://<host>/robots.txt`).
- A missing or unreachable `robots.txt` means **everything is allowed**
  (the standard fallback — a 404 is not a ban).
- A `Crawl-delay` directive is read if present; the crawler honours it
  via its polite-delay mechanism.
- Disallowed seed/page URLs are reported in `robots_blocked` in the
  JSON report and in the console output, and are never fetched.

## Project structure

```
link-scout/
├── link_scout/
│   ├── __init__.py      package metadata
│   ├── __main__.py      `python3 -m link_scout` entry point
│   ├── cli.py           argparse CLI: crawl / check / sitemap
│   ├── crawler.py       breadth-first, same-host, robots-aware crawler
│   ├── checker.py       HEAD-then-GET status checking + classification
│   ├── robots.py        robots.txt policy (urllib.robotparser) + cache
│   ├── sitemap.py       sitemap.xml generation + parsing
│   └── urls.py          URL normalisation + HTML link extraction
├── tests/
│   └── test_link_scout.py   unittest suite (local HTTP test server)
├── link-scout.py        top-level entry point
├── LICENSE              MIT
└── README.md
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The suite runs against a tiny `http.server` on `127.0.0.1` (no public
internet needed) and covers: link extraction, URL normalisation,
broken/redirect/timeout classification, crawler depth/page limits,
robots.txt blocking, sitemap XML validity, and CLI smoke tests.

## What was implemented

- `urls.py` — `normalise_url()` (fragment strip, lowercase scheme/host,
  default-port drop, slash collapse), `LinkExtractor` (html.parser based,
  collects `a`/`img`/`link`/`script`/`source`/`iframe` targets, separates
  non-fetchable schemes into `skipped`).
- `checker.py` — `check_url()` / `check_urls()`: HEAD first, GET fallback
  on 400/401/403/405/501, redirect counting via a custom
  `HTTPRedirectHandler`, `LinkResult` dataclass, `classify_status()` and
  `summarise()` counters.
- `robots.py` — `RobotsPolicy` + `RobotsCache` over `urllib.robotparser`,
  allow-all fallback when robots.txt is missing/unparseable.
- `crawler.py` — breadth-first crawl with same-host scope, depth/page
  caps, robots gating, per-page reports, deduped link checking, JSON-
  serialisable `CrawlReport` with summary stats.
- `sitemap.py` — `build_sitemap()` / `write_sitemap()` (sorted, deduped,
  XML-escaped `<loc>` + `<lastmod>`) and `parse_sitemap()` for read-back.
- `cli.py` — `crawl` / `check` / `sitemap` subcommands with readable
  console tables and JSON report output.

## License

MIT — see [LICENSE](LICENSE).
