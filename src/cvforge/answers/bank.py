"""Answer bank: approved answers to repeated screening questions."""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

import yaml

from cvforge.profile.model import ProfileError, read_yaml
from cvforge.text import fold_accents

FIELDS = ("key", "question", "answer", "refs", "lang", "last_used")
NON_WORD = re.compile(r"[\W_]+")
STOPWORDS = frozenset(["a", "an", "the", "of", "to", "in", "on", "at", "for", "and", "or", "is", "are", "was", "were", "be", "do", "does", "did", "you", "your", "we", "our", "i", "me", "my", "it", "this", "that", "with", "as", "by", "from", "have", "has", "can", "will", "would", "o", "os", "as", "um", "uma", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "por", "para", "e", "ou", "que", "com", "voce", "voces", "tem", "ter", "seu", "sua", "sao", "ser"])


class AnswerError(ProfileError):
    pass


def normalise_question(text: str) -> str:
    """Folded question without punctuation and stopwords, so rewordings share a key."""
    words = NON_WORD.sub(" ", fold_accents(text)).split()
    return " ".join(w for w in words if w not in STOPWORDS)


def load_bank(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    data = read_yaml(path, "answer bank")
    if data is None:
        return []
    if not isinstance(data, list) or not all(
            isinstance(e, dict) and {"key", "answer", "lang"} <= e.keys() for e in data):
        raise AnswerError(f"{path}: expected a list of entries with key, answer and lang")
    return [{**e, "last_used": str(e["last_used"]) if e.get("last_used") else ""} for e in data]


def lookup(bank: list[dict], question: str, lang: str) -> dict | None:
    key = normalise_question(question)
    if not key:
        return None
    for entry in bank:
        if entry["key"] == key and entry["lang"] == lang:
            return entry
    return None


def save_answers(path: Path, answers: list[dict], lang: str, today: date) -> int:
    """Add or update answers (same key and lang), stamping last_used; returns how many."""
    bank = load_bank(path)
    count = 0
    for a in answers:
        key = normalise_question(a["question"])
        if not key:
            continue
        entry = {"key": key, "question": a["question"].strip(), "answer": a["answer"],
                 "refs": list(a.get("refs") or []), "lang": lang,
                 "last_used": today.isoformat()}
        for i, old in enumerate(bank):
            if old["key"] == key and old["lang"] == lang:
                bank[i] = entry
                break
        else:
            bank.append(entry)
        count += 1
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump([{k: e.get(k) for k in FIELDS} for e in bank], sort_keys=False,
                          allow_unicode=True, default_flow_style=False)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return count
