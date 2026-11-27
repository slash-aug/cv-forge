"""Advice on weak CV and kit content. Warnings never block a build."""
from __future__ import annotations

from cvforge.kit.describe import describe
from cvforge.profile.model import index, text_in

MAX_BULLETS = 6


def _selected(tailored: dict, master: dict):
    """(position from the master, its tailored bullets) in selection order."""
    ids = index(master)
    for entry in tailored.get("experience", []):
        for selection in entry["positions"]:
            yield ids[selection["ref"]][1], selection["bullets"]


def cv_warnings(tailored: dict, master: dict) -> list[str]:
    lang = tailored["lang"]
    warnings = []
    for position, bullets in _selected(tailored, master):
        pid = position["id"]
        if len(bullets) > MAX_BULLETS:
            warnings.append(f"{pid}: {len(bullets)} bullets on the CV, keep at most {MAX_BULLETS}")
        form = position.get("x-form") or {}
        if form.get("cv_lead") and form["pinned"]:
            lead = form["pinned"][0]["ref"]
            if not bullets or bullets[0]["ref"] != lead:
                warnings.append(f"{pid}: the CV should lead with {lead}")
    if lang.startswith("pt"):
        ids = index(master)
        for selection in tailored.get("skills", []):
            labels = ids[selection["ref"]][1].get("x-labels") or {}
            warnings.extend(
                f"{selection['ref']}: skill '{k}' has no {lang} label"
                for k in selection["keywords"] if k in labels and text_in(labels[k], lang) is None)
    return warnings


def _form_warnings(position: dict, bullets: list[dict], lang: str) -> list[str]:
    pid, form = position["id"], position.get("x-form")
    if not form:
        return [f"{pid}: no x-form, the kit description has no context line"]
    if text_in(form["context"], lang) is None:
        return [f"{pid}: x-form context has no {lang} text"]
    warnings = []
    tailored = {b["ref"] for b in bullets}
    highlights = {h["id"]: h for h in position["highlights"]}
    for pin in form["pinned"]:
        ref = pin["ref"]
        if ref not in tailored and text_in(highlights[ref]["impact"], lang) is None:
            warnings.append(f"{pid}: pinned {ref} has no text in {lang}, left out")
        if "short" in pin and text_in(pin["short"], lang) is None:
            warnings.append(f"{pid}: pinned {ref} has no {lang} short text")
    # The 200 variant is the context line followed by the first pinned highlight.
    if form["pinned"] and "\n" not in describe(position, bullets, lang, 200):
        warnings.append(f"{pid}: the 200 variant lacks the context or the first pinned highlight")
    return warnings


def kit_warnings(tailored: dict, master: dict) -> list[str]:
    lang = tailored["lang"]
    warnings = []
    for position, bullets in _selected(tailored, master):
        warnings.extend(_form_warnings(position, bullets, lang))
        full = describe(position, bullets, lang, 2000)
        if "\n" not in full:
            size = "one line" if full else "empty"
            warnings.append(f"{position['id']}: the kit description is {size}")
    return warnings
