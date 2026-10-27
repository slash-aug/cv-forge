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
