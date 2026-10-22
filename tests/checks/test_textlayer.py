# Ported from ai-job-search (MIT): tests/test_verify_pdf.py
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from cvforge.checks.textlayer import (
    VerificationError,
    extract_text_layer,
    find_non_ascii_date_ranges,
    normalize_text,
    parse_page_count,
    run_tool,
)


class ParsePageCountTests(unittest.TestCase):
    def test_parses_pdfinfo_page_count(self):
        self.assertEqual(parse_page_count("Title: Example\nPages:          2\n"), 2)

    def test_rejects_output_without_page_count(self):
        with self.assertRaisesRegex(VerificationError, "did not contain a page count"):
            parse_page_count("Title: Example\n")


class NormalizeTextTests(unittest.TestCase):
    """Required strings must see through what LaTeX does to plain source text.

    With lualatex the apostrophe in `Master's` reaches the text layer as U+2019
    and the `--` in `2016--2024` as U+2013, so a whitespace-only fold reports
    both missing from a CV that plainly contains them. Under pdflatex without
    T1 font encoding, accents arrive decomposed (`e` + U+0300) instead of
    precomposed.
    """

    def test_folds_curly_apostrophe_to_ascii(self):
        self.assertEqual(normalize_text("Master\u2019s degree"), "Master's degree")
        self.assertEqual(normalize_text("\u2018quoted\u2019"), "'quoted'")

    def test_folds_curly_double_quotes_to_ascii(self):
        self.assertEqual(normalize_text("\u201cSix Sigma\u201d"), '"Six Sigma"')

    def test_folds_en_and_em_dashes_to_hyphen(self):
        self.assertEqual(normalize_text("2016\u20132024"), "2016-2024")
        self.assertEqual(normalize_text("role\u2014title"), "role-title")

    def test_folds_no_break_space_to_space(self):
        self.assertEqual(normalize_text("EUR\u00a0600k"), "EUR 600k")

    def test_folds_decomposed_accents_to_nfc(self):
        decomposed = "Gene\u0300ve Universite\u0301"
        precomposed = "Gen\u00e8ve Universit\u00e9"
        self.assertEqual(normalize_text(decomposed), precomposed)

    def test_still_collapses_whitespace(self):
        self.assertEqual(normalize_text("Professional\n   Experience "), "Professional Experience")

    def test_fold_is_symmetric(self):
        # A user who pastes the curly form from a posting must match an ASCII layer too.
        self.assertEqual(normalize_text("Master\u2019s"), normalize_text("Master's"))


class FindNonAsciiDateRangesTests(unittest.TestCase):
    """The date-range rule reads the raw layer; the comparison fold cannot.

    A Workday import dropped a role's end date because `2016--2024` reaches the
    text layer as `2016<U+2013>2024`. The fold that makes a required "2016-2024"
    pass on that layer is what makes it unable to detect the defect, so this
    check never folds.

    Newline cases: whitespace between year and dash must not match a line
    break, or a heading ending in an ASCII date would join a dash that merely
    opens the next line.
    """

    def test_en_dash_between_years_is_reported_with_its_code_point(self):
        hits = find_non_ascii_date_ranges("Six Sigma Green Belt, 2016\u20132024.\n")
        self.assertEqual(hits, [("Six Sigma Green Belt, 2016\u20132024.", "\u2013")])

    def test_ascii_hyphen_range_is_clean(self):
        self.assertEqual(find_non_ascii_date_ranges("2016-2024\nMar 2016 - Jul 2016\n"), [])

    def test_a_year_on_either_side_of_the_dash_is_enough(self):
        # Month-qualified and open-ended ranges: the year is only on one side.
        for text in ("Mar 2016 \u2013 Jul 2016", "2016 \u2013 Present", "\u2013 2024"):
            with self.subTest(text=text):
                self.assertEqual(len(find_non_ascii_date_ranges(text)), 1)

    def test_other_unicode_dashes_and_the_minus_sign_are_caught(self):
        for dash in ("\u2010", "\u2011", "\u2012", "\u2014", "\u2015", "\u2212"):
            with self.subTest(dash=dash):
                self.assertEqual(find_non_ascii_date_ranges(f"2016{dash}2024")[0][1], dash)

    def test_numeric_range_without_a_year_is_not_a_date(self):
        # Prose ranges like EUR 600k--1M keep `--`.
        self.assertEqual(find_non_ascii_date_ranges("EUR 600k\u20131M, 12\u201315 people"), [])

    def test_year_like_digits_inside_a_longer_number_are_not_a_year(self):
        # `2000` sits inside `120000`, `200000`, `12000`, `15000`: a budget or
        # throughput range typed with `--` is not a date and must not be flagged.
        for text in ("Grew budget DKK 120000\u2013200000", "Scaled ingestion from 12000\u201315000 events/s"):
            with self.subTest(text=text):
                self.assertEqual(find_non_ascii_date_ranges(text), [])

    def test_numeric_range_with_year_shaped_ends_is_a_quantity_not_a_date(self):
        # Four-digit numbers that are not both years: bounded the year but
        # a salary band or a throughput range still read as a date range.
        for text in (
            "Salary EUR 1500\u20132000 per month",
            "Scaled the API to serve 2000\u20135000 requests per second",
            "Grew users from 2000\u20135000",
            "Budget 1.5\u20132.0M, headcount 20\u201325",
        ):
            with self.subTest(text=text):
                self.assertEqual(find_non_ascii_date_ranges(text), [])

    def test_numerically_formatted_date_ranges_are_still_caught(self):
        # A composite token (slashed, dotted, hyphenated) is not a bare number,
        # so the quantity rule does not apply and the year rule still fires.
        # These are the Workday-drops-the-date shape the flag exists for.
        for text in (
            "03/2016\u201307/2024",
            "01.2016 \u2013 12.2024",
            "2016-03\u20132024-07",
            "2016/17\u20132018/19",
            "2016/03\u20132024/07",
            "01.03.2016\u201331.07.2024",
            "2016\u201307/2024",
        ):
            with self.subTest(text=text):
                self.assertEqual(len(find_non_ascii_date_ranges(text)), 1)

    def test_year_and_two_digit_year_is_a_date_range(self):
        # The academic-year and season form, caught before the quantity rule
        #  and suppressed by it because `17` is a bare non-year number.
        for text in ("MSc Physics, 2016\u201317", "Sep 2016\u201317", "2019\u201320 season", "2016 \u2013 17"):
            with self.subTest(text=text):
                self.assertEqual(len(find_non_ascii_date_ranges(text)), 1)

    def test_two_digit_number_before_a_year_is_still_a_quantity(self):
        # Only year-first is the date form; `17-2016` is not a date anyone writes.
        self.assertEqual(find_non_ascii_date_ranges("items 17\u20132016"), [])

    def test_two_years_joined_by_a_dash_are_still_a_date_range(self):
        for text in ("2016\u20132024", "1990\u20132010 programme", "Roles 2000\u20132024"):
            with self.subTest(text=text):
                self.assertEqual(len(find_non_ascii_date_ranges(text)), 1)

    def test_a_standalone_year_next_to_a_longer_number_is_still_caught(self):
        self.assertEqual(find_non_ascii_date_ranges("2016\u20132024 (120000 users)")[0][1], "\u2013")

    def test_year_ending_a_line_is_not_joined_to_the_next_lines_dash(self):
        text = "Heading 1988-1994\n\u2013 note\n"
        self.assertEqual(find_non_ascii_date_ranges(text), [])

    def test_dash_ending_a_line_is_not_joined_to_the_next_lines_year(self):
        text = "Six Sigma \u2013\n2016 onwards\n"
        self.assertEqual(find_non_ascii_date_ranges(text), [])

    def test_same_line_spaces_around_the_dash_are_still_caught(self):
        self.assertEqual(len(find_non_ascii_date_ranges("1988 \u2013 1994")), 1)

    def test_hits_are_reported_in_document_order_one_per_range(self):
        text = "2016\u20132024 role\nmore text\nJan 2010 \u2013 Dec 2012 degree\n"
        self.assertEqual(
            [line for line, _ in find_non_ascii_date_ranges(text)],
            ["2016\u20132024 role", "Jan 2010 \u2013 Dec 2012 degree"],
        )


