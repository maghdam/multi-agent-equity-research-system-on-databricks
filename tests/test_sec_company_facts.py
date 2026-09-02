"""Offline tests for reusable SEC company-facts logic."""

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.sec_company_facts import (  # noqa: E402
    CompanyFactsResponse,
    build_company_facts_path,
    parse_company_facts_response,
)


class SecCompanyFactsRequestTests(unittest.TestCase):
    """Verify SEC company-facts request construction."""

    def test_builds_company_facts_path(self) -> None:
        """Build the exact SEC endpoint path for a normalized CIK."""

        path = build_company_facts_path("0000320193")

        self.assertEqual(
            path,
            "/api/xbrl/companyfacts/CIK0000320193.json",
        )

    def test_rejects_invalid_ciks(self) -> None:
        """Require the project's ten-digit SEC CIK contract."""

        invalid_ciks = (
            "",
            "320193",
            "000032019",
            "00003201933",
            "000032019X",
        )

        for cik in invalid_ciks:
            with self.subTest(cik=cik):
                with self.assertRaisesRegex(
                    ValueError,
                    "exactly 10 digits",
                ):
                    build_company_facts_path(cik)


class SecCompanyFactsResponseTests(unittest.TestCase):
    """Verify validation of SEC company-facts response envelopes."""

    def test_parses_valid_company_facts_response(self) -> None:
        """Preserve SEC entity metadata and facts payload."""

        payload = {
            "cik": 320193,
            "entityName": "Apple Inc.",
            "facts": {
                "dei": {
                    "EntityCommonStockSharesOutstanding": {}
                },
                "us-gaap": {
                    "Assets": {}
                },
            },
        }

        result = parse_company_facts_response(payload)

        self.assertEqual(
            result,
            CompanyFactsResponse(
                cik=320193,
                entity_name="Apple Inc.",
                facts=payload["facts"],
            ),
        )

    def test_normalizes_entity_name(self) -> None:
        """Trim surrounding whitespace from SEC entity metadata."""

        result = parse_company_facts_response(
            {
                "cik": 320193,
                "entityName": " Apple Inc. ",
                "facts": {},
            }
        )

        self.assertEqual(result.entity_name, "Apple Inc.")

    def test_accepts_empty_facts_object(self) -> None:
        """Allow structurally valid responses without extracted concepts."""

        result = parse_company_facts_response(
            {
                "cik": 320193,
                "entityName": "Apple Inc.",
                "facts": {},
            }
        )

        self.assertEqual(result.facts, {})

    def test_rejects_invalid_response_structure(self) -> None:
        """Reject malformed SEC response envelopes."""

        invalid_payloads = (
            None,
            [],
            {},
            {
                "cik": 0,
                "entityName": "Apple Inc.",
                "facts": {},
            },
            {
                "cik": True,
                "entityName": "Apple Inc.",
                "facts": {},
            },
            {
                "cik": 320193,
                "entityName": "",
                "facts": {},
            },
            {
                "cik": 320193,
                "entityName": "Apple Inc.",
                "facts": [],
            },
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_company_facts_response(payload)


if __name__ == "__main__":
    unittest.main()