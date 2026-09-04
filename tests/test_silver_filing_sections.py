"""Tests for Silver SEC filing-section transformation logic."""

from __future__ import annotations

import hashlib
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.silver_filing_sections import (
    BronzeFilingDocument,
    select_latest_filing_documents,
    transform_filing_document,
    transform_filing_sections_snapshot,
)


FETCHED_AT = datetime(
    2026,
    9,
    3,
    9,
    45,
    41,
    tzinfo=timezone.utc,
)


def _long_text(label: str, *, length: int = 800) -> str:
    repeated = (
        f"{label} operations products customers employees markets "
        "technology strategy competition regulation research development "
    )
    return (repeated * ((length // len(repeated)) + 2))[:length]


def _context(
    context_id: str,
    *,
    cik: str = "0000320193",
    period_end: str = "2025-09-27",
    scheme: str = "http://www.sec.gov/CIK",
) -> str:
    return f"""
    <xbrli:context id="{context_id}">
      <xbrli:entity>
        <xbrli:identifier scheme="{scheme}">{cik}</xbrli:identifier>
      </xbrli:entity>
      <xbrli:period>
        <xbrli:startDate>2024-09-29</xbrli:startDate>
        <xbrli:endDate>{period_end}</xbrli:endDate>
      </xbrli:period>
    </xbrli:context>
    """


def _identity_facts(
    *,
    cik: str = "0000320193",
    document_type: str = "10-K",
    period_end: str = "September 27, 2025",
    contextref: str = "c1",
    extra: str = "",
) -> str:
    return f"""
    <ix:nonNumeric name="dei:EntityCentralIndexKey" contextref="{contextref}">
      {cik}
    </ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentType" contextref="{contextref}">
      {document_type}
    </ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentPeriodEndDate" contextref="{contextref}">
      {period_end}
    </ix:nonNumeric>
    {extra}
    """


def _filing_html(
    *,
    item_1: str | None = None,
    item_1a: str | None = None,
    end_heading: str = "Item 1B. Unresolved Staff Comments",
    toc: bool = True,
    fragmented: bool = False,
    identity: str | None = None,
    context: str | None = None,
    pre_body: str = "",
) -> str:
    item_1 = item_1 if item_1 is not None else _long_text("business")
    item_1a = item_1a if item_1a is not None else _long_text("risk")

    if fragmented:
        item_1_heading = "Item 1. B usiness"
        item_1a_heading = "Item 1A. Ris k Factors"
    else:
        item_1_heading = "Item 1. Business"
        item_1a_heading = "Item 1A. Risk Factors"

    toc_html = ""

    if toc:
        toc_html = """
        <table>
          <tr><td>Item 1. Business</td><td>1</td></tr>
          <tr><td>Item 1A. Risk Factors</td><td>5</td></tr>
          <tr><td>Item 1B. Unresolved Staff Comments</td><td>17</td></tr>
          <tr><td>Item 1C. Cybersecurity</td><td>17</td></tr>
          <tr><td>Item 2. Properties</td><td>17</td></tr>
        </table>
        """

    identity = identity if identity is not None else _identity_facts()
    context = context if context is not None else _context("c1")

    return f"""
    <html>
      <head>
        <style>.hidden {{ display:none; }}</style>
        <script>Item 1. Business fake script text</script>
      </head>
      <body>
        <ix:header>
          <ix:hidden>Item 1A. Risk Factors hidden xbrl text</ix:hidden>
        </ix:header>
        {context}
        {identity}
        {toc_html}
        <p>
          This report includes forward-looking statements.
          Business (Part I, Item 1 of this Form 10-K) and
          Risk Factors (Part I, Item 1A of this Form 10-K)
          are referenced here but this is not a section heading.
        </p>
        {pre_body}
        <div>{item_1_heading}</div>
        <div>{item_1}</div>
        <div>{item_1a_heading}</div>
        <div>{item_1a}</div>
        <div>{end_heading}</div>
        <div>{_long_text("later section", length=550)}</div>
      </body>
    </html>
    """


def _bronze_response(
    html: str | None = None,
    *,
    response_id: str = "response-a",
    project_symbol: str = "AAPL",
    sec_cik: str = "0000320193",
    accession_number: str = "0000320193-25-000079",
    filing_form: str = "10-K",
    filing_date: date = date(2025, 10, 31),
    report_date: date = date(2025, 9, 27),
    primary_document: str = "aapl-20250927.htm",
    fetched_at: datetime = FETCHED_AT,
    ingestion_run_id: str = "run-1",
) -> BronzeFilingDocument:
    html = html if html is not None else _filing_html()
    payload = html.encode("utf-8")
    accession_path = accession_number.replace("-", "")
    cik_path = str(int(sec_cik))

    source_url = (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_path}/{accession_path}/{primary_document}"
    )

    return BronzeFilingDocument(
        source_response_id=response_id,
        source_system="sec",
        source_endpoint="filing_document",
        project_symbol=project_symbol,
        sec_cik=sec_cik,
        accession_number=accession_number,
        filing_form=filing_form,
        filing_date=filing_date,
        report_date=report_date,
        primary_document=primary_document,
        source_url=source_url,
        http_status=200,
        response_payload_html=html,
        response_bytes=len(payload),
        response_sha256=hashlib.sha256(payload).hexdigest(),
        fetched_at=fetched_at,
        ingestion_run_id=ingestion_run_id,
    )


class FilingSelectionTests(unittest.TestCase):
    def test_selects_latest_filing_then_latest_retrieval(self) -> None:
        older_filing = _bronze_response(
            response_id="old-filing",
            accession_number="0000320193-24-000123",
            filing_date=date(2024, 11, 1),
            report_date=date(2024, 9, 28),
            primary_document="aapl-20240928.htm",
        )
        older_retrieval = _bronze_response(
            response_id="old-retrieval",
            fetched_at=FETCHED_AT - timedelta(minutes=5),
        )
        latest = _bronze_response(response_id="latest")

        result = select_latest_filing_documents(
            [older_filing, older_retrieval, latest],
            {"AAPL": "0000320193"},
        )

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(
            result.selected[0].source_response_id,
            "latest",
        )
        self.assertEqual(result.superseded_response_count, 2)

    def test_ambiguous_latest_accessions_fail(self) -> None:
        first = _bronze_response(response_id="a")
        second = _bronze_response(
            response_id="b",
            accession_number="0000320193-25-000081",
            primary_document="aapl-other.htm",
        )

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            select_latest_filing_documents(
                [first, second],
                {"AAPL": "0000320193"},
            )

    def test_tied_identical_html_uses_smallest_response_id(self) -> None:
        html = _filing_html()
        response_b = _bronze_response(html, response_id="b")
        response_a = _bronze_response(html, response_id="a")

        result = select_latest_filing_documents(
            [response_b, response_a],
            {"AAPL": "0000320193"},
        )

        self.assertEqual(
            result.selected[0].source_response_id,
            "a",
        )
        self.assertEqual(result.tie_repeat_count, 1)

    def test_tied_different_html_fails(self) -> None:
        first = _bronze_response(
            _filing_html(item_1=_long_text("first")),
            response_id="a",
        )
        second = _bronze_response(
            _filing_html(item_1=_long_text("second")),
            response_id="b",
        )

        with self.assertRaisesRegex(
            ValueError,
            "different raw HTML",
        ):
            select_latest_filing_documents(
                [first, second],
                {"AAPL": "0000320193"},
            )

    def test_out_of_scope_company_is_ignored(self) -> None:
        aapl = _bronze_response()
        googl = _bronze_response(
            _filing_html(
                identity=_identity_facts(cik="0001652044"),
                context=_context("c1", cik="0001652044"),
            ),
            response_id="googl",
            project_symbol="GOOGL",
            sec_cik="0001652044",
            accession_number="0001652044-25-000001",
            primary_document="googl.htm",
        )

        result = select_latest_filing_documents(
            [aapl, googl],
            {"AAPL": "0000320193"},
        )

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.out_of_scope_response_count, 1)

    def test_mismatched_configured_cik_fails(self) -> None:
        response = _bronze_response(
            sec_cik="0000789019",
            accession_number="0001193125-26-323660",
            primary_document="msft.htm",
        )

        with self.assertRaisesRegex(
            ValueError,
            "does not match configured CIK",
        ):
            select_latest_filing_documents(
                [response],
                {"AAPL": "0000320193"},
            )

    def test_non_ascii_cik_is_rejected(self) -> None:
        response = _bronze_response()
        corrupted = BronzeFilingDocument(
            **{
                **response.__dict__,
                "sec_cik": "٠٠٠٠٣٢٠١٩٣",
            }
        )

        with self.assertRaisesRegex(ValueError, "ASCII digits"):
            select_latest_filing_documents(
                [corrupted],
                {"AAPL": "0000320193"},
            )


class FilingIdentityTests(unittest.TestCase):
    def test_valid_identity_is_accepted(self) -> None:
        sections = transform_filing_document(
            _bronze_response(),
            expected_cik="0000320193",
        )
        self.assertEqual(len(sections), 2)

    def test_document_type_must_match_bronze(self) -> None:
        html = _filing_html(
            identity=_identity_facts(document_type="10-Q")
        )

        with self.assertRaisesRegex(ValueError, "DocumentType"):
            transform_filing_document(
                _bronze_response(html),
                expected_cik="0000320193",
            )

    def test_document_period_end_must_match_report_date(self) -> None:
        html = _filing_html(
            identity=_identity_facts(
                period_end="September 28, 2025"
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "DocumentPeriodEndDate",
        ):
            transform_filing_document(
                _bronze_response(html),
                expected_cik="0000320193",
            )

    def test_nested_inline_xbrl_period_end_date_is_accepted(self) -> None:
        identity = """
        <ix:nonNumeric name="dei:EntityCentralIndexKey" contextref="c1">
          0000320193
        </ix:nonNumeric>
        <ix:nonNumeric name="dei:DocumentType" contextref="c1">
          10-K
        </ix:nonNumeric>
        <ix:nonNumeric
          name="dei:DocumentPeriodEndDate"
          contextref="c1"
          format="ixt:date-monthname-day-year-en"
        >
          <ix:nonNumeric
            name="dei:CurrentFiscalYearEndDate"
            contextref="c1"
            format="ixt:date-monthname-day-en"
          >
            September&nbsp;27
          </ix:nonNumeric>, 2025
        </ix:nonNumeric>
        """

        sections = transform_filing_document(
            _bronze_response(
                _filing_html(identity=identity)
            ),
            expected_cik="0000320193",
        )

        self.assertEqual(len(sections), 2)

    def test_conflicting_repeated_dei_fact_fails(self) -> None:
        extra = """
        <ix:nonNumeric name="dei:DocumentType" contextref="c1">
          10-Q
        </ix:nonNumeric>
        """
        html = _filing_html(
            identity=_identity_facts(extra=extra)
        )

        with self.assertRaisesRegex(
            ValueError,
            "conflicting values",
        ):
            transform_filing_document(
                _bronze_response(html),
                expected_cik="0000320193",
            )

    def test_context_cik_must_match(self) -> None:
        html = _filing_html(
            context=_context(
                "c1",
                cik="0000789019",
            )
        )

        with self.assertRaisesRegex(ValueError, "context .* CIK"):
            transform_filing_document(
                _bronze_response(html),
                expected_cik="0000320193",
            )

    def test_context_period_end_must_match(self) -> None:
        html = _filing_html(
            context=_context(
                "c1",
                period_end="2025-09-28",
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "context .* period end",
        ):
            transform_filing_document(
                _bronze_response(html),
                expected_cik="0000320193",
            )

    def test_unsupported_context_identifier_scheme_fails(self) -> None:
        html = _filing_html(
            context=_context(
                "c1",
                scheme="urn:example:not-sec-cik",
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "unsupported SEC identifier scheme",
        ):
            transform_filing_document(
                _bronze_response(html),
                expected_cik="0000320193",
            )

    def test_response_hash_must_match_payload(self) -> None:
        response = _bronze_response()
        corrupted = BronzeFilingDocument(
            **{
                **response.__dict__,
                "response_sha256": "0" * 64,
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "does not match the filing payload",
        ):
            transform_filing_document(
                corrupted,
                expected_cik="0000320193",
            )


class FilingSectionExtractionTests(unittest.TestCase):
    def test_rejects_toc_and_extracts_real_bodies(self) -> None:
        business = _long_text("REAL BUSINESS", length=900)
        risk = _long_text("REAL RISK", length=950)

        item_1, item_1a = transform_filing_document(
            _bronze_response(
                _filing_html(
                    item_1=business,
                    item_1a=risk,
                    toc=True,
                )
            ),
            expected_cik="0000320193",
        )

        self.assertTrue(
            item_1.section_text.startswith("REAL BUSINESS")
        )
        self.assertTrue(
            item_1a.section_text.startswith("REAL RISK")
        )

    def test_narrative_cross_references_do_not_become_boundaries(self) -> None:
        business = _long_text("BUSINESS BODY", length=850)
        risk = _long_text("RISK BODY", length=850)

        html = _filing_html(
            item_1=business,
            item_1a=risk,
            pre_body=(
                "Business is discussed in Part I, Item 1 of this Form 10-K. "
                "Risk Factors are discussed in Part I, Item 1A of this Form 10-K."
            ),
        )

        item_1, item_1a = transform_filing_document(
            _bronze_response(html),
            expected_cik="0000320193",
        )

        self.assertTrue(
            item_1.section_text.startswith("BUSINESS BODY")
        )
        self.assertTrue(
            item_1a.section_text.startswith("RISK BODY")
        )

    def test_fragmented_heading_words_are_supported(self) -> None:
        sections = transform_filing_document(
            _bronze_response(
                _filing_html(fragmented=True)
            ),
            expected_cik="0000320193",
        )

        self.assertEqual(
            {section.section_code for section in sections},
            {"item_1", "item_1a"},
        )

    def test_item_1a_end_can_use_item_1b(self) -> None:
        sections = transform_filing_document(
            _bronze_response(
                _filing_html(
                    end_heading="Item 1B. Unresolved Staff Comments",
                )
            ),
            expected_cik="0000320193",
        )

        self.assertNotIn(
            "Unresolved Staff Comments",
            sections[1].section_text,
        )

    def test_item_1a_end_can_fall_back_to_item_1c(self) -> None:
        sections = transform_filing_document(
            _bronze_response(
                _filing_html(
                    end_heading="Item 1C. Cybersecurity",
                )
            ),
            expected_cik="0000320193",
        )

        self.assertNotIn(
            "Cybersecurity",
            sections[1].section_text,
        )

    def test_item_1a_end_can_fall_back_to_item_2(self) -> None:
        sections = transform_filing_document(
            _bronze_response(
                _filing_html(
                    end_heading="Item 2. Properties",
                )
            ),
            expected_cik="0000320193",
        )

        self.assertNotIn(
            "Properties",
            sections[1].section_text,
        )

    def test_terminal_filing_footer_is_removed(self) -> None:
        business = (
            _long_text("BUSINESS BODY", length=850)
            + ". Apple Inc. | 2025 Form 10-K | 4"
        )

        item_1, _ = transform_filing_document(
            _bronze_response(
                _filing_html(
                    item_1=business,
                )
            ),
            expected_cik="0000320193",
        )

        self.assertNotIn(
            "Apple Inc. | 2025 Form 10-K | 4",
            item_1.section_text,
        )
        self.assertTrue(
            item_1.section_text.endswith(".")
        )


    def test_terminal_sec_page_markers_are_removed(self) -> None:
        business = (
            _long_text("BUSINESS BODY", length=850)
            + " 13 PART I Item 1A"
        )
        risk = (
            _long_text("RISK BODY", length=850)
            + " 28 PART I Item 1B, 1C"
        )

        item_1, item_1a = transform_filing_document(
            _bronze_response(
                _filing_html(
                    item_1=business,
                    item_1a=risk,
                )
            ),
            expected_cik="0000320193",
        )

        self.assertFalse(
            item_1.section_text.endswith(
                "13 PART I Item 1A"
            )
        )
        self.assertFalse(
            item_1a.section_text.endswith(
                "28 PART I Item 1B, 1C"
            )
        )
        self.assertTrue(
            item_1.section_text.startswith(
                "BUSINESS BODY"
            )
        )
        self.assertTrue(
            item_1a.section_text.startswith(
                "RISK BODY"
            )
        )

    def test_short_item_1_is_rejected(self) -> None:
        html = _filing_html(item_1="short body")

        with self.assertRaisesRegex(
            ValueError,
            "no substantive Item 1",
        ):
            transform_filing_document(
                _bronze_response(html),
                expected_cik="0000320193",
            )

    def test_short_item_1a_is_rejected(self) -> None:
        html = _filing_html(item_1a="short risk")

        with self.assertRaisesRegex(
            ValueError,
            "Item 1A text is shorter",
        ):
            transform_filing_document(
                _bronze_response(html),
                expected_cik="0000320193",
            )

    def test_section_hash_is_deterministic(self) -> None:
        response = _bronze_response()

        first = transform_filing_document(
            response,
            expected_cik="0000320193",
        )
        second = transform_filing_document(
            response,
            expected_cik="0000320193",
        )

        self.assertEqual(
            first[0].section_text_sha256,
            second[0].section_text_sha256,
        )
        self.assertEqual(
            first[1].section_text_sha256,
            second[1].section_text_sha256,
        )
        self.assertEqual(len(first[0].section_text_sha256), 64)

    def test_script_style_and_ix_hidden_content_are_not_extracted(self) -> None:
        sections = transform_filing_document(
            _bronze_response(),
            expected_cik="0000320193",
        )

        combined = " ".join(
            section.section_text for section in sections
        )

        self.assertNotIn("fake script text", combined)
        self.assertNotIn("hidden xbrl text", combined)


class FilingSnapshotTests(unittest.TestCase):
    def test_snapshot_contains_two_sections_per_company(self) -> None:
        aapl = _bronze_response()

        msft_html = _filing_html(
            identity=_identity_facts(
                cik="0000789019",
                period_end="June 30, 2026",
            ),
            context=_context(
                "c1",
                cik="0000789019",
                period_end="2026-06-30",
            ),
            fragmented=True,
        )

        msft = _bronze_response(
            msft_html,
            response_id="msft",
            project_symbol="MSFT",
            sec_cik="0000789019",
            accession_number="0001193125-26-323660",
            filing_date=date(2026, 7, 29),
            report_date=date(2026, 6, 30),
            primary_document="msft-20260630.htm",
        )

        result = transform_filing_sections_snapshot(
            [aapl, msft],
            {
                "AAPL": "0000320193",
                "MSFT": "0000789019",
            },
        )

        self.assertEqual(result.selected_count, 4)
        self.assertEqual(
            {
                (section.project_symbol, section.section_code)
                for section in result.selected
            },
            {
                ("AAPL", "item_1"),
                ("AAPL", "item_1a"),
                ("MSFT", "item_1"),
                ("MSFT", "item_1a"),
            },
        )

    def test_invalid_latest_retrieval_does_not_fallback(self) -> None:
        older = _bronze_response(
            response_id="older",
            fetched_at=FETCHED_AT - timedelta(minutes=5),
        )
        latest = _bronze_response(
            _filing_html(item_1="too short"),
            response_id="latest",
        )

        with self.assertRaisesRegex(
            ValueError,
            "no substantive Item 1",
        ):
            transform_filing_sections_snapshot(
                [older, latest],
                {"AAPL": "0000320193"},
            )

    def test_missing_configured_company_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "MSFT"):
            transform_filing_sections_snapshot(
                [_bronze_response()],
                {
                    "AAPL": "0000320193",
                    "MSFT": "0000789019",
                },
            )


if __name__ == "__main__":
    unittest.main()
