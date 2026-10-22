"""Compiled-CV layout guarantees: contact wraps between items, entries keep their bullets."""
import copy
from pathlib import Path

import pytest
import yaml

from cvforge.build import compile_tex
from cvforge.checks.textlayer import extract_text_layer, normalize_text
from cvforge.cli import main
from cvforge.profile.model import load_master
from cvforge.render.cv import build_cv_view, render_view
from cvforge.tailor.audit import load_tailored

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
M = load_master(PERSONA / "master.yaml")
T = load_tailored(PERSONA / "tailored.yaml")

LONG_PROFILES = [
    {"network": "GitHub", "url": "https://github.com/ana-exemplo-engineering-portfolio"},
    {"network": "LinkedIn", "url": "https://www.linkedin.com/in/ana-exemplo-full-stack-engineer"},
    {"network": "Site", "url": "https://ana-exemplo-engineering.example.com/portfolio"},
]


@pytest.mark.latex
def test_long_contact_line_keeps_every_item(cfg):
    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    master = copy.deepcopy(M)
    master["basics"]["email"] = "ana.exemplo.full.stack.engineer@example.com"
    master["basics"]["profiles"] = LONG_PROFILES
    view = build_cv_view(T, master)
    pdf = compile_tex(render_view(view), engine=cfg.lualatex,
                      build_dir=cfg.build_dir / "test_layout", jobname="contact")
    text = normalize_text(extract_text_layer(pdf)[0])
    for link in view["contact"]["links"]:
        assert normalize_text(link["text"]) in text, link["text"]


def _long_master() -> dict:
    master = copy.deepcopy(M)
    bullet = ("Delivered a cross-team platform change with careful rollout, monitoring and "
              "written follow-up so that the product teams could adopt it safely")
    for i in range(12):
        master["work"].append({
            "id": f"w-extra-{i}", "name": f"Extra Company {i}", "location": "Porto, Portugal",
            "x-mode": "onsite",
            "positions": [{
                "id": f"p-extra-{i}", "title": f"Engineer level {i}",
                "startDate": f"{2010 - i}-01", "endDate": f"{2010 - i}-12",
                "highlights": [{"id": f"h-extra-{i}-{k}", "impact": f"{bullet} ({k}).", "angles": ["team-lead"]}
                               for k in range(1 + i % 5)],
            }],
        })
    return master


@pytest.mark.latex
def test_long_master_cv_has_no_orphaned_entry_headers(cfg, tmp_path, capsys):
    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    master = tmp_path / "long.yaml"
    master.write_text(yaml.safe_dump(_long_master(), allow_unicode=True), encoding="utf-8")
    assert main(["master-cv", str(master), "--lang", "en", "--out", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    pages = int(out.split("ok (")[-1].split(" page")[0]) if "ok (" in out else 0
    assert pages >= 3, out
    assert "orphaned" not in out and "ends on" not in out, out
