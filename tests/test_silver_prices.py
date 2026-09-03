"""Offline tests for Silver daily-price transformation logic."""

"""Offline tests for Silver daily-price transformation logic."""

"""Offline tests for Silver daily-price transformation logic."""

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.silver_prices import (  # noqa: E402
    BronzePriceResponse,
    select_current_price_snapshot,
    transform_price_response,
    transform_price_snapshot,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))



REQUEST_PARAMETERS = json.dumps(
    {
        "symbols": "AAPL,MSFT",
        "timeframe": "1Day",
        "start": "2026-08-27T00:00:00-04:00",
        "end": "2026-08-27T23:59:59-04:00",
        "feed": "sip",
        "adjustment": "split",
        "currency": "USD",
        "limit": 10000,
        "sort": "asc",
    }
)

FETCHED_AT = datetime(
    2026,
    8,
    28,
    12,
    0,
    tzinfo=timezone.utc,
)


def _response_with_bar(bar_json: str) -> str:
    return (
        '{"bars":{"AAPL":['
        + bar_json
        + ']},"next_page_token":null}'
    )


def _transform(
    response_payload_json: str,
    *,
    request_parameters_json: str = REQUEST_PARAMETERS,
    configured_symbols: tuple[str, ...] = ("AAPL", "MSFT"),
    fetched_at: datetime = FETCHED_AT,
):
    return transform_price_response(
        response_payload_json=response_payload_json,
        request_parameters_json=request_parameters_json,
        source_system="alpaca",
        source_response_id="response-1",
        fetched_at=fetched_at,
        ingestion_run_id="run-1",
        configured_symbols=configured_symbols,
    )

def _bronze_response(
    response_payload_json: str,
    *,
    source_response_id: str,
    fetched_at: datetime,
    ingestion_run_id: str,
    request_parameters_json: str = REQUEST_PARAMETERS,
) -> BronzePriceResponse:
    return BronzePriceResponse(
        source_system="alpaca",
        source_response_id=source_response_id,
        request_parameters_json=request_parameters_json,
        response_payload_json=response_payload_json,
        fetched_at=fetched_at,
        ingestion_run_id=ingestion_run_id,
    )

