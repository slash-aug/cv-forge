import io
import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from cvforge.apply.companies import add_company, load_registry
from cvforge.apply.dete import (
    dete_imported,
    dete_key,
    import_year,
    parse_company_xlsx,
    permit_record,
    xlsx_link,
    year_page_links,
)
from cvforge.apply.http import FetchError
from cvforge.cli import main

FIX = Path(__file__).parent / "fixtures" / "dete"
HEADER = ["Employer Name", "Permits Issued Jan", "Permits Issued Grand Total"]


def make_xlsx(rows, sheet="Export") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(["Employment permits issued to companies"])
    ws.append([])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sample() -> bytes:
    return make_xlsx([HEADER, ["Stripe Payments Europe Limited", 3, 41],
                      ["Workhuman Unlimited Company", 1, 5], [None, None, None],
                      ["Grand Total", 4, 46]])


def write_file(tmp_path) -> Path:
    f = tmp_path / "companies-2026.xlsx"
    f.write_bytes(sample())
    return f


def test_parse_company_xlsx():
    data = make_xlsx([HEADER, ["Stripe Payments Europe Limited", 3, 41], ["Grand Total", 3, 41]])
    assert parse_company_xlsx(data) == {"Stripe Payments Europe Limited": 41}


def test_dete_key_strips_irish_suffixes():
    assert dete_key("Workhuman Unlimited Company") == dete_key("Workhuman") == "workhuman"


def test_year_page_links():
    html = '<a href="/en/publications/employment-permit-statistics-2026.html">x</a>' \
           '<a href="/en/Publications/Employment-Permit-Statistics-2022.html">y</a><a href="/en/">z</a>'
    assert year_page_links(html) == {
        2026: "/en/publications/employment-permit-statistics-2026.html",
        2022: "/en/Publications/Employment-Permit-Statistics-2022.html"}


def test_xlsx_link_from_year_page():
    html = (FIX / "statistics-2026.html").read_text()
    assert xlsx_link(html).endswith("employment-permits-issued-to-companies-2026.xlsx")
    assert xlsx_link("<a href='/x.xlsx'>no</a>") is None


def test_import_marks_registry_and_writes_cache(tmp_path):
    add_company(tmp_path / "companies.yaml", "Stripe")
    add_company(tmp_path / "companies.yaml", "Unrelated")
    result = import_year(tmp_path, 2026, file=write_file(tmp_path))
    assert (result.year, result.employers, result.matched) == (2026, 2, ["Stripe"])
    marks = load_registry(tmp_path / "companies.yaml")[0]["sponsor"]
    assert len(marks) == 1 and marks[0]["type"] == "ie-permit" and marks[0]["count"] == 41
    cache = json.loads((tmp_path / "sponsors" / "ie-2026.json").read_text())
    assert cache["year"] == 2026 and cache["employers"]["Workhuman Unlimited Company"] == 5


def test_import_twice_does_not_duplicate_marks(tmp_path):
    add_company(tmp_path / "companies.yaml", "Stripe")
    f = write_file(tmp_path)
    import_year(tmp_path, 2026, file=f)
    f.write_bytes(make_xlsx([HEADER, ["Stripe Payments Europe Limited", 3, 50]]))
    import_year(tmp_path, 2026, file=f)
    marks = load_registry(tmp_path / "companies.yaml")[0]["sponsor"]
    assert [m["count"] for m in marks] == [50]


def test_import_fetches_through_index_and_year_page(tmp_path):
    seen = []
    pages = {
        "https://enterprise.gov.ie/idx/": b'<a href="/en/publications/employment-permit-statistics-2026.html">',
        "https://enterprise.gov.ie/en/publications/employment-permit-statistics-2026.html":
            (FIX / "statistics-2026.html").read_bytes(),
        "https://enterprise.gov.ie/en/publications/publication-files/"
        "employment-permits-issued-to-companies-2026.xlsx": sample(),
    }

    def fetch(url):
        seen.append(url)
        return pages[url]

    result = import_year(tmp_path, 2026, fetch=fetch, index_url="https://enterprise.gov.ie/idx/")
    assert result.employers == 2 and len(seen) == 3