class ExtractTextLayerTests(unittest.TestCase):
    def setUp(self):
        self.pdf = Path("example.pdf")

    @patch("cvforge.checks.textlayer.shutil.which", return_value="/usr/bin/pdftotext")
    @patch("cvforge.checks.textlayer._extract_pypdf", return_value=("pypdf text", 1))
    @patch("cvforge.checks.textlayer.run_tool")
    def test_pdftotext_is_preferred_when_installed(self, mock_run_tool, _pypdf, _which):
        mock_run_tool.side_effect = ["poppler text", "Pages:          2\n"]
        text, pages, extractor = extract_text_layer(self.pdf)
        self.assertEqual(extractor, "pdftotext")
        self.assertEqual(text, "poppler text")
        self.assertEqual(pages, 2)
        self.assertEqual(mock_run_tool.call_args_list[0][0][0][:3], ["pdftotext", "-layout", "-enc"])

    @patch("cvforge.checks.textlayer.shutil.which", return_value=None)
    @patch("cvforge.checks.textlayer._extract_pypdf", return_value=("Hello ATS body", 1))
    def test_pypdf_is_used_when_pdftotext_is_absent(self, _pypdf, _which):
        text, pages, extractor = extract_text_layer(self.pdf)
        self.assertEqual((text, pages, extractor), ("Hello ATS body", 1, "pypdf"))

    @patch("cvforge.checks.textlayer.shutil.which", return_value="/usr/bin/pdftotext")
    @patch("cvforge.checks.textlayer._extract_pypdf", return_value=("pypdf text", 1))
    @patch("cvforge.checks.textlayer.run_tool", side_effect=VerificationError("boom"))
    def test_pypdf_is_the_fallback_when_pdftotext_fails(self, _run, _pypdf, _which):
        self.assertEqual(extract_text_layer(self.pdf)[2], "pypdf")

    @patch("cvforge.checks.textlayer.shutil.which", return_value=None)
    @patch("cvforge.checks.textlayer._extract_pypdf", return_value=None)
    def test_no_usable_extractor_raises(self, _pypdf, _which):
        with self.assertRaises(VerificationError):
            extract_text_layer(self.pdf)


class RunToolTests(unittest.TestCase):
    @patch("cvforge.checks.textlayer.subprocess.run", side_effect=FileNotFoundError)
    def test_reports_missing_poppler_command(self, _mock_run):
        with self.assertRaisesRegex(VerificationError, "Install poppler-utils"):
            run_tool(["pdftotext", "example.pdf", "-"])

    @patch("cvforge.checks.textlayer.subprocess.run")
    def test_reports_unreadable_pdf(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["pdfinfo", "example.pdf"], stderr="invalid PDF"
        )

        with self.assertRaisesRegex(VerificationError, "invalid PDF"):
            run_tool(["pdfinfo", "example.pdf"])


if __name__ == "__main__":
    unittest.main()
