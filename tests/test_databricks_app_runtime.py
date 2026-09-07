from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.app_contracts import (  # noqa: E402
    build_app_research_selection,
)
from equity_research.config import Equity  # noqa: E402
from equity_research.databricks_app_runtime import (  # noqa: E402
    CATALOG_ENV,
    FUNDAMENTAL_METRICS_TABLE_ENV,
    GOLD_SCHEMA_ENV,
    MARKET_METRICS_TABLE_ENV,
    MLFLOW_EXPERIMENT_ENV,
    VECTOR_INDEX_ENV,
    WAREHOUSE_ENV,
    DatabricksAppResearchRuntime,
    DatabricksAppRuntimeConfig,
    DatabricksAppTransport,
)
from equity_research.databricks_cli_runtime import (  # noqa: E402
    ControlledToolExecutionError,
)
from equity_research.structured_data_tools import (  # noqa: E402
    FundamentalMetricsToolResult,
    MarketMetricsToolResult,
)
from equity_research.supervisor_research_graph import (  # noqa: E402
    SupervisorResearchResult,
)


EQUITIES = {
    "AAPL": Equity(
        symbol="AAPL",
        display_name="Apple Inc.",
        alpaca_symbol="AAPL",
        sec_cik="0000320193",
    ),
    "MSFT": Equity(
        symbol="MSFT",
        display_name="Microsoft Corporation",
        alpaca_symbol="MSFT",
        sec_cik="0000789019",
    ),
}


class FakeApiClient:
    def __init__(
        self,
        responses,
    ) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def do(
        self,
        *,
        method,
        path,
        body=None,
    ):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "body": body,
            }
        )
        return self.responses.pop(0)


class FakeWorkspaceClient:
    def __init__(
        self,
        responses,
    ) -> None:
        self.api_client = FakeApiClient(
            responses
        )


class FakeTransport:
    def __init__(self) -> None:
        self.execute_statement = lambda **kwargs: {}
        self.query_vector_index = lambda **kwargs: {}
        self.query_chat_completions = lambda **kwargs: {}


def _market_result(
    symbol: str,
) -> MarketMetricsToolResult:
    return MarketMetricsToolResult(
        symbol=symbol,
        display_name=EQUITIES[symbol].display_name,
        status="unavailable",
        reason_code="missing",
        limitation="Synthetic runtime test limitation.",
        metric=None,
    )


def _fundamental_result(
    symbol: str,
) -> FundamentalMetricsToolResult:
    return FundamentalMetricsToolResult(
        symbol=symbol,
        display_name=EQUITIES[symbol].display_name,
        status="unavailable",
        reason_code="missing",
        limitation="Synthetic runtime test limitation.",
        metric=None,
    )