class SilverPriceTransformationTests(unittest.TestCase):
    """Verify exact typing and contract validation for one Bronze page."""

    def test_newer_changed_observation_wins(self) -> None:
        old_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        new_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":236,
              "l":229,
              "c":235,
              "v":1100
            }
            """
        )

        old_result = _transform(
            old_response,
            fetched_at=datetime(
                2026,
                8,
                28,
                10,
                0,
                tzinfo=timezone.utc,
            ),
        )

        new_result = transform_price_response(
            response_payload_json=new_response,
            request_parameters_json=REQUEST_PARAMETERS,
            source_system="alpaca",
            source_response_id="response-2",
            fetched_at=datetime(
                2026,
                8,
                28,
                12,
                0,
                tzinfo=timezone.utc,
            ),
            ingestion_run_id="run-2",
            configured_symbols=("AAPL", "MSFT"),
        )

        selection = select_current_price_snapshot(
            (
                new_result.accepted[0],
                old_result.accepted[0],
            )
        )

        self.assertEqual(selection.selected_count, 1)
        self.assertEqual(
            selection.selected[0].source_response_id,
            "response-2",
        )
        self.assertEqual(selection.duplicate_count, 0)
        self.assertEqual(selection.superseded_count, 1)

    def test_older_replay_cannot_replace_newer_observation(
        self,
    ) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        newer = transform_price_response(
            response_payload_json=response,
            request_parameters_json=REQUEST_PARAMETERS,
            source_system="alpaca",
            source_response_id="response-new",
            fetched_at=datetime(
                2026,
                8,
                29,
                12,
                0,
                tzinfo=timezone.utc,
            ),
            ingestion_run_id="run-new",
            configured_symbols=("AAPL", "MSFT"),
        ).accepted[0]

        older = transform_price_response(
            response_payload_json=response,
            request_parameters_json=REQUEST_PARAMETERS,
            source_system="alpaca",
            source_response_id="response-old",
            fetched_at=datetime(
                2026,
                8,
                28,
                12,
                0,
                tzinfo=timezone.utc,
            ),
            ingestion_run_id="run-old",
            configured_symbols=("AAPL", "MSFT"),
        ).accepted[0]

        selection = select_current_price_snapshot(
            (newer, older)
        )

        self.assertEqual(
            selection.selected[0].source_response_id,
            "response-new",
        )
        self.assertEqual(selection.duplicate_count, 1)
        self.assertEqual(selection.superseded_count, 0)

    def test_identical_same_time_repeat_uses_smallest_response_id(
        self,
    ) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        candidate_b = transform_price_response(
            response_payload_json=response,
            request_parameters_json=REQUEST_PARAMETERS,
            source_system="alpaca",
            source_response_id="response-b",
            fetched_at=FETCHED_AT,
            ingestion_run_id="run-b",
            configured_symbols=("AAPL", "MSFT"),
        ).accepted[0]

        candidate_a = transform_price_response(
            response_payload_json=response,
            request_parameters_json=REQUEST_PARAMETERS,
            source_system="alpaca",
            source_response_id="response-a",
            fetched_at=FETCHED_AT,
            ingestion_run_id="run-a",
            configured_symbols=("AAPL", "MSFT"),
        ).accepted[0]

        selection = select_current_price_snapshot(
            (candidate_b, candidate_a)
        )

        self.assertEqual(selection.selected_count, 1)
        self.assertEqual(
            selection.selected[0].source_response_id,
            "response-a",
        )
        self.assertEqual(selection.duplicate_count, 1)

    def test_same_time_different_values_fail_selection(
        self,
    ) -> None:
        first_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        conflicting_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":236,
              "l":229,
              "c":235,
              "v":1000
            }
            """
        )

        first = transform_price_response(
            response_payload_json=first_response,
            request_parameters_json=REQUEST_PARAMETERS,
            source_system="alpaca",
            source_response_id="response-a",
            fetched_at=FETCHED_AT,
            ingestion_run_id="run-a",
            configured_symbols=("AAPL", "MSFT"),
        ).accepted[0]

        conflicting = transform_price_response(
            response_payload_json=conflicting_response,
            request_parameters_json=REQUEST_PARAMETERS,
            source_system="alpaca",
            source_response_id="response-b",
            fetched_at=FETCHED_AT,
            ingestion_run_id="run-b",
            configured_symbols=("AAPL", "MSFT"),
        ).accepted[0]

        with self.assertRaises(ValueError):
            select_current_price_snapshot(
                (first, conflicting)
            )

    def test_same_time_historical_conflict_is_not_hidden_by_newer_bar(
        self,
    ) -> None:
        first_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        conflict_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":236,
              "l":229,
              "c":235,
              "v":1000
            }
            """
        )

        newer_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":231,
              "h":237,
              "l":230,
              "c":236,
              "v":1200
            }
            """
        )

        first = transform_price_response(
            response_payload_json=first_response,
            request_parameters_json=REQUEST_PARAMETERS,
            source_system="alpaca",
            source_response_id="response-a",
            fetched_at=datetime(
                2026,
                8,
                28,
                10,
                0,
                tzinfo=timezone.utc,
            ),
            ingestion_run_id="run-a",
            configured_symbols=("AAPL", "MSFT"),
        ).accepted[0]

        conflict = transform_price_response(
            response_payload_json=conflict_response,
            request_parameters_json=REQUEST_PARAMETERS,
            source_system="alpaca",
            source_response_id="response-b",
            fetched_at=datetime(
                2026,
                8,
                28,
                10,
                0,
                tzinfo=timezone.utc,
            ),
            ingestion_run_id="run-b",
            configured_symbols=("AAPL", "MSFT"),
        ).accepted[0]

        newer = transform_price_response(
            response_payload_json=newer_response,
            request_parameters_json=REQUEST_PARAMETERS,
            source_system="alpaca",
            source_response_id="response-c",
            fetched_at=datetime(
                2026,
                8,
                29,
                12,
                0,
                tzinfo=timezone.utc,
            ),
            ingestion_run_id="run-c",
            configured_symbols=("AAPL", "MSFT"),
        ).accepted[0]

        with self.assertRaises(ValueError):
            select_current_price_snapshot(
                (first, conflict, newer)
            )

    def test_accepts_valid_completed_daily_bar(self) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230.10000000,
              "h":235.20000000,
              "l":229.50000000,
              "c":234.75000000,
              "v":1234567.00000000
            }
            """
        )

        result = _transform(response)

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.rejected_count, 0)
        self.assertEqual(result.out_of_scope_count, 0)

        candidate = result.accepted[0]

        self.assertEqual(candidate.symbol, "AAPL")
        self.assertEqual(
            candidate.trading_date.isoformat(),
            "2026-08-27",
        )
        self.assertEqual(candidate.feed, "sip")
        self.assertEqual(candidate.adjustment, "split")
        self.assertEqual(candidate.timeframe, "1Day")
        self.assertEqual(candidate.currency, "USD")
        self.assertEqual(
            candidate.source_response_id,
            "response-1",
        )

    def test_allows_numerically_equivalent_trailing_zeros(self) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230.123456780,
              "h":235.200000000,
              "l":229.500000000,
              "c":234.750000000,
              "v":1234567.000000000
            }
            """
        )

        result = _transform(response)

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.rejected_count, 0)

    def test_rejects_close_above_high(self) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":240,
              "v":1000
            }
            """
        )

        result = _transform(response)

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.rejected_count, 1)

        issues = {
            (issue.code, issue.field)
            for issue in result.rejected[0].issues
        }

        self.assertIn(
            ("outside_low_high", "close"),
            issues,
        )

    def test_rejects_zero_volume(self) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":0
            }
            """
        )

        result = _transform(response)

        issues = {
            (issue.code, issue.field)
            for issue in result.rejected[0].issues
        }

        self.assertIn(
            ("not_positive", "volume"),
            issues,
        )

    def test_rejects_numeric_string(self) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":"230.1",
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        result = _transform(response)

        issues = {
            (issue.code, issue.field)
            for issue in result.rejected[0].issues
        }

        self.assertIn(
            ("numeric_type", "open"),
            issues,
        )

    def test_rejects_fractional_precision_above_eight_digits(
        self,
    ) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230.123456789,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        result = _transform(response)

        issues = {
            (issue.code, issue.field)
            for issue in result.rejected[0].issues
        }

        self.assertIn(
            ("decimal_20_8", "open"),
            issues,
        )

    def test_rejects_more_than_twelve_integer_digits(self) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":1234567890123,
              "h":1234567890124,
              "l":1234567890122,
              "c":1234567890123,
              "v":1000
            }
            """
        )

        result = _transform(response)

        issues = {
            (issue.code, issue.field)
            for issue in result.rejected[0].issues
        }

        self.assertIn(
            ("decimal_20_8", "open"),
            issues,
        )

    def test_rejects_same_day_partial_bar(self) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        same_new_york_day = datetime(
            2026,
            8,
            27,
            20,
            0,
            tzinfo=timezone.utc,
        )

        result = _transform(
            response,
            fetched_at=same_new_york_day,
        )

        issues = {
            issue.code
            for issue in result.rejected[0].issues
        }

        self.assertIn(
            "incomplete_trading_day",
            issues,
        )

    def test_classifies_removed_config_symbol_as_out_of_scope(
        self,
    ) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        result = _transform(
            response,
            configured_symbols=("MSFT",),
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.rejected_count, 0)
        self.assertEqual(result.out_of_scope_count, 1)

    def test_classifies_wrong_request_settings_as_out_of_scope(
        self,
    ) -> None:
        parameters = json.loads(REQUEST_PARAMETERS)
        parameters["feed"] = "iex"

        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        result = _transform(
            response,
            request_parameters_json=json.dumps(parameters),
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.rejected_count, 0)
        self.assertEqual(result.out_of_scope_count, 1)

    def test_fails_response_symbol_absent_from_original_request(
        self,
    ) -> None:
        response = """
        {
          "bars":{
            "GOOG":[
              {
                "t":"2026-08-27T04:00:00Z",
                "o":100,
                "h":105,
                "l":99,
                "c":104,
                "v":1000
              }
            ]
          },
          "next_page_token":null
        }
        """

        with self.assertRaises(ValueError):
            _transform(response)

    def test_requires_timezone_aware_fetched_at(self) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        with self.assertRaises(ValueError):
            _transform(
                response,
                fetched_at=datetime(
                    2026,
                    8,
                    28,
                    12,
                    0,
                ),
            )

    def test_rebuilds_snapshot_from_multiple_bronze_responses(
        self,
    ) -> None:
        old_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        new_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":231,
              "h":236,
              "l":230,
              "c":235,
              "v":1200
            }
            """
        )

        result = transform_price_snapshot(
            bronze_responses=(
                _bronze_response(
                    old_response,
                    source_response_id="response-old",
                    fetched_at=datetime(
                        2026,
                        8,
                        28,
                        10,
                        0,
                        tzinfo=timezone.utc,
                    ),
                    ingestion_run_id="run-old",
                ),
                _bronze_response(
                    new_response,
                    source_response_id="response-new",
                    fetched_at=datetime(
                        2026,
                        8,
                        29,
                        10,
                        0,
                        tzinfo=timezone.utc,
                    ),
                    ingestion_run_id="run-new",
                ),
            ),
            configured_symbols=("AAPL", "MSFT"),
        )

        self.assertEqual(result.bronze_response_count, 2)
        self.assertEqual(result.accepted_candidate_count, 2)
        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.rejected_count, 0)
        self.assertEqual(result.out_of_scope_count, 0)
        self.assertEqual(result.duplicate_count, 0)
        self.assertEqual(result.superseded_count, 1)
        self.assertEqual(
            result.selected[0].source_response_id,
            "response-new",
        )

    def test_snapshot_aggregates_rejected_bars(self) -> None:
        valid_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        invalid_response = _response_with_bar(
            """
            {
              "t":"2026-08-28T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":240,
              "v":1000
            }
            """
        )

        result = transform_price_snapshot(
            bronze_responses=(
                _bronze_response(
                    valid_response,
                    source_response_id="response-valid",
                    fetched_at=datetime(
                        2026,
                        8,
                        29,
                        12,
                        0,
                        tzinfo=timezone.utc,
                    ),
                    ingestion_run_id="run-valid",
                ),
                _bronze_response(
                    invalid_response,
                    source_response_id="response-invalid",
                    fetched_at=datetime(
                        2026,
                        8,
                        29,
                        12,
                        0,
                        tzinfo=timezone.utc,
                    ),
                    ingestion_run_id="run-invalid",
                ),
            ),
            configured_symbols=("AAPL", "MSFT"),
        )

        self.assertEqual(result.accepted_candidate_count, 1)
        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.rejected_count, 1)

    def test_snapshot_aggregates_out_of_scope_bars(
        self,
    ) -> None:
        response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        result = transform_price_snapshot(
            bronze_responses=(
                _bronze_response(
                    response,
                    source_response_id="response-1",
                    fetched_at=FETCHED_AT,
                    ingestion_run_id="run-1",
                ),
            ),
            configured_symbols=("MSFT",),
        )

        self.assertEqual(result.selected_count, 0)
        self.assertEqual(result.rejected_count, 0)
        self.assertEqual(result.out_of_scope_count, 1)

    def test_snapshot_fails_if_any_bronze_response_is_malformed(
        self,
    ) -> None:
        valid_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        malformed_response = '{"not_bars":[]}'

        with self.assertRaises(ValueError):
            transform_price_snapshot(
                bronze_responses=(
                    _bronze_response(
                        valid_response,
                        source_response_id="response-valid",
                        fetched_at=FETCHED_AT,
                        ingestion_run_id="run-valid",
                    ),
                    _bronze_response(
                        malformed_response,
                        source_response_id="response-bad",
                        fetched_at=FETCHED_AT,
                        ingestion_run_id="run-bad",
                    ),
                ),
                configured_symbols=("AAPL", "MSFT"),
            )

    def test_snapshot_fails_on_cross_response_conflict(
        self,
    ) -> None:
        first_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":235,
              "l":229,
              "c":234,
              "v":1000
            }
            """
        )

        conflicting_response = _response_with_bar(
            """
            {
              "t":"2026-08-27T04:00:00Z",
              "o":230,
              "h":236,
              "l":229,
              "c":235,
              "v":1000
            }
            """
        )

        with self.assertRaises(ValueError):
            transform_price_snapshot(
                bronze_responses=(
                    _bronze_response(
                        first_response,
                        source_response_id="response-a",
                        fetched_at=FETCHED_AT,
                        ingestion_run_id="run-a",
                    ),
                    _bronze_response(
                        conflicting_response,
                        source_response_id="response-b",
                        fetched_at=FETCHED_AT,
                        ingestion_run_id="run-b",
                    ),
                ),
                configured_symbols=("AAPL", "MSFT"),
            )

if __name__ == "__main__":
    unittest.main()