def test_permit_record_from_cache_without_registry(tmp_path):
    import_year(tmp_path, 2026, file=write_file(tmp_path))
    assert permit_record(tmp_path, "Stripe", None) == (2026, 41)
    assert permit_record(tmp_path, "Nobody", None) is None
    assert dete_imported(tmp_path)


def test_permit_record_from_registry_mark(tmp_path):
    entry = {"sponsor": [{"type": "ie-permit", "count": 7, "date": "2026-01-01",
                          "source": "DETE employment permits issued to companies 2025"}]}
    assert permit_record(tmp_path, "Stripe", entry) == (2025, 7)


def test_permit_record_missing_or_broken_cache(tmp_path):
    assert permit_record(tmp_path, "Stripe", None) is None
    assert not dete_imported(tmp_path)
    (tmp_path / "sponsors").mkdir()
    (tmp_path / "sponsors" / "ie-2026.json").write_text("{")
    assert permit_record(tmp_path, "Stripe", None) is None
    assert not dete_imported(tmp_path)


def test_refuses_non_dete_host(tmp_path):
    with pytest.raises(FetchError):
        import_year(tmp_path, 2026, fetch=lambda u: b"", index_url="https://evil.example/")


def test_cli_import_ie(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    add_company(tmp_path / "companies.yaml", "Stripe")
    assert main(["company", "import-ie", "--year", "2026", "--file", str(write_file(tmp_path))]) == 0
    assert "ie 2026: 2 employers, 1 registry matches" in capsys.readouterr().out
    assert main(["company", "show", "Stripe"]) == 0
    assert "41 permits" in capsys.readouterr().out


def _import_names(tmp_path, registry_name, names):
    add_company(tmp_path / "companies.yaml", registry_name)
    f = tmp_path / "c.xlsx"
    f.write_bytes(make_xlsx([HEADER, *[[n, 1, 10] for n in names]]))
    import_year(tmp_path, 2026, file=f)
    return load_registry(tmp_path / "companies.yaml")[0]["sponsor"]


def test_suffix_inside_a_name_is_kept(tmp_path):
    assert dete_key("Bank of Ireland") == "bank of ireland"
    marks = _import_names(tmp_path, "Bank of Ireland",
                          ["Bank of America Europe DAC", "Bank of China (Europe) S.A."])
    assert marks == []


def test_generic_key_gets_no_prefix_match(tmp_path):
    assert _import_names(tmp_path, "Kerry", ["Kerry Fish Trawlers"]) == []


def test_prefix_match_records_matched_names(tmp_path):
    marks = _import_names(tmp_path, "Stripe", ["Stripe Payments Europe Limited"])
    assert marks[0]["matched"] == ["Stripe Payments Europe Limited"] and marks[0]["count"] == 10


def test_reimport_removes_mark_when_no_longer_matching(tmp_path):
    _import_names(tmp_path, "Stripe", ["Stripe Payments Europe Limited"])
    f = tmp_path / "c.xlsx"
    f.write_bytes(make_xlsx([HEADER, ["Other Co", 1, 2]]))
    import_year(tmp_path, 2026, file=f)
    assert load_registry(tmp_path / "companies.yaml")[0]["sponsor"] == []


def make_2025_xlsx(rows) -> bytes:
    """The 2025 layout: sheet "Sheet1", no name header, months, then "Grand Total"."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    months = ["January", "February", "December"]
    ws.append([None, *months, "Grand Total", None])
    ws.append(["Grand Total", 9, 9, 9, 27, None])
    for name, total in rows:
        ws.append([name, None, None, total, total, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_2025_layout():
    data = make_2025_xlsx([(" Stripe Payments Europe Limited", 12), ("Workhuman Unlimited Company", 3)])
    assert parse_company_xlsx(data) == {"Stripe Payments Europe Limited": 12,
                                        "Workhuman Unlimited Company": 3}


def test_parse_skips_total_row():
    data = make_xlsx([HEADER, ["Stripe Payments Europe Limited", 3, 41], ["Total", 3, 41]])
    assert parse_company_xlsx(data) == {"Stripe Payments Europe Limited": 41}


def test_parse_without_header_row_fails():
    from cvforge.apply.dete import DeteError

    with pytest.raises(DeteError):
        parse_company_xlsx(make_xlsx([["Stripe", 1]], sheet="Sheet1"))


def test_import_2025_layout_marks_registry(tmp_path):
    add_company(tmp_path / "companies.yaml", "Stripe")
    f = tmp_path / "companies-2025.xlsx"
    f.write_bytes(make_2025_xlsx([(" Stripe Payments Europe Limited", 12)]))
    result = import_year(tmp_path, 2025, file=f)
    assert result.matched == ["Stripe"] and result.employers == 1


@pytest.mark.parametrize("registry, dete_name", [
    ("Railway", "Railway & Steam Packet Union SC"),
    ("Remote", "Remote Management Technology Limited"),
    ("Citi", "Citi Bus Limited"),
])
def test_prefix_of_another_business_is_only_possible(tmp_path, registry, dete_name):
    add_company(tmp_path / "companies.yaml", registry)
    f = tmp_path / "c.xlsx"
    f.write_bytes(make_xlsx([HEADER, [dete_name, 1, 10]]))
    result = import_year(tmp_path, 2026, file=f)
    assert result.matched == [] and result.possible == {registry: [dete_name]}
    assert load_registry(tmp_path / "companies.yaml")[0]["sponsor"] == []


@pytest.mark.parametrize("registry, dete_name", [
    ("Stripe", "Stripe Payments Europe Limited"),
    ("Intercom", "Intercom R&D Unlimited Company"),
    ("Okta", "Okta Identity Ireland Limited"),
    ("Workato", "Workato Hibernia Limited"),
    ("Notion", "Notion Labs, Ireland Limited"),
    ("Version 1", "Version 1 Software Limited"),
    ("Zendesk", "Zendesk International Limited"),
    ("Crusoe", "Crusoe AI Ireland Limited"),
    ("Indra", "Indra Sistemas S.A Irish Branch"),
    ("J & E Davy", "J & E Davy Holdings Unlimited Company"),
])
def test_prefix_with_entity_descriptors_matches(tmp_path, registry, dete_name):
    marks = _import_names(tmp_path, registry, [dete_name])
    assert marks and marks[0]["matched"] == [dete_name]


def test_cli_import_ie_prints_possible_match(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    add_company(tmp_path / "companies.yaml", "Railway")
    f = tmp_path / "c.xlsx"
    f.write_bytes(make_xlsx([HEADER, ["Railway & Steam Packet Union SC", 1, 10]]))
    assert main(["company", "import-ie", "--year", "2026", "--file", str(f)]) == 0
    out = capsys.readouterr().out
    assert ("  Railway: possible match Railway & Steam Packet Union SC, add an alias to confirm"
            in out)


def test_cli_import_ie_missing_file_is_clean(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    assert main(["company", "import-ie", "--year", "2026", "--file",
                 str(tmp_path / "missing.xlsx")]) == 1
    err = capsys.readouterr().err
    assert "ie 2026: cannot read" in err and "Traceback" not in err


def test_cli_import_ie_unpublished_year_is_a_notice(tmp_path, monkeypatch, capsys):
    from cvforge import cli
    from cvforge.apply import dete

    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_today", lambda: __import__("datetime").date(2027, 1, 5))

    def fake(data_dir, year, **kw):
        if year == 2027:
            raise dete.NoYearPage("no DETE statistics page for 2027")
        return dete.ImportResult(year, 3)

    monkeypatch.setattr(dete, "import_year", fake)
    assert main(["company", "import-ie"]) == 0
    out = capsys.readouterr().out
    assert "ie 2027: not published yet, skipped" in out and "ie 2026: 3 employers" in out
    assert main(["company", "import-ie", "--year", "2027"]) == 1
