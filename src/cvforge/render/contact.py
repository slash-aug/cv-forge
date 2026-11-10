"""Contact links shared by the CV and the cover letter (visible text, no icon labels, for ATS)."""

from itertools import groupby


def contact_links(basics: dict) -> list[dict]:
    """Phone and mailto email, then each profile as a visible bare URL; `href` is empty for plain text.

    Phone and email form the first header line. Profiles go below it, one line per `line`
    number (default 1); `newline` marks the first link of each line after the first.
    """
    links = []
    if basics.get("phone"):
        links.append({"text": basics["phone"], "href": "", "newline": False})
    if basics.get("email"):
        links.append({"text": basics["email"], "href": "mailto:" + basics["email"], "newline": False})
    profiles = sorted(basics.get("profiles", []), key=_line)
    for _, group in groupby(profiles, key=_line):
        for i, profile in enumerate(group):
            links.append({**url_link(profile["url"]), "newline": bool(links) and i == 0})
    return links


def _line(profile: dict) -> int:
    return profile.get("line", 1)


def url_link(url: str) -> dict:
    """A URL as visible text without scheme or www, linking to its https address."""
    bare = url.split("://", 1)[-1].strip("/")
    return {"text": bare.removeprefix("www."), "href": "https://" + bare}
