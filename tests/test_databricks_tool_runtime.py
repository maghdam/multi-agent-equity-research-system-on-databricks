"""Offline tests for controlled Databricks execution and result parsing."""

import json
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.databricks_cli_runtime import (  # noqa: E402
    ControlledToolExecutionError,
    execute_statement_via_cli,
    query_chat_completions_via_cli,
    query_vector_index_via_cli,
)
from equity_research.structured_data_access import (  # noqa: E402
    FUNDAMENTAL_COLUMNS,
    MARKET_COLUMNS,
    parse_fundamental_metrics_statement_response,
    parse_market_metrics_statement_response,
)
from equity_research.structured_data_tools import (  # noqa: E402
    ControlledToolDataError,
)


def _statement_response(
    columns: tuple[str, ...],
    row: list[object],
) -> dict:
    return {
        "statement_id": "statement-1",
        "status": {
            "state": "SUCCEEDED",
        },
        "manifest": {
            "format": "JSON_ARRAY",
            "schema": {
                "column_count": len(columns),
                "columns": [
                    {
                        "name": name,
                        "position": index,
                    }
                    for index, name in enumerate(columns)
                ],
            },
            "total_chunk_count": 1,
        },
        "result": {
            "chunk_index": 0,
            "data_array": [row],
            "row_count": 1,
            "row_offset": 0,
        },
    }


def _market_row() -> list[object]:
    return [
        "alpaca",
        "AAPL",
        "2026-09-04",
        "1788494400000",
        "240.12000000",
        "2026-06-09",
        "169",
        "0.0100000000",
        "0.0200000000",
        "0.0300000000",
        "0.0400000000",
        "0.2000000000",
        "0.2500000000",
        "-0.0500000000",
        "-0.1000000000",
        "235.0000000000",
        "230.0000000000",
        "0.0200000000",
        "0.0400000000",
        "0.0217391304",
        "sip",
        "split",
        "1Day",
        "USD",
        "price-response-1",
        "1788580800000",
        "price-run-1",
    ]


def _fundamental_row() -> list[object]:
    return [
        "sec",
        "AAPL",
        "0000320193",
        "2026-07-31",
        "2026-06-27",
        "10-Q",
        "0000320193-26-000079",
        "400000000000.00000000",
        "100000000000.00000000",
        "0.2500000000",
        "350000000000.00000000",
        "0.0800000000",
        "7000000000.00000000",
        "2025-09-27",
        "2024-09-28",
        "annual_plus_ytd_minus_prior_ytd",
        "facts-response-1",
        "1788580800000",
        "facts-run-1",
    ]


class StructuredStatementParsingTests(unittest.TestCase):
    def test_parses_market_metric_row(self) -> None:
        metrics = parse_market_metrics_statement_response(
            _statement_response(
                MARKET_COLUMNS,
                _market_row(),
            )
        )

        self.assertEqual(len(metrics), 1)
        metric = metrics[0]
        self.assertEqual(metric.symbol, "AAPL")
        self.assertEqual(metric.as_of_date, date(2026, 9, 4))
        self.assertEqual(str(metric.close), "240.12000000")
        self.assertEqual(metric.observations_available, 169)
        self.assertEqual(
            metric.latest_source_fetched_at.tzinfo.utcoffset(
                metric.latest_source_fetched_at
            ).total_seconds(),
            0,
        )

    def test_parses_fundamental_metric_row(self) -> None:
        metrics = parse_fundamental_metrics_statement_response(
            _statement_response(
                FUNDAMENTAL_COLUMNS,
                _fundamental_row(),
            )
        )

        self.assertEqual(len(metrics), 1)
        metric = metrics[0]
        self.assertEqual(metric.symbol, "AAPL")
        self.assertEqual(metric.cik, "0000320193")
        self.assertEqual(metric.latest_filing_form, "10-Q")
        self.assertEqual(
            metric.ttm_derivation_method,
            "annual_plus_ytd_minus_prior_ytd",
        )

    def test_rejects_failed_statement(self) -> None:
        response = {
            "status": {
                "state": "FAILED",
                "error": {
                    "error_code": "BAD_REQUEST",
                    "message": "bad query",
                },
            }
        }

        with self.assertRaisesRegex(
            ControlledToolDataError,
            "BAD_REQUEST",
        ):
            parse_market_metrics_statement_response(response)

    def test_rejects_unexpected_columns(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolDataError,
            "controlled projection",
        ):
            parse_market_metrics_statement_response(
                _statement_response(
                    ("symbol",),
                    ["AAPL"],
                )
            )

    def test_rejects_multi_chunk_result(self) -> None:
        response = _statement_response(
            MARKET_COLUMNS,
            _market_row(),
        )
        response["result"]["next_chunk_index"] = 1

        with self.assertRaisesRegex(
            ControlledToolDataError,
            "multiple chunks",
        ):
            parse_market_metrics_statement_response(response)


class DatabricksCliRuntimeTests(unittest.TestCase):
    def test_statement_executor_polls_pending_to_success(self) -> None:
        pending = {
            "statement_id": "statement-1",
            "status": {
                "state": "PENDING",
            },
        }
        succeeded = _statement_response(
            MARKET_COLUMNS,
            _market_row(),
        )

        runner = Mock(
            side_effect=[
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(pending),
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(succeeded),
                    stderr="",
                ),
            ]
        )
        sleeper = Mock()

        response = execute_statement_via_cli(
            payload={
                "warehouse_id": "warehouse-1",
                "statement": "SELECT 1",
            },
            profile="free-edition-us-east-2",
            max_polls=2,
            poll_interval_seconds=0,
            runner=runner,
            sleeper=sleeper,
        )

        self.assertEqual(
            response["status"]["state"],
            "SUCCEEDED",
        )
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(
            runner.call_args_list[1].args[0][:4],
            [
                "databricks",
                "api",
                "get",
                "/api/2.0/sql/statements/statement-1",
            ],
        )
        sleeper.assert_called_once_with(0)

    def test_statement_executor_surfaces_failed_state(self) -> None:
        failed = {
            "statement_id": "statement-1",
            "status": {
                "state": "FAILED",
                "error": {
                    "error_code": "BAD_REQUEST",
                    "sql_state": "42000",
                    "message": "bad query",
                },
            },
        }

        runner = Mock(
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(failed),
                stderr="",
            )
        )

        with self.assertRaisesRegex(
            ControlledToolExecutionError,
            "BAD_REQUEST",
        ):
            execute_statement_via_cli(
                payload={
                    "warehouse_id": "warehouse-1",
                    "statement": "SELECT broken",
                },
                runner=runner,
            )

    def test_statement_executor_rejects_unknown_state(self) -> None:
        response = {
            "statement_id": "statement-1",
            "status": {
                "state": "MYSTERY",
            },
        }

        runner = Mock(
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )
        )

        with self.assertRaisesRegex(
            ControlledToolExecutionError,
            "unknown state",
        ):
            execute_statement_via_cli(
                payload={
                    "warehouse_id": "warehouse-1",
                    "statement": "SELECT 1",
                },
                runner=runner,
            )

    def test_chat_executor_uses_fixed_gateway_and_nonstreaming_payload(
        self,
    ) -> None:
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "message": {
                                    "role": "assistant",
                                    "content": "{\"findings\":[]}",
                                },
                            }
                        ]
                    }
                ),
                stderr="",
            )
        )

        response = query_chat_completions_via_cli(
            payload={
                "model": "system.ai.gpt-oss-20b",
                "messages": [
                    {
                        "role": "user",
                        "content": "test",
                    }
                ],
                "stream": False,
            },
            profile="free-edition-us-east-2",
            runner=runner,
        )

        self.assertIn("choices", response)

        command = runner.call_args.args[0]

        self.assertEqual(
            command[:4],
            [
                "databricks",
                "api",
                "post",
                "/ai-gateway/mlflow/v1/chat/completions",
            ],
        )

    def test_chat_executor_rejects_streaming_request(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolExecutionError,
            "must set stream=false",
        ):
            query_chat_completions_via_cli(
                payload={
                    "model": "system.ai.gpt-oss-20b",
                    "messages": [],
                    "stream": True,
                }
            )

    def test_vector_executor_uses_controlled_query_endpoint(self) -> None:
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    {
                        "manifest": {
                            "columns": [],
                        },
                        "result": {
                            "data_array": [],
                        },
                    }
                ),
                stderr="",
            )
        )

        response = query_vector_index_via_cli(
            index_name=(
                "workspace.equity_research_ai."
                "research_chunks_index"
            ),
            payload={
                "columns": ["chunk_id"],
                "query_text": "risk",
                "query_type": "HYBRID",
            },
            profile="free-edition-us-east-2",
            runner=runner,
        )

        self.assertIn("result", response)

        command = runner.call_args.args[0]

        self.assertEqual(
            command[:4],
            [
                "databricks",
                "api",
                "post",
                (
                    "/api/2.0/vector-search/indexes/"
                    "workspace.equity_research_ai."
                    "research_chunks_index/query"
                ),
            ],
        )

    def test_cli_nonzero_exit_becomes_execution_error(self) -> None:
        runner = Mock(
            side_effect=subprocess.CalledProcessError(
                1,
                ["databricks"],
                stderr="authentication failed",
            )
        )

        with self.assertRaisesRegex(
            ControlledToolExecutionError,
            "authentication failed",
        ):
            query_vector_index_via_cli(
                index_name=(
                    "workspace.equity_research_ai."
                    "research_chunks_index"
                ),
                payload={
                    "columns": ["chunk_id"],
                    "query_text": "risk",
                },
                runner=runner,
            )


if __name__ == "__main__":
    unittest.main()