class DatabricksAppRuntimeTests(unittest.TestCase):
    def test_config_resolves_bound_resource_environment_values(self) -> None:
        config = DatabricksAppRuntimeConfig.from_environment(
            {
                WAREHOUSE_ENV: " warehouse-1 ",
                MARKET_METRICS_TABLE_ENV: (
                    "workspace.gold_schema.market_metrics"
                ),
                FUNDAMENTAL_METRICS_TABLE_ENV: (
                    "workspace.gold_schema.fundamental_metrics"
                ),
                VECTOR_INDEX_ENV: "workspace.ai.index",
                MLFLOW_EXPERIMENT_ENV: "/Shared/app-traces",
            }
        )

        self.assertEqual(
            config.warehouse_id,
            "warehouse-1",
        )
        self.assertEqual(
            config.gold_schema,
            "gold_schema",
        )
        self.assertEqual(
            config.index_name,
            "workspace.ai.index",
        )
        self.assertEqual(
            config.catalog,
            "workspace",
        )
        self.assertEqual(
            config.mlflow_experiment,
            "/Shared/app-traces",
        )

    def test_config_requires_bound_runtime_resources(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            WAREHOUSE_ENV,
        ):
            DatabricksAppRuntimeConfig.from_environment(
                {
                    GOLD_SCHEMA_ENV: "gold_schema",
                    VECTOR_INDEX_ENV: "workspace.ai.index",
                }
            )

    def test_bound_gold_tables_must_share_catalog_and_schema(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "must share the same catalog and schema",
        ):
            DatabricksAppRuntimeConfig.from_environment(
                {
                    WAREHOUSE_ENV: "warehouse-1",
                    MARKET_METRICS_TABLE_ENV: (
                        "workspace.gold_a.market_metrics"
                    ),
                    FUNDAMENTAL_METRICS_TABLE_ENV: (
                        "workspace.gold_b.fundamental_metrics"
                    ),
                    VECTOR_INDEX_ENV: "workspace.ai.index",
                }
            )

    def test_legacy_schema_environment_remains_supported_locally(self) -> None:
        config = DatabricksAppRuntimeConfig.from_environment(
            {
                WAREHOUSE_ENV: "warehouse-1",
                GOLD_SCHEMA_ENV: "gold_schema",
                CATALOG_ENV: "workspace",
                VECTOR_INDEX_ENV: "workspace.ai.index",
            }
        )

        self.assertEqual(
            config.catalog,
            "workspace",
        )
        self.assertEqual(
            config.gold_schema,
            "gold_schema",
        )


    def test_statement_transport_polls_with_authenticated_client(self) -> None:
        workspace = FakeWorkspaceClient(
            [
                {
                    "statement_id": "statement-1",
                    "status": {
                        "state": "PENDING",
                    },
                },
                {
                    "statement_id": "statement-1",
                    "status": {
                        "state": "SUCCEEDED",
                    },
                    "result": {
                        "data_array": [],
                    },
                },
            ]
        )
        sleeps: list[float] = []
        transport = DatabricksAppTransport(
            workspace_client=workspace,
            sleeper=sleeps.append,
        )

        response = transport.execute_statement(
            payload={
                "warehouse_id": "warehouse-1",
                "statement": "SELECT 1",
            },
            max_polls=1,
            poll_interval_seconds=0.25,
        )

        self.assertEqual(
            response["status"]["state"],
            "SUCCEEDED",
        )
        self.assertEqual(
            sleeps,
            [0.25],
        )
        self.assertEqual(
            workspace.api_client.calls[0]["path"],
            "/api/2.0/sql/statements",
        )
        self.assertEqual(
            workspace.api_client.calls[1]["path"],
            "/api/2.0/sql/statements/statement-1",
        )

    def test_vector_and_chat_transport_use_existing_api_contracts(self) -> None:
        workspace = FakeWorkspaceClient(
            [
                {
                    "result": {
                        "data_array": [],
                    }
                },
                {
                    "choices": [],
                },
            ]
        )
        transport = DatabricksAppTransport(
            workspace_client=workspace,
        )

        transport.query_vector_index(
            index_name="workspace.ai.research_chunks_index",
            payload={
                "query_text": "Apple risks",
            },
        )
        transport.query_chat_completions(
            payload={
                "stream": False,
                "model": "system.ai.gpt-oss-20b",
                "messages": [],
            },
        )

        self.assertEqual(
            workspace.api_client.calls[0]["path"],
            (
                "/api/2.0/vector-search/indexes/"
                "workspace.ai.research_chunks_index/query"
            ),
        )
        self.assertEqual(
            workspace.api_client.calls[1]["path"],
            "/ai-gateway/mlflow/v1/chat/completions",
        )

    def test_app_transport_rejects_cli_profile(self) -> None:
        transport = DatabricksAppTransport(
            workspace_client=FakeWorkspaceClient(
                []
            ),
        )

        with self.assertRaisesRegex(
            ControlledToolExecutionError,
            "unified authentication",
        ):
            transport.query_chat_completions(
                payload={
                    "stream": False,
                },
                profile="developer-profile",
            )

    def test_runtime_returns_atomic_structured_and_research_result(self) -> None:
        selection = build_app_research_selection(
            primary_symbol="AAPL",
            comparison_symbol="MSFT",
            market_window_sessions=60,
            equities=EQUITIES,
        )
        transport = FakeTransport()

        class FakeWorkers:
            def __init__(
                self,
                *,
                market_agent_runner,
                company_agent_runner,
                **_kwargs,
            ) -> None:
                self._market_agent_runner = market_agent_runner
                self._company_agent_runner = company_agent_runner

            def market_worker(
                self,
                *,
                request,
            ):
                return self._market_agent_runner(
                    requested_symbols=request.requested_symbols,
                    market_results=(
                        _market_result("AAPL"),
                        _market_result("MSFT"),
                    ),
                    fundamental_results=(
                        _fundamental_result("AAPL"),
                        _fundamental_result("MSFT"),
                    ),
                    profile=None,
                    equities=EQUITIES,
                )

            def company_worker(
                self,
                *,
                request,
                topic,
            ):
                return self._company_agent_runner(
                    topic=topic,
                    requested_symbols=(
                        request.requested_symbols[0],
                    ),
                    evidence=(),
                    profile=None,
                    equities=EQUITIES,
                )

        def fake_graph_runner(
            *,
            request_text,
            requested_symbols,
            market_worker,
            **_kwargs,
        ):
            request = SimpleNamespace(
                requested_symbols=tuple(
                    requested_symbols
                ),
            )
            market_worker(
                request=request,
            )
            return SupervisorResearchResult(
                state=object(),
                report=SimpleNamespace(
                    symbols=tuple(
                        requested_symbols
                    ),
                    mode="comparison",
                ),
            )

        runtime = DatabricksAppResearchRuntime(
            config=DatabricksAppRuntimeConfig(
                warehouse_id="warehouse-1",
                gold_schema="gold_schema",
                index_name="workspace.ai.index",
            ),
            transport=transport,
            equities=EQUITIES,
        )

        with (
            patch(
                "equity_research.databricks_app_runtime."
                "DatabricksSupervisorWorkers",
                FakeWorkers,
            ),
            patch(
                "equity_research.databricks_app_runtime."
                "run_market_analyst",
                return_value=object(),
            ),
            patch(
                "equity_research.databricks_app_runtime."
                "run_company_researcher",
                return_value=object(),
            ),
            patch(
                "equity_research.databricks_app_runtime."
                "run_supervisor_research_graph",
                side_effect=fake_graph_runner,
            ),
        ):
            structured, research = runtime.run_research(
                selection=selection,
                request_text="Compare AAPL and MSFT.",
            )

        self.assertEqual(
            tuple(
                item.symbol
                for item in structured.market_results
            ),
            ("AAPL", "MSFT"),
        )
        self.assertEqual(
            tuple(
                item.symbol
                for item in structured.fundamental_results
            ),
            ("AAPL", "MSFT"),
        )
        self.assertEqual(
            research.report.symbols,
            ("AAPL", "MSFT"),
        )


if __name__ == "__main__":
    unittest.main()
