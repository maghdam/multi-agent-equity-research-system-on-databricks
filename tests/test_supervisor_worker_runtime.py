"""Offline tests for live Databricks-backed Supervisor worker adapters."""

import json
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.agent_contracts import AgentLimitation  # noqa: E402
from equity_research.company_researcher import (  # noqa: E402
    CompanyResearcherResult,
    ResearchFinding,
)
from equity_research.config import Equity  # noqa: E402
from equity_research.market_analyst import (  # noqa: E402
    MarketAnalystResult,
    MetricReference,
    StructuredFinding,
)
from equity_research.retrieval_tools import EvidenceRecord  # noqa: E402
from equity_research.supervisor_contracts import (  # noqa: E402
    SupervisorRequest,
)
from equity_research.supervisor_graph import run_supervisor_graph  # noqa: E402
from equity_research.supervisor_worker_runtime import (  # noqa: E402
    DatabricksSupervisorWorkers,
    SupervisorWorkerRuntimeConfig,
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


def _request(
    *symbols: str,
) -> SupervisorRequest:
    return SupervisorRequest(
        request_text="Compare Apple and Microsoft.",
        requested_symbols=tuple(symbols),
        mode=(
            "single_company"
            if len(symbols) == 1
            else "comparison"
        ),
    )


def _market_agent_result(
    symbols: tuple[str, ...],
) -> MarketAnalystResult:
    findings = []

    for symbol in symbols:
        findings.extend(
            [
                StructuredFinding(
                    finding_id=f"{symbol}-market",
                    dimension="market",
                    symbols=(symbol,),
                    statement=f"{symbol} market finding.",
                    metric_references=(
                        MetricReference(
                            dataset="market_metrics",
                            symbol=symbol,
                            as_of_date=date(2026, 9, 4),
                            fields=("return_20d",),
                        ),
                    ),
                ),
                StructuredFinding(
                    finding_id=f"{symbol}-fundamental",
                    dimension="fundamental",
                    symbols=(symbol,),
                    statement=f"{symbol} fundamental finding.",
                    metric_references=(
                        MetricReference(
                            dataset="fundamental_metrics",
                            symbol=symbol,
                            as_of_date=(
                                date(2026, 7, 31)
                                if symbol == "AAPL"
                                else date(2026, 7, 29)
                            ),
                            fields=("revenue_ttm",),
                        ),
                    ),
                ),
            ]
        )

    return MarketAnalystResult(
        findings=tuple(findings),
        limitations=(),
    )


def _company_agent_result(
    topic: str,
    symbols: tuple[str, ...],
) -> CompanyResearcherResult:
    characterization = (
        "development"
        if topic == "recent_developments"
        else "company_disclosed_risk"
    )

    return CompanyResearcherResult(
        findings=tuple(
            ResearchFinding(
                finding_id=f"{topic}-{symbol}",
                topic=topic,
                characterization=characterization,
                symbols=(symbol,),
                statement=f"{symbol} {topic} finding.",
                evidence_ids=(f"{symbol}-{topic}-evidence",),
            )
            for symbol in symbols
        ),
        limitations=(),
    )


def _evidence(
    evidence_id: str,
    *,
    symbol: str,
    source_type: str,
    rank: int = 1,
) -> EvidenceRecord:
    filing = source_type == "filing"

    return EvidenceRecord(
        evidence_id=evidence_id,
        retrieval_rank=rank,
        chunk_id=evidence_id,
        document_id=(
            f"sec:filing:{symbol}-accession:item_1a"
            if filing
            else f"alpaca:news:{symbol}-101"
        ),
        document_version_id=f"{symbol}-version",
        source_type=source_type,
        source_system="sec" if filing else "alpaca",
        configured_symbols=(symbol,),
        title=(
            f"{symbol} Risk Factors"
            if filing
            else f"{symbol} News"
        ),
        evidence_date=date(2026, 8, 30),
        source_url="https://example.test/evidence",
        source_business_id=(
            f"{symbol}-accession"
            if filing
            else f"{symbol}-101"
        ),
        section_code="item_1a" if filing else None,
        section_title="Risk Factors" if filing else None,
        chunk_index=0,
        text="Synthetic controlled evidence.",
        source_response_id=f"{symbol}-response",
        source_fetched_at=datetime(
            2026,
            9,
            5,
            20,
            0,
            tzinfo=timezone.utc,
        ),
        source_ingestion_run_id=f"{symbol}-run",
    )


class SupervisorWorkerRuntimeConfigTests(unittest.TestCase):
    def test_accepts_valid_runtime_config(self) -> None:
        config = SupervisorWorkerRuntimeConfig(
            warehouse_id="warehouse-1",
            gold_schema="gold_schema",
            index_name="workspace.ai.research_chunks_index",
            profile="profile-1",
        )

        self.assertEqual(
            config.retrieval_results_per_symbol,
            3,
        )

    def test_rejects_blank_required_resource(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "warehouse_id must be a nonblank string",
        ):
            SupervisorWorkerRuntimeConfig(
                warehouse_id=" ",
                gold_schema="gold_schema",
                index_name="workspace.ai.research_chunks_index",
            )

    def test_rejects_invalid_retrieval_depth(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "retrieval_results_per_symbol",
        ):
            SupervisorWorkerRuntimeConfig(
                warehouse_id="warehouse-1",
                gold_schema="gold_schema",
                index_name="workspace.ai.research_chunks_index",
                retrieval_results_per_symbol=11,
            )


class DatabricksSupervisorWorkersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SupervisorWorkerRuntimeConfig(
            warehouse_id="warehouse-1",
            gold_schema="gold_schema",
            index_name="workspace.ai.research_chunks_index",
            profile="profile-1",
            retrieval_results_per_symbol=2,
        )

    def test_market_worker_uses_exact_supervisor_scope_for_both_gold_queries(
        self,
    ) -> None:
        statement_executor = Mock(
            side_effect=[
                {"kind": "market"},
                {"kind": "fundamental"},
            ]
        )
        market_agent_runner = Mock(
            return_value=_market_agent_result(
                ("AAPL", "MSFT")
            )
        )
        now = datetime(
            2026,
            9,
            6,
            9,
            0,
            tzinfo=timezone.utc,
        )

        workers = DatabricksSupervisorWorkers(
            config=self.config,
            equities=EQUITIES,
            statement_executor=statement_executor,
            market_agent_runner=market_agent_runner,
            clock=lambda: now,
        )

        with (
            patch(
                "equity_research.supervisor_worker_runtime."
                "parse_market_metrics_statement_response",
                return_value=("market-metric",),
            ),
            patch(
                "equity_research.supervisor_worker_runtime."
                "parse_fundamental_metrics_statement_response",
                return_value=("fundamental-metric",),
            ),
            patch(
                "equity_research.supervisor_worker_runtime."
                "prepare_market_metrics_results",
                return_value=("market-result",),
            ) as prepare_market,
            patch(
                "equity_research.supervisor_worker_runtime."
                "prepare_fundamental_metrics_results",
                return_value=("fundamental-result",),
            ) as prepare_fundamental,
        ):
            result = workers.market_worker(
                request=_request("AAPL", "MSFT")
            )

        self.assertEqual(
            result,
            _market_agent_result(("AAPL", "MSFT")),
        )
        self.assertEqual(
            statement_executor.call_count,
            2,
        )

        for call in statement_executor.call_args_list:
            parameters = call.kwargs["payload"]["parameters"]
            self.assertEqual(
                tuple(
                    parameter["value"]
                    for parameter in parameters
                ),
                ("AAPL", "MSFT"),
            )
            self.assertEqual(
                call.kwargs["profile"],
                "profile-1",
            )

        prepare_market.assert_called_once_with(
            metrics=("market-metric",),
            requested_symbols=("AAPL", "MSFT"),
            now_utc=now,
            equities=EQUITIES,
        )
        prepare_fundamental.assert_called_once_with(
            metrics=("fundamental-metric",),
            requested_symbols=("AAPL", "MSFT"),
            now_utc=now,
            equities=EQUITIES,
        )

        market_agent_runner.assert_called_once_with(
            requested_symbols=("AAPL", "MSFT"),
            market_results=("market-result",),
            fundamental_results=("fundamental-result",),
            profile="profile-1",
            equities=EQUITIES,
        )

    def test_company_comparison_retrieves_and_runs_each_symbol_separately(
        self,
    ) -> None:
        vector_query = Mock(
            side_effect=[
                {"symbol": "AAPL"},
                {"symbol": "MSFT"},
            ]
        )
        company_agent_runner = Mock(
            side_effect=[
                _company_agent_result(
                    "recent_developments",
                    ("AAPL",),
                ),
                _company_agent_result(
                    "recent_developments",
                    ("MSFT",),
                ),
            ]
        )

        workers = DatabricksSupervisorWorkers(
            config=self.config,
            equities=EQUITIES,
            vector_query=vector_query,
            company_agent_runner=company_agent_runner,
        )

        with patch(
            "equity_research.supervisor_worker_runtime."
            "parse_retrieval_response",
            side_effect=[
                (
                    _evidence(
                        "a" * 64,
                        symbol="AAPL",
                        source_type="news",
                    ),
                ),
                (
                    _evidence(
                        "b" * 64,
                        symbol="MSFT",
                        source_type="news",
                    ),
                ),
            ],
        ) as parser:
            result = workers.company_worker(
                request=_request("AAPL", "MSFT"),
                topic="recent_developments",
            )

        self.assertEqual(vector_query.call_count, 2)
        self.assertEqual(
            tuple(
                call.kwargs["requested_symbols"]
                for call in parser.call_args_list
            ),
            (
                ("AAPL",),
                ("MSFT",),
            ),
        )

        self.assertEqual(
            company_agent_runner.call_count,
            2,
        )
        first_call, second_call = (
            company_agent_runner.call_args_list
        )
        self.assertEqual(
            first_call.kwargs["requested_symbols"],
            ("AAPL",),
        )
        self.assertEqual(
            second_call.kwargs["requested_symbols"],
            ("MSFT",),
        )
        self.assertEqual(
            tuple(
                item.evidence_id
                for item in first_call.kwargs["evidence"]
            ),
            ("a" * 64,),
        )
        self.assertEqual(
            tuple(
                item.evidence_id
                for item in second_call.kwargs["evidence"]
            ),
            ("b" * 64,),
        )

        self.assertEqual(
            tuple(
                finding.symbols
                for finding in result.findings
            ),
            (
                ("AAPL",),
                ("MSFT",),
            ),
        )
        self.assertEqual(
            tuple(
                finding.finding_id
                for finding in result.findings
            ),
            (
                "AAPL:recent_developments-AAPL",
                "MSFT:recent_developments-MSFT",
            ),
        )

        filters = [
            json.loads(
                call.kwargs["payload"]["filters_json"]
            )
            for call in vector_query.call_args_list
        ]
        self.assertEqual(
            filters,
            [
                {
                    "configured_symbols": "AAPL",
                    "source_type": "news",
                },
                {
                    "configured_symbols": "MSFT",
                    "source_type": "news",
                },
            ],
        )

    def test_company_comparison_scopes_insufficiency_to_missing_symbol(
        self,
    ) -> None:
        limitation = AgentLimitation(
            agent="company_researcher",
            symbol=None,
            dimension="recent_developments",
            reason_code="insufficient_evidence",
            message="No sufficiently relevant evidence was found.",
        )
        company_agent_runner = Mock(
            side_effect=[
                _company_agent_result(
                    "recent_developments",
                    ("AAPL",),
                ),
                CompanyResearcherResult(
                    findings=(),
                    limitations=(limitation,),
                ),
            ]
        )
        workers = DatabricksSupervisorWorkers(
            config=self.config,
            equities=EQUITIES,
            vector_query=Mock(
                side_effect=[
                    {"symbol": "AAPL"},
                    {"symbol": "MSFT"},
                ]
            ),
            company_agent_runner=company_agent_runner,
        )

        with patch(
            "equity_research.supervisor_worker_runtime."
            "parse_retrieval_response",
            side_effect=[
                (
                    _evidence(
                        "c" * 64,
                        symbol="AAPL",
                        source_type="news",
                    ),
                ),
                (),
            ],
        ):
            result = workers.company_worker(
                request=_request("AAPL", "MSFT"),
                topic="recent_developments",
            )

        self.assertEqual(
            tuple(
                finding.symbols
                for finding in result.findings
            ),
            (("AAPL",),),
        )
        self.assertEqual(
            len(result.limitations),
            1,
        )
        self.assertEqual(
            result.limitations[0].symbol,
            "MSFT",
        )
        self.assertEqual(
            result.limitations[0].reason_code,
            "insufficient_evidence",
        )

    def test_principal_risk_worker_uses_item_1a_filing_filter(self) -> None:
        company_agent_runner = Mock(
            return_value=_company_agent_result(
                "principal_risks",
                ("AAPL",),
            )
        )
        vector_query = Mock(
            return_value={"symbol": "AAPL"}
        )

        workers = DatabricksSupervisorWorkers(
            config=self.config,
            equities=EQUITIES,
            vector_query=vector_query,
            company_agent_runner=company_agent_runner,
        )

        with patch(
            "equity_research.supervisor_worker_runtime."
            "parse_retrieval_response",
            return_value=(
                _evidence(
                    "d" * 64,
                    symbol="AAPL",
                    source_type="filing",
                ),
            ),
        ):
            workers.company_worker(
                request=_request("AAPL"),
                topic="principal_risks",
            )

        filters = json.loads(
            vector_query.call_args.kwargs["payload"][
                "filters_json"
            ]
        )

        self.assertEqual(
            filters,
            {
                "configured_symbols": "AAPL",
                "section_code": "item_1a",
                "source_type": "filing",
            },
        )

    def test_real_adapter_methods_plug_into_compiled_graph(self) -> None:
        market_agent_runner = Mock(
            return_value=_market_agent_result(
                ("AAPL",)
            )
        )
        def company_agent_runner(**kwargs):
            return _company_agent_result(
                kwargs["topic"],
                ("AAPL",),
            )

        workers = DatabricksSupervisorWorkers(
            config=self.config,
            equities=EQUITIES,
            statement_executor=Mock(
                side_effect=[
                    {"kind": "market"},
                    {"kind": "fundamental"},
                ]
            ),
            vector_query=Mock(
                return_value={"kind": "retrieval"}
            ),
            market_agent_runner=market_agent_runner,
            company_agent_runner=company_agent_runner,
            clock=lambda: datetime(
                2026,
                9,
                6,
                9,
                0,
                tzinfo=timezone.utc,
            ),
        )

        def parse_evidence_by_source(
            response,
            *,
            requested_symbols,
            expected_source_type,
            equities,
        ):
            del response, equities
            return (
                _evidence(
                    (
                        "e" * 64
                        if expected_source_type == "news"
                        else "f" * 64
                    ),
                    symbol=requested_symbols[0],
                    source_type=expected_source_type,
                ),
            )

        with (
            patch(
                "equity_research.supervisor_worker_runtime."
                "parse_market_metrics_statement_response",
                return_value=("market-metric",),
            ),
            patch(
                "equity_research.supervisor_worker_runtime."
                "parse_fundamental_metrics_statement_response",
                return_value=("fundamental-metric",),
            ),
            patch(
                "equity_research.supervisor_worker_runtime."
                "prepare_market_metrics_results",
                return_value=("market-result",),
            ),
            patch(
                "equity_research.supervisor_worker_runtime."
                "prepare_fundamental_metrics_results",
                return_value=("fundamental-result",),
            ),
            patch(
                "equity_research.supervisor_worker_runtime."
                "parse_retrieval_response",
                side_effect=parse_evidence_by_source,
            ),
        ):
            state = run_supervisor_graph(
                request_text="Research Apple.",
                requested_symbols=("AAPL",),
                market_worker=workers.market_worker,
                company_worker=workers.company_worker,
                equities=EQUITIES,
            )

        self.assertEqual(
            state.status,
            "ready",
        )
        self.assertEqual(
            len(state.outcomes),
            3,
        )


if __name__ == "__main__":
    unittest.main()
