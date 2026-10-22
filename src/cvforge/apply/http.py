"""The one place that touches the network: fetch a page as text."""
from __future__ import annotations

import urllib.error
import urllib.request

from cvforge.apply.page_decode import decode_page

USER_AGENT = "Mozilla/5.0 (cv-forge)"


class FetchError(Exception):
    """A page could not be fetched."""


def get(url: str, *, timeout: float = 20.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return decode_page(response.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc
