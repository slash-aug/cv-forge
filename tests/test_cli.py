import copy
from pathlib import Path

import pytest
import yaml

from cvforge.cli import main

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
P = str(PERSONA / "master.yaml")
T = str(PERSONA / "tailored.yaml")


def test_validate_ok(capsys):
    assert main(["validate", P]) == 0
    assert capsys.readouterr().out.strip() == "ok"


def test_validate_bad_file(tmp_path, capsys):
    bad = tmp_path / "m.yaml"
    bad.write_text("basics: {}\n", encoding="utf-8")
    assert main(["validate", str(bad)]) == 1
    assert capsys.readouterr().err.strip()


def test_audit_clean(capsys):
    assert main(["audit", T, "--master", P]) == 0


def test_audit_reports_findings(tmp_path, capsys):
    data = yaml.safe_load(Path(T).read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    data["experience"][0]["positions"][0]["bullets"][0]["text"] = "Rebuilt onboarding, tripling activation by 75%."
    bad = tmp_path / "t.yaml"
    bad.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert main(["audit", str(bad), "--master", P]) == 1
    assert "number" in capsys.readouterr().out


def test_build_stops_on_findings(tmp_path, capsys):
    data = yaml.safe_load(Path(T).read_text(encoding="utf-8"))
    data["experience"][0]["positions"][0]["bullets"][0]["text"] = "Doubled activation by 75%."
    bad = tmp_path / "t.yaml"
    bad.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert main(["build", str(bad), "--master", P, "--out", str(tmp_path / "o")]) == 1
    assert not (tmp_path / "o").exists()


@pytest.mark.latex
def test_build_writes_both_pdfs(cfg, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["build", T, "--master", P, "--out", str(out)]) == 0
    assert (out / "Ana_Exemplo_CV_Example_Corp.pdf").exists()
    assert (out / "Ana_Exemplo_Cover_Letter_Example_Corp.pdf").exists()


@pytest.mark.latex
def test_master_cv(cfg, tmp_path, capsys):
    out = tmp_path / "rev"
    assert main(["master-cv", P, "--lang", "en", "--out", str(out)]) == 0
    assert (out / "Ana_Exemplo_CV_master_en.pdf").exists()


def test_master_cv_missing_translation(tmp_path, capsys):
    assert main(["master-cv", P, "--lang", "pt-PT", "--out", str(tmp_path)]) == 1
    assert "pt-PT" in capsys.readouterr().err


def _leaky_master(tmp_path):
    data = yaml.safe_load(Path(P).read_text(encoding="utf-8"))
    data["work"][0]["name"] = "ProjectZebra Payments"
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(path)


def test_build_blocks_confidential_master_field(tmp_path, capsys):
    out = tmp_path / "o"
    assert main(["build", T, "--master", _leaky_master(tmp_path), "--out", str(out)]) == 1
    printed = capsys.readouterr().out
    assert "confidential cv.experience." in printed and ".employer" in printed
    assert not out.exists()


def test_master_cv_blocks_confidential_master_field(tmp_path, capsys):
    out = tmp_path / "o"
    assert main(["master-cv", _leaky_master(tmp_path), "--lang", "en", "--out", str(out)]) == 1
    assert "confidential cv.experience." in capsys.readouterr().out
    assert not out.exists()


def test_build_scans_letter_context(tmp_path, capsys):
    data = yaml.safe_load(Path(P).read_text(encoding="utf-8"))
    data["basics"]["name"] = "Ana Projectzebra"
    master = tmp_path / "m.yaml"
    master.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert main(["build", T, "--master", str(master), "--out", str(tmp_path / "o")]) == 1
    assert "confidential letter.name" in capsys.readouterr().out


def _capture_required(monkeypatch, tmp_path):
    from cvforge import cli
    from cvforge.checks.ats import AtsReport

    seen = []
    monkeypatch.setattr(cli, "load_config", lambda: cli.Config(tmp_path, tmp_path, "lua", "xe"))
    monkeypatch.setattr(cli, "compile_tex", lambda *a, **k: tmp_path / "x.pdf")
    monkeypatch.setattr(cli, "_publish", lambda pdf, out, name: out / name)

    def fake_check(pdf, **kwargs):
        seen.append(kwargs.get("required", []))
        return AtsReport(True, [], "", 1, "stub")

    monkeypatch.setattr(cli, "ats_check", fake_check)
    return seen


CONTACT_TEXTS = ["+351 900 000 000", "ana.exemplo@example.com",
                 "github.com/ana-exemplo", "linkedin.com/in/ana-exemplo"]


def test_build_requires_every_contact_item(monkeypatch, tmp_path):
    seen = _capture_required(monkeypatch, tmp_path)
    assert main(["build", T, "--master", P, "--out", str(tmp_path), "--no-letter"]) == 0
    assert set(CONTACT_TEXTS) <= set(seen[0])


def test_master_cv_requires_every_contact_item(monkeypatch, tmp_path):
    seen = _capture_required(monkeypatch, tmp_path)
    assert main(["master-cv", P, "--lang", "en", "--out", str(tmp_path)]) == 0
    assert set(CONTACT_TEXTS) <= set(seen[0])


def test_build_allows_knockout_figures_in_answers(monkeypatch, tmp_path, capsys):
    from datetime import date

    from cvforge import cli
    from cvforge.answers.facts import knockout_facts
    from cvforge.apply.experience import engineering_months

    _capture_required(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 22))
    master = cli.load_master(Path(P))
    years = knockout_facts(master, engineering_months(master, date(2026, 10, 22)), "en")["years"]
    data = yaml.safe_load(Path(T).read_text(encoding="utf-8"))
    data["answers"] = [{"question": "Years?", "answer": f"{years} of engineering.", "refs": []}]
    app = tmp_path / "app"
    app.mkdir()
    (app / "tailored.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    assert main(["build", str(app / "tailored.yaml"), "--master", P, "--out", str(tmp_path),
                 "--no-letter"]) == 0, capsys.readouterr().out
