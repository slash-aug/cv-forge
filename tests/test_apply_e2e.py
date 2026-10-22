"""Apply flow end to end on the persona: no network, no LaTeX unless marked."""
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from cvforge import cli
from cvforge.apply import http as apply_http

TODAY = date(2026, 10, 22)
PERSONA = Path(__file__).resolve().parents[1] / "examples" / "persona"
MASTER = str(PERSONA / "master.yaml")
SLUG = "example-corp-senior-full-stack-engineer"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_today", lambda: TODAY)

    def no_net(url, **kw):
        raise apply_http.FetchError("network must not be used")

    monkeypatch.setattr(apply_http, "get", no_net)
    (tmp_path / "salary").mkdir()
    (tmp_path / "salary" / f"ecb-{TODAY.isoformat()}.json").write_text(
        json.dumps({"day": "2026-10-21",
                    "per_eur": {"EUR": 1.0, "USD": 1.10, "BRL": 6.00, "GBP": 0.85}}),
        encoding="utf-8")
    return tmp_path


def _apply_until_audit(data_dir, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", (PERSONA / "posting.txt").open(encoding="utf-8"))
    assert cli.main(["intake", "-", "--company", "Example Corp",
                     "--role", "Senior Full-stack Engineer"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == SLUG
    app = data_dir / "applications" / SLUG
    shutil.copy(PERSONA / "requirements.yaml", app / "requirements.yaml")
    assert cli.main(["check", SLUG, "--master", MASTER]) == 0
    shutil.copy(PERSONA / "tailored.yaml", app / "tailored.yaml")
    assert cli.main(["audit", str(app / "tailored.yaml"), "--master", MASTER]) == 0
    return app


def test_apply_e2e(data_dir, monkeypatch, capsys):
    app = _apply_until_audit(data_dir, monkeypatch, capsys)
    assert cli.main(["salary", SLUG, "--master", MASTER]) == 0
    assert (app / "salary.json").exists()
    assert cli.main(["kit", SLUG, "--master", MASTER]) == 0
    assert (app / "kit.json").exists() and (app / "kit.html").exists()
    assert cli.main(["track", "status", SLUG, "applied"]) == 0
    capsys.readouterr()
    assert cli.main(["due"]) == 0
    assert SLUG not in capsys.readouterr().out
    assert cli.main(["intake", "-", "--company", "Example Corp",
                     "--role", "Senior Full-stack Engineer"]) == 3


@pytest.mark.latex
def test_apply_e2e_build(data_dir, monkeypatch, capsys):
    app = _apply_until_audit(data_dir, monkeypatch, capsys)
    assert cli.main(["build", str(app / "tailored.yaml"), "--master", MASTER,
                     "--out", str(app)]) == 0
    assert list(app.glob("*_CV_*.pdf")) and list(app.glob("*Cover_Letter*.pdf"))
    assert cli.main(["kit", SLUG, "--master", MASTER]) == 0
    kit = json.loads((app / "kit.json").read_text(encoding="utf-8"))
    assert kit["links"]["cv_pdf"] and kit["links"]["letter_pdf"]
