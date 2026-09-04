"""Offline tests for Silver SEC company-facts transformation logic."""

import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.silver_company_facts import (  # noqa: E402
    BronzeCompanyFactsResponse,
    select_latest_company_responses,
    transform_company_facts_response,
    transform_company_facts_snapshot,
)


FETCHED_AT = datetime(2026, 9, 2, 18, 3, tzinfo=timezone.utc)


def _duration_observation(**overrides: object) -> dict[str, object]:
    observation: dict[str, object] = {
        "start": "2025-09-28",
        "end": "2026-06-27",
        "val": 364357000000,
        "accn": "0000320193-26-000020",
        "fy": 2026,
        "fp": "Q3",
        "form": "10-Q",
        "filed": "2026-07-31",
        "frame": None,
    }
    observation.update(overrides)
    return observation


def _instant_observation(**overrides: object) -> dict[str, object]:
    observation: dict[str, object] = {
        "end": "2026-06-27",
        "val": 383266000000,
        "accn": "0000320193-26-000020",
        "fy": 2026,
        "fp": "Q3",
        "form": "10-Q",
        "filed": "2026-07-31",
        "frame": "CY2026Q2I",
    }
    observation.update(overrides)
    return observation


def _payload(
    *,
    cik: int = 320193,
    entity_name: str = "Apple Inc.",
    revenue: list[object] | None = None,
    net_income: list[object] | None = None,
    assets: list[object] | None = None,
) -> dict[str, object]:
    us_gaap: dict[str, object] = {}

    if revenue is not None:
        us_gaap[
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        ] = {
            "label": "Revenue",
            "units": {"USD": revenue},
        }

    if net_income is not None:
        us_gaap["NetIncomeLoss"] = {
            "label": "Net Income (Loss)",
            "units": {"USD": net_income},
        }

    if assets is not None:
        us_gaap["Assets"] = {
            "label": "Assets",
            "units": {"USD": assets},
        }

    return {
        "cik": cik,
        "entityName": entity_name,
        "facts": {"us-gaap": us_gaap},
    }


def _bronze_response(
    payload: dict[str, object],
    *,
    response_id: str = "response-a",
    fetched_at: datetime = FETCHED_AT,
    project_symbol: str = "AAPL",
    sec_cik: str = "0000320193",
    entity_name: str = "Apple Inc.",
    source_system: str = "sec",
    source_endpoint: str = "companyfacts",
) -> BronzeCompanyFactsResponse:
    raw_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    response_sha256 = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    return BronzeCompanyFactsResponse(
        source_system=source_system,
        source_endpoint=source_endpoint,
        project_symbol=project_symbol,
        sec_cik=sec_cik,
        entity_name=entity_name,
        source_response_id=response_id,
        response_payload_json=raw_json,
        response_sha256=response_sha256,
        fetched_at=fetched_at,
        ingestion_run_id="run-1",
    )


