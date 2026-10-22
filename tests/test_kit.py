import json
import re
import shutil
from pathlib import Path

from cvforge import cli
from cvforge.apply.posting import Posting
from cvforge.kit.data import build_kit, cut
from cvforge.kit.render import render_kit
from cvforge.profile.model import load_master, load_schema, schema_problems
from cvforge.tailor.audit import load_tailored

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
MASTER = load_master(PERSONA / "master.yaml")
TAILORED = load_tailored(PERSONA / "tailored.yaml")
POSTING = Posting(
    company="Example Corp", title="Senior Full-stack Engineer", location="Remote",
    location_requirements=[], workplace="remote", salary=None, language="en",
    url="https://jobs.example.com/senior", apply_url="https://jobs.example.com/senior/apply",
    source="test", fetched="2026-10-22", description="A fictional role.")
SALARY = {"confirmed": True, "basis": "market", "amount": 60000, "currency": "EUR",
          "period": "year", "brl_month": 30000, "eur_year": 60000, "usd_year": 66000,
          "sources": ["market example 2026"], "rates_day": "2026-10-21"}
EM = chr(0x2014)
FILES = {"cv_pdf": "Ana_Exemplo_CV_Example_Corp.pdf"}


def kit(salary=SALARY, tailored=None, files=FILES):
    return build_kit(MASTER, tailored or TAILORED, POSTING, salary, slug="example-corp", files=files)


def test_kit_json_keys_stable():
    k = kit()
    assert list(k) == ["schema_version", "slug", "lang", "company", "role", "links", "fields",
                       "work", "education", "languages", "certificates", "salary", "answers",
                       "recruiter_note", "tracker"]
    assert k["schema_version"] == 1
    assert list(k["links"]) == ["apply", "posting", "cv_pdf", "letter_pdf"]
    assert k["links"]["letter_pdf"] is None and k["links"]["cv_pdf"] == FILES["cv_pdf"]
    keys = [f["key"] for f in k["fields"]]
    assert keys == ["basics.name", "basics.first_name", "basics.last_name", "basics.email",
                    "basics.phone", "basics.city", "basics.country", "basics.linkedin",
                    "basics.github", "prefs.visa", "prefs.notice", "prefs.relocation"]
    assert all(set(f) == {"key", "label", "value", "group"} for f in k["fields"])
    work = k["work"][0]
    assert set(work) == {"key", "title", "company", "start", "end", "description"}
    assert list(work["description"]) == ["200", "500", "1000", "2000"]
    assert set(k["salary"]) == {"confirmed", "text", "sources"}
    assert schema_problems(k, load_schema("cvforge.kit", "kit.schema.json")) == []


def test_cut_respects_limit_and_words():
    text = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
    for limit in (10, 20, 33, 50):
        out = cut(text, limit)
        assert len(out) <= limit
        assert out and set(out.split()) <= set(text.split())
    assert cut("short", 200) == "short"
    assert cut("x" * 50, 20) == ""  # a single word longer than the limit is dropped, never split


def test_cut_prefers_bullet_boundary():
    bullets = ["- First bullet. With two sentences.", "- Second bullet is here.", "- Third bullet."]
    text = "\n".join(bullets)
    assert cut(text, len(text)) == text
    assert cut(text, len(text) - 1) == "\n".join(bullets[:2])
    assert cut(text, 40) == bullets[0]
    # first bullet alone too long: fall back to whole sentences
    assert cut(text, 20) == "- First bullet."


def test_html_has_no_external_resources():
    page = render_kit(kit())
    assert "<script src" not in page and "<link" not in page
    assert "@import" not in page and "url(" not in page
    assert not re.search(r"\bsrc\s*=", page)
    assert "navigator.clipboard.writeText" in page and "execCommand('copy')" in page
    assert "prefers-color-scheme: dark" in page
    template = (Path(cli.__file__).parent / "kit" / "templates" / "kit.html.j2").read_text(encoding="utf-8")
    assert "http" not in template
    assert 'href="https://jobs.example.com/senior/apply"' in page
    assert 'href="Ana_Exemplo_CV_Example_Corp.pdf"' in page
    assert "Cover_Letter" not in page


def test_no_em_dash_in_kit():
    k = kit()
    page = render_kit(k)
    assert EM not in json.dumps(k, ensure_ascii=False)
    assert EM not in page
    long = {**TAILORED, "experience": [{"ref": "w-examplepay", "positions": [
        {"ref": "p-examplepay-dev", "bullets": [{"ref": "h-load-time", "text": "Word " * 300}]}]}]}
    assert EM not in json.dumps(kit(tailored=long), ensure_ascii=False)


def test_unconfirmed_salary_hidden():
    k = kit({**SALARY, "confirmed": False})
    assert k["salary"]["confirmed"] is False
    assert k["salary"]["text"] == "unconfirmed: run cvforge salary example-corp --confirm"
    assert k["salary"]["sources"] == []
    page = render_kit(k)
    assert "unconfirmed: run cvforge salary example-corp --confirm" in page
    assert "60,000" not in page and "60000" not in page and "30,000" not in page
    assert "60,000" in render_kit(kit())
    assert kit(None)["salary"] is None


def test_persona_kit_builds(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_windows_path", lambda p: None)
    app = tmp_path / "applications" / "example-corp"
    POSTING.save(app)
    shutil.copy(PERSONA / "tailored.yaml", app / "tailored.yaml")
    (app / "Ana_Exemplo_CV_Example_Corp.pdf").write_bytes(b"%PDF")
    (app / "salary.json").write_text(json.dumps({**SALARY, "confirmed": False}), encoding="utf-8")
    assert cli.main(["kit", "example-corp", "--master", str(PERSONA / "master.yaml")]) == 0
    k = json.loads((app / "kit.json").read_text(encoding="utf-8"))
    assert k["links"]["cv_pdf"] == "Ana_Exemplo_CV_Example_Corp.pdf"
    assert k["company"] == "Example Corp" and k["role"] == "Senior Full-stack Engineer"
    assert [(w["key"], w["title"], w["company"], w["start"], w["end"]) for w in k["work"]] == [
        ("work.0", "Senior Engineer", "SampleWorks", "2024-06", None),
        ("work.1", "Tech Lead", "ExamplePay", "2022-03", "2024-05"),
        ("work.2", "Software Engineer", "ExamplePay", "2020-01", "2022-02")]
    assert k["work"][1]["description"]["2000"] == (
        "- Led a team of 5 engineers through two product launches.\n- Payment integration & reconciliation")
    assert k["work"][2]["description"]["2000"] == "- Cut load time by 40% by reworking the checkout bundle."
    assert k["education"][0]["institution"] == "Universidade Exemplo"
    assert [x["name"] for x in k["languages"]] == ["English", "Portuguese"]
    assert k["recruiter_note"]["connect"].startswith("Hi, I am")
    assert k["salary"]["confirmed"] is False
    assert (app / "kit.html").exists()
    assert str(app / "kit.html") in capsys.readouterr().out


def test_cli_unknown_slug(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    assert cli.main(["kit", "nope"]) == 1
    assert "unknown slug" in capsys.readouterr().err


def test_one_block_per_position_with_own_dates_and_bullets():
    page = render_kit(kit())
    assert page.count("Tech Lead") >= 2 and page.index("Tech Lead") < page.index("Software Engineer")
    assert page.count('<h3 class="employer">ExamplePay</h3>') == 1
    assert 'lang="en"' in page


def test_name_fields_use_name_parts_split():
    master = {**MASTER, "basics": {**MASTER["basics"], "name": "Ana Maria Exemplo"}}
    k = build_kit(master, TAILORED, POSTING, None, slug="s", files={})
    values = {f["key"]: f["value"] for f in k["fields"]}
    assert (values["basics.first_name"], values["basics.last_name"]) == ("Ana", "Maria Exemplo")


def test_empty_cut_variant_is_not_rendered():
    word = "x" * 300
    t = {**TAILORED, "experience": [{"ref": "w-examplepay", "positions": [
        {"ref": "p-examplepay-dev", "bullets": [{"ref": "h-load-time", "text": word}]}]}]}
    k = kit(tailored=t)
    assert k["work"][0]["description"]["200"] == ""
    page = render_kit(k)
    assert "up to 200 " not in page and "up to 500 " in page


def test_certificate_without_issuer_renders_cleanly():
    k = kit()
    k["certificates"] = [{"key": "certificates.0", "name": "Example Cloud Practitioner",
                          "issuer": "", "date": ""}]
    page = render_kit(k)
    assert "None" not in page
    assert ">Example Cloud Practitioner</div>" in page
    assert "None" not in render_kit(kit())


def test_lang_attribute_follows_kit_lang():
    k = kit()
    k["lang"] = "pt-BR"
    assert 'lang="pt-BR"' in render_kit(k)
