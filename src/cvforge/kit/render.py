"""Render kit.json data to one self-contained HTML page."""
from __future__ import annotations

from importlib import resources

import jinja2

from cvforge.kit.data import LIMITS

GROUPS = (("personal", "Personal data"), ("links", "Links"), ("preferences", "Preferences"))


def _variants(description: dict[str, str]) -> list[dict]:
    """Merge limits that give identical text, so the page does not repeat the same block."""
    merged: list[dict] = []
    for limit in LIMITS:
        text = description[str(limit)]
        if merged and merged[-1]["text"] == text:
            merged[-1]["limits"].append(limit)
        else:
            merged.append({"text": text, "limits": [limit]})
    return merged


def render_kit(kit: dict) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(resources.files("cvforge.kit").joinpath("templates"))),
        autoescape=True, trim_blocks=True, lstrip_blocks=True, undefined=jinja2.StrictUndefined)
    groups = [(label, [f for f in kit["fields"] if f["group"] == key]) for key, label in GROUPS]
    work = [{**w, "variants": _variants(w["description"])} for w in kit["work"]]
    return env.get_template("kit.html.j2").render(kit=kit, groups=groups, work=work)