class CompanyFactsResponseTransformTests(unittest.TestCase):
    """Verify extraction and validation from one selected SEC response."""

    def test_accepts_duration_and_instant_facts(self) -> None:
        response = _bronze_response(
            _payload(
                revenue=[_duration_observation()],
                assets=[_instant_observation()],
            )
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        self.assertEqual(result.accepted_count, 2)
        self.assertEqual(result.rejected_count, 0)
        self.assertEqual(result.unavailable_scope_count, 1)

        revenue = next(
            fact
            for fact in result.accepted
            if fact.concept
            == "RevenueFromContractWithCustomerExcludingAssessedTax"
        )
        assets = next(
            fact for fact in result.accepted if fact.concept == "Assets"
        )

        self.assertEqual(
            revenue.fact_value,
            Decimal("364357000000.00000000"),
        )
        self.assertEqual(revenue.period_start.isoformat(), "2025-09-28")
        self.assertIsNone(assets.period_start)
        self.assertEqual(assets.period_end.isoformat(), "2026-06-27")

    def test_preserves_negative_net_income(self) -> None:
        response = _bronze_response(
            _payload(
                net_income=[
                    _duration_observation(
                        val=-1250000000,
                    )
                ]
            )
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(
            result.accepted[0].fact_value,
            Decimal("-1250000000.00000000"),
        )

    def test_preserves_selected_bronze_provenance(self) -> None:
        response = _bronze_response(
            _payload(assets=[_instant_observation()]),
            response_id="selected-response",
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        fact = result.accepted[0]
        self.assertEqual(fact.project_symbol, "AAPL")
        self.assertEqual(fact.cik, "0000320193")
        self.assertEqual(fact.source_response_id, "selected-response")
        self.assertEqual(fact.ingestion_run_id, "run-1")
        self.assertEqual(fact.fetched_at, FETCHED_AT)

    def test_missing_scoped_concepts_are_unavailable(self) -> None:
        response = _bronze_response(_payload())

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.rejected_count, 0)
        self.assertEqual(result.unavailable_scope_count, 3)

    def test_rejects_invalid_accession(self) -> None:
        response = _bronze_response(
            _payload(
                revenue=[
                    _duration_observation(accn="bad-accession")
                ]
            )
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.rejected_count, 1)
        codes = {issue.code for issue in result.rejected[0].issues}
        self.assertIn("invalid_accession_number", codes)

    def test_rejects_non_ascii_accession_digits(self) -> None:
        response = _bronze_response(
            _payload(
                revenue=[
                    _duration_observation(
                        accn="٠٠٠٠٣٢٠١٩٣-٢٦-٠٠٠٠٢٠",
                    )
                ]
            )
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.rejected_count, 1)
        codes = {issue.code for issue in result.rejected[0].issues}
        self.assertIn("invalid_accession_number", codes)

    def test_rejects_duration_without_start(self) -> None:
        observation = _duration_observation()
        observation.pop("start")
        response = _bronze_response(
            _payload(revenue=[observation])
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        self.assertEqual(result.rejected_count, 1)
        fields = {issue.field for issue in result.rejected[0].issues}
        self.assertIn("start", fields)

    def test_rejects_duration_start_after_end(self) -> None:
        response = _bronze_response(
            _payload(
                revenue=[
                    _duration_observation(
                        start="2026-07-01",
                        end="2026-06-30",
                    )
                ]
            )
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        codes = {issue.code for issue in result.rejected[0].issues}
        self.assertIn("period_start_after_end", codes)

    def test_rejects_unexpected_start_on_instant_fact(self) -> None:
        response = _bronze_response(
            _payload(
                assets=[
                    _instant_observation(start="2026-01-01")
                ]
            )
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        codes = {issue.code for issue in result.rejected[0].issues}
        self.assertIn("unexpected_start_for_instant_fact", codes)

    def test_rejects_boolean_fiscal_year(self) -> None:
        response = _bronze_response(
            _payload(
                assets=[_instant_observation(fy=True)]
            )
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        codes = {issue.code for issue in result.rejected[0].issues}
        self.assertIn("invalid_optional_integer", codes)

    def test_rejects_fact_value_beyond_decimal_scale(self) -> None:
        payload = _payload(
            assets=[_instant_observation(val=1.123456789)]
        )
        raw_json = json.dumps(payload, separators=(",", ":"))
        response = BronzeCompanyFactsResponse(
            source_system="sec",
            source_endpoint="companyfacts",
            project_symbol="AAPL",
            sec_cik="0000320193",
            entity_name="Apple Inc.",
            source_response_id="response-a",
            response_payload_json=raw_json,
            response_sha256="hash",
            fetched_at=FETCHED_AT,
            ingestion_run_id="run-1",
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        codes = {issue.code for issue in result.rejected[0].issues}
        self.assertIn("fact_value_exceeds_scale", codes)

    def test_rejects_fact_value_outside_decimal_28_8(self) -> None:
        response = _bronze_response(
            _payload(
                assets=[
                    _instant_observation(
                        val=100000000000000000000,
                    )
                ]
            )
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        codes = {issue.code for issue in result.rejected[0].issues}
        self.assertIn("fact_value_out_of_range", codes)

    def test_collapses_identical_business_key_duplicates(self) -> None:
        observation = _instant_observation()
        response = _bronze_response(
            _payload(assets=[observation, dict(observation)])
        )

        result = transform_company_facts_response(
            response,
            expected_cik="0000320193",
        )

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.duplicate_count, 1)

    def test_conflicting_business_key_duplicates_fail(self) -> None:
        first = _instant_observation(val=100)
        second = _instant_observation(val=200)
        response = _bronze_response(
            _payload(assets=[first, second])
        )

        with self.assertRaisesRegex(
            ValueError,
            "conflicting SEC company facts",
        ):
            transform_company_facts_response(
                response,
                expected_cik="0000320193",
            )

    def test_payload_cik_must_match_configured_cik(self) -> None:
        response = _bronze_response(
            _payload(cik=789019, entity_name="Apple Inc."),
        )

        with self.assertRaisesRegex(ValueError, "payload CIK"):
            transform_company_facts_response(
                response,
                expected_cik="0000320193",
            )

    def test_payload_entity_name_must_match_bronze_metadata(self) -> None:
        response = _bronze_response(
            _payload(entity_name="Different Name"),
        )

        with self.assertRaisesRegex(ValueError, "entity_name"):
            transform_company_facts_response(
                response,
                expected_cik="0000320193",
            )


class CompanyResponseSelectionTests(unittest.TestCase):
    """Verify deterministic latest-response selection before fact validation."""

    def test_selects_greatest_fetched_at(self) -> None:
        payload = _payload(assets=[_instant_observation()])
        older = _bronze_response(
            payload,
            response_id="older",
            fetched_at=FETCHED_AT - timedelta(minutes=5),
        )
        newer = _bronze_response(
            payload,
            response_id="newer",
        )

        result = select_latest_company_responses(
            [older, newer],
            {"AAPL": "0000320193"},
        )

        self.assertEqual(result.selected[0].source_response_id, "newer")
        self.assertEqual(result.superseded_response_count, 1)

    def test_tied_identical_payload_uses_smallest_response_id(self) -> None:
        payload = _payload(assets=[_instant_observation()])
        response_b = _bronze_response(payload, response_id="b")
        response_a = _bronze_response(payload, response_id="a")

        result = select_latest_company_responses(
            [response_b, response_a],
            {"AAPL": "0000320193"},
        )

        self.assertEqual(result.selected[0].source_response_id, "a")
        self.assertEqual(result.tie_repeat_count, 1)

    def test_tied_different_payloads_fail(self) -> None:
        response_a = _bronze_response(
            _payload(assets=[_instant_observation(val=100)]),
            response_id="a",
        )
        response_b = _bronze_response(
            _payload(assets=[_instant_observation(val=200)]),
            response_id="b",
        )

        with self.assertRaisesRegex(ValueError, "different raw payloads"):
            select_latest_company_responses(
                [response_a, response_b],
                {"AAPL": "0000320193"},
            )

    def test_missing_configured_company_fails(self) -> None:
        response = _bronze_response(_payload())

        with self.assertRaisesRegex(ValueError, "MSFT"):
            select_latest_company_responses(
                [response],
                {
                    "AAPL": "0000320193",
                    "MSFT": "0000789019",
                },
            )

    def test_mismatched_bronze_cik_fails(self) -> None:
        response = _bronze_response(
            _payload(),
            sec_cik="0000789019",
        )

        with self.assertRaisesRegex(ValueError, "does not match configured"):
            select_latest_company_responses(
                [response],
                {"AAPL": "0000320193"},
            )

    def test_rejects_non_ascii_cik_digits(self) -> None:
        response = _bronze_response(
            _payload(),
            sec_cik="٠٠٠٠٣٢٠١٩٣",
        )

        with self.assertRaisesRegex(ValueError, "exactly 10 digits"):
            select_latest_company_responses(
                [response],
                {"AAPL": "0000320193"},
            )

    def test_out_of_scope_bronze_response_is_ignored(self) -> None:
        aapl = _bronze_response(_payload())
        googl = _bronze_response(
            _payload(cik=1652044, entity_name="Alphabet Inc."),
            project_symbol="GOOGL",
            sec_cik="0001652044",
            entity_name="Alphabet Inc.",
            response_id="googl",
        )

        result = select_latest_company_responses(
            [aapl, googl],
            {"AAPL": "0000320193"},
        )

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.out_of_scope_response_count, 1)

    def test_naive_fetched_at_fails(self) -> None:
        response = _bronze_response(
            _payload(),
            fetched_at=datetime(2026, 9, 2, 18, 3),
        )

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            select_latest_company_responses(
                [response],
                {"AAPL": "0000320193"},
            )


class CompanyFactsSnapshotTests(unittest.TestCase):
    """Verify latest-response selection and snapshot orchestration together."""

    def test_invalid_latest_fact_does_not_fallback_to_older_response(self) -> None:
        older = _bronze_response(
            _payload(assets=[_instant_observation(val=100)]),
            response_id="older",
            fetched_at=FETCHED_AT - timedelta(minutes=5),
        )
        newer = _bronze_response(
            _payload(
                assets=[
                    _instant_observation(
                        val=200,
                        accn="invalid",
                    )
                ]
            ),
            response_id="newer",
        )

        result = transform_company_facts_snapshot(
            [older, newer],
            {"AAPL": "0000320193"},
        )

        self.assertEqual(result.selected_count, 0)
        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(
            result.selected_responses[0].source_response_id,
            "newer",
        )
        self.assertEqual(result.superseded_response_count, 1)

    def test_snapshot_combines_configured_companies(self) -> None:
        aapl = _bronze_response(
            _payload(assets=[_instant_observation()]),
        )
        msft_payload = _payload(
            cik=789019,
            entity_name="MICROSOFT CORPORATION",
            assets=[
                _instant_observation(
                    end="2026-06-30",
                    val=758376000000,
                    accn="0001193125-26-323660",
                    fy=2026,
                    fp="FY",
                    form="10-K",
                    filed="2026-07-29",
                    frame="CY2026Q2I",
                )
            ],
        )
        msft = _bronze_response(
            msft_payload,
            project_symbol="MSFT",
            sec_cik="0000789019",
            entity_name="MICROSOFT CORPORATION",
            response_id="msft",
        )

        result = transform_company_facts_snapshot(
            [aapl, msft],
            {
                "AAPL": "0000320193",
                "MSFT": "0000789019",
            },
        )

        self.assertEqual(result.selected_count, 2)
        self.assertEqual(
            {fact.project_symbol for fact in result.selected},
            {"AAPL", "MSFT"},
        )


if __name__ == "__main__":
    unittest.main()
