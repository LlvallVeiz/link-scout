"""HTTP link checking: status classification and per-link results.

Strategy per URL:
1. ``HEAD`` request first (cheap — no body downloaded).
2. If the server rejects HEAD (405/501/403 in practice) or errors, retry
   with ``GET`` (with a small body read so the connection closes cleanly).
3. ``urllib``'s default opener follows redirects; we record the final URL
   and how many hops the redirect chain took.

Classification (see README for the full table):
- ``ok``        — final status 2xx
- ``redirect``  — final status 3xx (rare: only when the opener stops early)
- ``broken``    — final status 4xx or 5xx
- ``timeout``   — the request exceeded the timeout
- ``error``     — DNS failure, refused connection, bad URL, ...
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_TIMEOUT = 10.0
USER_AGENT = "link-scout/0.1.0 (+https://github.com/LlvallVeiz/link-scout)"


@dataclass
class LinkResult:
    """The outcome of checking one URL."""

    url: str
    status: int | None = None          # final HTTP status, None if no response
    final_url: str | None = None       # URL after redirects (== url if none)
    redirects: int = 0                 # number of redirect hops followed
    classification: str = "error"      # ok | redirect | broken | timeout | error
    detail: str = ""                   # human-readable explanation
    method: str = ""                   # HEAD or GET (which one produced the result)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "status": self.status,
            "final_url": self.final_url,
            "redirects": self.redirects,
            "classification": self.classification,
            "detail": self.detail,
            "method": self.method,
        }


def classify_status(status: int | None) -> str:
    """Map a final HTTP status code to a link-scout classification."""
    if status is None:
        return "error"
    if 200 <= status < 300:
        return "ok"
    if 300 <= status < 400:
        return "redirect"
    return "broken"


class _RedirectCounter(urllib.request.HTTPRedirectHandler):
    """Counts redirect hops while still following them like the default."""

    def __init__(self) -> None:
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener() -> tuple[urllib.request.OpenerDirector, _RedirectCounter]:
    counter = _RedirectCounter()
    opener = urllib.request.build_opener(counter)
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener, counter


def _single_request(opener, url: str, method: str, timeout: float):
    """One request; returns (status, final_url) or raises."""
    req = urllib.request.Request(url, method=method)
    with opener.open(req, timeout=timeout) as resp:
        # GET bodies are drained so the socket can be reused/closed cleanly.
        if method == "GET":
            resp.read(65536)
        return resp.status, resp.geturl()


def check_url(url: str, timeout: float = DEFAULT_TIMEOUT) -> LinkResult:
    """Check one URL and return a :class:`LinkResult` (never raises)."""
    opener, counter = _build_opener()
    for method in ("HEAD", "GET"):
        counter.count = 0
        try:
            status, final_url = _single_request(opener, url, method, timeout)
            return LinkResult(
                url=url,
                status=status,
                final_url=final_url,
                redirects=counter.count,
                classification=classify_status(status),
                detail=f"HTTP {status}" + (f" after {counter.count} redirect(s)"
                                            if counter.count else ""),
                method=method,
            )
        except urllib.error.HTTPError as exc:
            # HTTPError *is* a response: 4xx/5xx means the link is broken.
            # But some servers reject HEAD (405/501) — retry those with GET.
            if method == "HEAD" and exc.code in (400, 401, 403, 405, 501):
                continue
            return LinkResult(
                url=url,
                status=exc.code,
                final_url=exc.geturl(),
                redirects=counter.count,
                classification=classify_status(exc.code),
                detail=f"HTTP {exc.code} {exc.reason}",
                method=method,
            )
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
                return LinkResult(url=url, classification="timeout",
                                  detail=f"timed out after {timeout:g}s", method=method)
            return LinkResult(url=url, classification="error",
                              detail=f"{type(reason).__name__}: {reason}", method=method)
        except (socket.timeout, TimeoutError):
            return LinkResult(url=url, classification="timeout",
                              detail=f"timed out after {timeout:g}s", method=method)
        except (ValueError, OSError) as exc:
            return LinkResult(url=url, classification="error",
                              detail=f"{type(exc).__name__}: {exc}", method=method)
    # Unreachable in practice (the loop always returns), kept for safety.
    return LinkResult(url=url, classification="error", detail="unknown failure")


def check_urls(urls, timeout: float = DEFAULT_TIMEOUT) -> list[LinkResult]:
    """Check an iterable of URLs, preserving input order (deduped)."""
    seen: set[str] = set()
    results: list[LinkResult] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        results.append(check_url(url, timeout=timeout))
    return results


def summarise(results: list[LinkResult]) -> dict[str, int]:
    """Count results per classification, plus a ``total`` key."""
    counts = {"total": len(results), "ok": 0, "redirect": 0,
              "broken": 0, "timeout": 0, "error": 0}
    for result in results:
        counts[result.classification] = counts.get(result.classification, 0) + 1
    return counts
