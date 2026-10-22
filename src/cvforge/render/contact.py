"""Contact links shared by the CV and the cover letter (visible text, no icon labels, for ATS)."""


def contact_links(basics: dict) -> list[dict]:
    """Phone, mailto email, then each profile as a visible bare URL; `href` is empty for plain text."""
    links = []
    if basics.get("phone"):
        links.append({"text": basics["phone"], "href": ""})
    if basics.get("email"):
        links.append({"text": basics["email"], "href": "mailto:" + basics["email"]})
    for profile in basics.get("profiles", []):
        bare = profile["url"].split("://", 1)[-1].strip("/")
        links.append({"text": bare.removeprefix("www."), "href": "https://" + bare})
    return links
