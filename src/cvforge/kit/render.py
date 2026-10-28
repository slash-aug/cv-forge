"""Render kit.json data to one self-contained HTML page."""
from __future__ import annotations

from importlib import resources
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from cvforge.kit.data import LIMITS

if TYPE_CHECKING:
    import jinja2

GROUPS = (("personal", "Personal data"), ("links", "Links"), ("preferences", "Preferences"))


def _variants(description: dict[str, str]) -> list[dict]:
    """Merge limits that give identical text, so the page does not repeat the same block."""
    merged: list[dict] = []
    for limit in LIMITS:
        text = description[str(limit)]
        if not text:
            continue  # nothing fits this limit (first word too long): no empty block
        if merged and merged[-1]["text"] == text:
            merged[-1]["limits"].append(limit)
        else:
            merged.append({"text": text, "limits": [limit]})
    return merged


def is_web(url) -> bool:
    """Only http(s) links become hrefs; a posting's apply URL is untrusted input."""
    return isinstance(url, str) and urlsplit(url.strip()).scheme.lower() in ("http", "https")


def make_env(package: str) -> jinja2.Environment:
    """HTML environment over the package's templates folder, with the `web` test."""
    import jinja2  # imported here so the CLI starts without it

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(resources.files(package).joinpath("templates"))),
        autoescape=True, trim_blocks=True, lstrip_blocks=True, undefined=jinja2.StrictUndefined)
    env.tests["web"] = is_web
    return env


def render_kit(kit: dict) -> str:
    env = make_env("cvforge.kit")
    groups = [(label, [f for f in kit["fields"] if f["group"] == key]) for key, label in GROUPS]
    employers: list[dict] = []
    for w in kit["work"]:
        job = {**w, "variants": _variants(w["description"])}
        if employers and employers[-1]["company"] == w["company"]:
            employers[-1]["jobs"].append(job)
        else:
            employers.append({"company": w["company"], "jobs": [job]})
    return env.get_template("kit.html.j2").render(kit=kit, groups=groups, employers=employers)
