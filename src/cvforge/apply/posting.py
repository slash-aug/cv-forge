"""The saved posting snapshot and the small helpers around it."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

TRACKING_PARAMS = frozenset({"referral", "ref", "src", "source", "gh_src", "lever-source"})

# Fixed stopword lists, about 30 words each. Words that are common in both languages are left out.
EN_WORDS = frozenset(
    ["the", "and", "of", "to", "in", "for", "with", "you", "we", "is", "are", "will", "on", "as", "be", "our", "your", "this", "that", "or", "an", "at", "by", "from", "have", "has", "experience", "work", "team", "about", "who", "what", "their", "can"])
PT_WORDS = frozenset(
    ["de", "e", "o", "os", "as", "do", "da", "em", "para", "com", "um", "uma", "que", "na", "no", "por", "se", "ao", "dos", "das", "nos", "nas", "ser", "mais", "nossa", "nosso", "equipa", "experiencia", "trabalho", "sobre"])
LANG_MIN_HITS = 5


@dataclass
class Posting:
    company: str
    title: str
    location: str
    location_requirements: list[str]
    workplace: str | None
    salary: dict | None
    language: str | None
    url: str
    apply_url: str | None
    source: str
    fetched: str
    description: str
    guard: dict = field(default_factory=dict)

    def save(self, app_dir: Path) -> None:
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / "posting.json").write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        facts = [("Company", self.company), ("Location", self.location),
                 ("Workplace", self.workplace), ("Language", self.language),
                 ("Link", self.url), ("Apply", self.apply_url), ("Source", f"{self.source}, {self.fetched}")]
        lines = [f"# {self.title}", ""]
        lines += [f"- {k}: {v}" for k, v in facts if v]
        if self.location_requirements:
            lines.append(f"- Open to: {', '.join(self.location_requirements)}")
        if self.salary:
            lines.append(f"- Salary: {json.dumps(self.salary, ensure_ascii=False)}")
        lines += ["", self.description, ""]
        (app_dir / "posting.md").write_text("\n".join(lines), encoding="utf-8")

    @classmethod
    def load(cls, app_dir: Path) -> Posting:
        data = json.loads((app_dir / "posting.json").read_text(encoding="utf-8"))
        return cls(**data)


def canonical_url(url: str) -> str:
    """Lowercase host, no fragment, no tracking parameters. Never resolves anything."""
    parts = urlsplit(url.strip())
    kept = []
    for item in parts.query.split("&"):
        key = item.split("=", 1)[0].lower()
        if item and not key.startswith("utm_") and key not in TRACKING_PARAMS:
            kept.append(item)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "&".join(kept), ""))


def guess_language(text: str) -> str | None:
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    words = re.findall(r"[^\W\d_]+", plain)
    en = sum(1 for w in words if w in EN_WORDS)
    pt = sum(1 for w in words if w in PT_WORDS)
    best = max(en, pt)
    if best < LANG_MIN_HITS or en == pt:
        return None
    return "en" if en > pt else "pt"
