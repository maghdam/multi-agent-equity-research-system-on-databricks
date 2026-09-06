"""Offline tests for deterministic numerical-fidelity helpers."""

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.numeric_fidelity import (  # noqa: E402
    extract_numeric_claims,
    numeric_claim_matches_expected,
    unsupported_numeric_claims_from_sources,
)


class NumericFidelityTests(unittest.TestCase):
    def test_extracts_unicode_date_percentage_and_scaled_money(self) -> None:
        claims = extract_numeric_claims(
            "On 2026‑09‑04 the return was –2.5% and net income was "
            "$128.9 billion."
        )

        self.assertEqual(
            tuple(claim.kind for claim in claims),
            ("date", "percent", "scaled"),
        )
        self.assertEqual(
            claims[0].value,
            "2026-09-04",
        )
        self.assertEqual(
            claims[1].value,
            Decimal("-2.5"),
        )
        self.assertEqual(
            claims[2].value,
            Decimal("128.9"),
        )
        self.assertEqual(
            claims[2].scale,
            "billion",
        )

    def test_ignores_small_plain_window_integers(self) -> None:
        claims = extract_numeric_claims(
            "The 20-day return and 60-day volatility were discussed."
        )

        self.assertEqual(
            claims,
            (),
        )

    def test_percent_claim_matches_ratio_after_times_100_conversion(self) -> None:
        claim = extract_numeric_claims(
            "The return was 2.2%."
        )[0]

        self.assertTrue(
            numeric_claim_matches_expected(
                claim,
                expected_percent_values=(
                    Decimal("0.0218"),
                ),
            )
        )

    def test_percent_claim_rejects_raw_ratio_with_percent_sign(self) -> None:
        claim = extract_numeric_claims(
            "The return was 0.02%."
        )[0]

        self.assertFalse(
            numeric_claim_matches_expected(
                claim,
                expected_percent_values=(
                    Decimal("0.0212"),
                ),
            )
        )

    def test_scaled_money_claim_matches_faithful_billion_conversion(self) -> None:
        claim = extract_numeric_claims(
            "Net income was $128.9 billion."
        )[0]

        self.assertTrue(
            numeric_claim_matches_expected(
                claim,
                expected_scaled_money_values=(
                    Decimal("128900000000"),
                ),
            )
        )

    def test_scaled_money_claim_rejects_decimal_place_shift(self) -> None:
        claim = extract_numeric_claims(
            "Net income was $12.89 billion."
        )[0]

        self.assertFalse(
            numeric_claim_matches_expected(
                claim,
                expected_scaled_money_values=(
                    Decimal("128900000000"),
                ),
            )
        )

    def test_date_claim_matches_controlled_date(self) -> None:
        claim = extract_numeric_claims(
            "As of 2026-09-04."
        )[0]

        self.assertTrue(
            numeric_claim_matches_expected(
                claim,
                expected_dates=(
                    date(2026, 9, 4),
                ),
            )
        )

    def test_final_source_guard_rejects_changed_numeric_precision(self) -> None:
        unsupported = unsupported_numeric_claims_from_sources(
            candidate_text="Volatility was 31.71%.",
            source_texts=(
                "Volatility was 31.7%.",
            ),
        )

        self.assertEqual(
            tuple(claim.raw for claim in unsupported),
            ("31.71%",),
        )

    def test_final_source_guard_accepts_equivalent_spacing_and_currency(self) -> None:
        unsupported = unsupported_numeric_claims_from_sources(
            candidate_text="Net income was 128.9 billion.",
            source_texts=(
                "Net income was $128.9 billion.",
            ),
        )

        self.assertEqual(
            unsupported,
            (),
        )


if __name__ == "__main__":
    unittest.main()
