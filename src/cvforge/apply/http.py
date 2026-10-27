"""The one place that touches the network: fetch a page as text."""
from __future__ import annotations

import urllib.error
import urllib.request
from urllib.parse import urlsplit

from cvforge.apply.page_decode import decode_page

USER_AGENT = "Mozilla/5.0 (cv-forge)"


class FetchError(Exception):
    """A page could not be fetched."""


def host_of(url: str) -> str:
    """Lowercase host without trailing dots ("linkedin.com." is linkedin.com)."""
    return (urlsplit(url.strip()).hostname or "").lower().rstrip(".")


def on_domain(host: str, domain: str) -> bool:
    host = host.lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


def is_linkedin(url: str) -> bool:
    """True for linkedin.com and its subdomains (not lnkd.in, which is only a short link)."""
    return on_domain(host_of(url), "linkedin.com")


class NoLinkedInRedirect(urllib.request.HTTPRedirectHandler):
    """Follows redirects, except into LinkedIn: those pages are never fetched."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if is_linkedin(newurl):
            raise FetchError(f"redirect to LinkedIn refused: {req.full_url} -> {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(NoLinkedInRedirect())


def get(url: str, *, timeout: float = 20.0) -> str:
    if is_linkedin(url):
        raise FetchError(f"LinkedIn pages are never fetched: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with OPENER.open(request, timeout=timeout) as response:
            return decode_page(response.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc


def get_bytes(url: str, *, timeout: float = 20.0) -> bytes:
    """Like get, without decoding (spreadsheets and other binary files)."""
    if is_linkedin(url):
        raise FetchError(f"LinkedIn pages are never fetched: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with OPENER.open(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc
