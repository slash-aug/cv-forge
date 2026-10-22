"""Render a tailored CV to moderncv LaTeX: view-model builder, then template."""
from cvforge.profile.model import ProfileError, index, localized
from cvforge.render.contact import contact_links
from cvforge.render.latex import format_date, format_range, jinja_env

HEADINGS = {
    "en": {"summary": "Summary", "experience": "Experience", "skills": "Skills",
           "education": "Education", "certificates": "Certifications", "languages": "Languages"},
    "pt-BR": {"summary": "Resumo", "experience": "Experiência Profissional", "skills": "Competências",
              "education": "Formação", "certificates": "Certificações", "languages": "Idiomas"},
    "pt-PT": {"summary": "Resumo", "experience": "Experiência Profissional", "skills": "Competências",
              "education": "Formação", "certificates": "Certificações", "languages": "Línguas"},
}
INTERNATIONAL = {
    "en": "International remote freelance",
    "pt-BR": "Freelance internacional remoto",
    "pt-PT": "Freelance internacional remoto",
}
REMOTE = {"en": "Remote", "pt-BR": "Remoto", "pt-PT": "Remoto"}


def _lookup(ids: dict, ref: str, kind: str) -> dict:
    entry = ids.get(ref)
    if entry is None or entry[0] != kind:
        raise ProfileError(f"{ref}: expected a {kind} id in the master profile")
    return entry[1]


def _contact(basics: dict, lang: str) -> dict:
    first, _, last = basics["name"].partition(" ")
    location = basics.get("location") or {}
    address = ", ".join(p for p in (location.get("city"), location.get("countryCode")) if p)
    label = basics.get("label")
    return {
        "first": first, "last": last, "address": address,
        "links": contact_links(basics),
        "title": localized(label, lang, item_id="basics.label") if label else "",
    }


def _positions(employer: dict, entry: dict, lang: str, ids: dict) -> list[dict]:
    if employer.get("x-international"):
        location = INTERNATIONAL[lang]
    else:
        location = employer.get("location") or REMOTE[lang]
    rows = []
    for ref in entry["positions"]:
        position = _lookup(ids, ref["ref"], "position")
        rows.append({
            "start": position["startDate"],
            "dates": format_range(position["startDate"], position.get("endDate"), lang, item_id=position["id"]),
            "title": localized(position["title"], lang, item_id=position["id"]),
            "employer": localized(employer["name"], lang, item_id=employer["id"]),
            "location": location,
            "bullets": [b["text"] for b in ref["bullets"]],
        })
    return sorted(rows, key=lambda r: r["start"], reverse=True)


def build_cv_view(tailored: dict, master: dict) -> dict:
    """Resolve refs and localise everything; the template only formats."""
    lang = tailored["lang"]
    ids = index(master)
    experience = []
    for entry in tailored.get("experience", []):
        employer = _lookup(ids, entry["ref"], "work")
        experience.extend(_positions(employer, entry, lang, ids))
    skills = [
        {"name": localized(_lookup(ids, s["ref"], "skill")["name"], lang, item_id=s["ref"]),
         "keywords": ", ".join(s["keywords"])}
        for s in tailored.get("skills", [])
    ]
    education = []
    for ref in tailored.get("education", []):
        ed = _lookup(ids, ref, "education")
        degree = ", ".join(p for p in (
            localized(ed["studyType"], lang, item_id=ref) if ed.get("studyType") else "",
            localized(ed["area"], lang, item_id=ref) if ed.get("area") else "",
        ) if p)
        start, end = ed.get("startDate"), ed.get("endDate")
        dates = (format_range(start, end, lang, item_id=ref) if start else format_date(end, lang, item_id=ref)) if (start or end) else ""
        education.append({"dates": dates, "degree": degree,
                          "institution": localized(ed["institution"], lang, item_id=ref)})
    certificates = []
    for ref in tailored.get("certificates", []):
        cert = _lookup(ids, ref, "certificate")
        if "locales" in cert and lang not in cert["locales"]:
            continue  # `locales` lists the CV languages that show this certificate
        certificates.append({"date": format_date(cert["date"], lang, item_id=ref),
                             "name": cert["name"], "issuer": cert["issuer"]})
    languages = []
    for ref in tailored.get("languages", []):
        item = _lookup(ids, ref, "language")
        fluency = localized(item["fluency"], lang, item_id=ref)
        detail = ", ".join(p for p in (fluency, item.get("cefr")) if p)
        languages.append({"name": localized(item["language"], lang, item_id=ref), "detail": detail})
    summary = (tailored.get("summary") or {}).get("text", "")
    return {
        "lang": lang,
        "headings": HEADINGS[lang],
        "contact": _contact(master["basics"], lang),
        "summary": summary,
        "experience": experience,
        "skills": skills,
        "education": education,
        "certificates": certificates,
        "languages": languages,
    }


def render_view(view: dict) -> str:
    return jinja_env().get_template("cv_moderncv.tex.j2").render(**view)


def render_cv(tailored: dict, master: dict) -> str:
    """Full .tex source for a tailored CV."""
    return render_view(build_cv_view(tailored, master))


__all__ = ["build_cv_view", "render_cv", "render_view"]
