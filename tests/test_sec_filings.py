"""Tests for reusable SEC filing metadata logic."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.sec_filings import (
    FilingMetadata,
    build_filing_document_path,
    build_submissions_path,
    parse_recent_10k_filings,
    select_latest_10k,
)


def _payload() -> dict[str, Any]:
    """Return representative SEC recent-filings metadata."""

    return {
        "cik": 320193,
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-25-000079",
                    "0000320193-24-000123",
                    "0000320193-25-000080",
                ],
                "filingDate": [
                    "2025-10-31",
                    "2024-11-01",
                    "2025-11-03",
                ],
                "reportDate": [
                    "2025-09-27",
                    "2024-09-28",
                    "2025-09-27",
                ],
                "form": [
                    "10-K",
                    "10-K",
                    "10-K/A",
                ],
                "primaryDocument": [
                    "aapl-20250927.htm",
                    "aapl-20240928.htm",
                    "aapl-20250927x10ka.htm",
                ],
            }
        },
    }


class SecSubmissionsPathTests(unittest.TestCase):
    def test_builds_submissions_path(self) -> None:
        self.assertEqual(
            build_submissions_path("0000320193"),
            "/submissions/CIK0000320193.json",
        )

    def test_rejects_invalid_cik(self) -> None:
        with self.assertRaises(ValueError):
            build_submissions_path("320193")


class SecRecentFilingsTests(unittest.TestCase):
    def test_parses_parallel_recent_arrays(self) -> None:
        filings = parse_recent_10k_filings(
            _payload(),
            "0000320193",
        )

        # The 10-K/A row is deliberately outside the Bronze MVP.
        self.assertEqual(len(filings), 2)

        self.assertEqual(
            filings[0].filing_date,
            date(2025, 10, 31),
        )

        self.assertEqual(
            filings[0].primary_document,
            "aapl-20250927.htm",
        )

        self.assertTrue(
            all(filing.form == "10-K" for filing in filings)
        )

    def test_accepts_string_response_cik(self) -> None:
        payload = _payload()
        payload["cik"] = "0000320193"

        filings = parse_recent_10k_filings(
            payload,
            "0000320193",
        )

        self.assertEqual(len(filings), 2)

    def test_ignores_incomplete_non_10k_metadata(self) -> None:
        payload = _payload()

        recent = payload["filings"]["recent"]

        # Out-of-scope amendment metadata is allowed to be incomplete
        # because only exact 10-K rows enter the Bronze MVP selection.
        recent["reportDate"][2] = ""
        recent["primaryDocument"][2] = "nested/amendment.htm"

        filings = parse_recent_10k_filings(
            payload,
            "0000320193",
        )

        self.assertEqual(len(filings), 2)

        self.assertTrue(
            all(filing.form == "10-K" for filing in filings)
        )

    def test_rejects_mismatched_response_cik(self) -> None:
        with self.assertRaises(ValueError):
            parse_recent_10k_filings(
                _payload(),
                "0000789019",
            )

    def test_rejects_misaligned_recent_arrays(self) -> None:
        payload = _payload()
        recent = payload["filings"]["recent"]

        recent["form"] = ["10-K"]

        with self.assertRaises(ValueError):
            parse_recent_10k_filings(
                payload,
                "0000320193",
            )


class SecFilingSelectionTests(unittest.TestCase):
    def test_selects_latest_exact_10k(self) -> None:
        filings = parse_recent_10k_filings(
            _payload(),
            "0000320193",
        )

        selected = select_latest_10k(filings)

        self.assertEqual(
            selected.accession_number,
            "0000320193-25-000079",
        )

        self.assertEqual(
            selected.filing_date,
            date(2025, 10, 31),
        )

        self.assertEqual(
            selected.report_date,
            date(2025, 9, 27),
        )

        self.assertEqual(
            selected.form,
            "10-K",
        )

    def test_rejects_ambiguous_latest_10k(self) -> None:
        filing = FilingMetadata(
            accession_number="0000320193-25-000079",
            filing_date=date(2025, 10, 31),
            report_date=date(2025, 9, 27),
            form="10-K",
            primary_document="aapl-20250927.htm",
        )

        second = FilingMetadata(
            accession_number="0000320193-25-000081",
            filing_date=date(2025, 10, 31),
            report_date=date(2025, 9, 27),
            form="10-K",
            primary_document="aapl-other.htm",
        )

        with self.assertRaises(ValueError):
            select_latest_10k(
                (filing, second)
            )


class SecFilingDocumentPathTests(unittest.TestCase):
    def test_builds_archive_document_path(self) -> None:
        filing = FilingMetadata(
            accession_number="0000320193-25-000079",
            filing_date=date(2025, 10, 31),
            report_date=date(2025, 9, 27),
            form="10-K",
            primary_document="aapl-20250927.htm",
        )

        self.assertEqual(
            build_filing_document_path(
                "0000320193",
                filing,
            ),
            (
                "/Archives/edgar/data/"
                "320193/"
                "000032019325000079/"
                "aapl-20250927.htm"
            ),
        )


if __name__ == "__main__":
    unittest.main()