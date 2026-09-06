"""Offline tests for LangGraph Supervisor orchestration."""

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

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
from equity_research.supervisor_contracts import (  # noqa: E402
    SupervisorContractError,
    build_supervisor_plan,
)
from equity_research.supervisor_graph import (  # noqa: E402
    build_supervisor_graph,
    run_supervisor_graph,
)
from equity_research.tool_scope import ControlledToolRequestError  # noqa: E402


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


def _market_result(
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


def _company_result(
    *,
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


class SupervisorGraphTests(unittest.TestCase):
    def test_compiled_graph_returns_only_validated_supervisor_state(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )

        def market_worker(*, request):
            return _market_result(
                request.requested_symbols
            )

        def company_worker(*, request, topic):
            return _company_result(
                topic=topic,
                symbols=request.requested_symbols,
            )

        graph = build_supervisor_graph(
            market_worker=market_worker,
            company_worker=company_worker,
        )
        output = graph.invoke(
            {
                "plan": plan,
            }
        )

        self.assertEqual(
            set(output),
            {"supervisor_state"},
        )
        self.assertEqual(
            output["supervisor_state"].status,
            "ready",
        )

    def test_runs_all_three_worker_routes_once(self) -> None:
        market_calls = []
        company_calls = []

        def market_worker(*, request):
            market_calls.append(request)

            return _market_result(
                request.requested_symbols
            )

        def company_worker(*, request, topic):
            company_calls.append(
                (
                    request,
                    topic,
                )
            )

            return _company_result(
                topic=topic,
                symbols=request.requested_symbols,
            )

        state = run_supervisor_graph(
            request_text="Research Apple.",
            requested_symbols=("aapl",),
            market_worker=market_worker,
            company_worker=company_worker,
            equities=EQUITIES,
        )

        self.assertEqual(state.status, "ready")
        self.assertEqual(len(market_calls), 1)
        self.assertEqual(len(company_calls), 2)
        self.assertEqual(
            market_calls[0].requested_symbols,
            ("AAPL",),
        )
        self.assertEqual(
            {
                topic
                for _, topic in company_calls
            },
            {
                "recent_developments",
                "principal_risks",
            },
        )

    def test_comparison_scope_reaches_every_worker_normalized(self) -> None:
        requests = []

        def market_worker(*, request):
            requests.append(request)

            return _market_result(
                request.requested_symbols
            )

        def company_worker(*, request, topic):
            requests.append(request)

            return _company_result(
                topic=topic,
                symbols=request.requested_symbols,
            )

        state = run_supervisor_graph(
            request_text="Compare Microsoft and Apple.",
            requested_symbols=("msft", "aapl"),
            market_worker=market_worker,
            company_worker=company_worker,
            equities=EQUITIES,
        )

        self.assertEqual(state.status, "ready")
        self.assertEqual(len(requests), 3)

        for request in requests:
            self.assertEqual(
                request.requested_symbols,
                ("MSFT", "AAPL"),
            )
            self.assertEqual(
                request.mode,
                "comparison",
            )

    def test_one_worker_exception_is_captured_and_graph_continues(self) -> None:
        def market_worker(*, request):
            return _market_result(
                request.requested_symbols
            )

        def company_worker(*, request, topic):
            if topic == "recent_developments":
                raise RuntimeError(
                    "upstream retrieval unavailable"
                )

            return _company_result(
                topic=topic,
                symbols=request.requested_symbols,
            )

        state = run_supervisor_graph(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            market_worker=market_worker,
            company_worker=company_worker,
            equities=EQUITIES,
        )

        self.assertEqual(state.status, "degraded")
        self.assertEqual(len(state.failures), 1)
        self.assertEqual(
            state.failures[0].route_id,
            "recent_developments",
        )
        self.assertEqual(
            state.failures[0].reason_code,
            "worker_exception",
        )

    def test_worker_exception_text_is_not_copied_into_state(self) -> None:
        secret = "SECRET PROVIDER SOURCE TEXT"

        def market_worker(*, request):
            del request
            raise RuntimeError(secret)

        def company_worker(*, request, topic):
            return _company_result(
                topic=topic,
                symbols=request.requested_symbols,
            )

        state = run_supervisor_graph(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            market_worker=market_worker,
            company_worker=company_worker,
            equities=EQUITIES,
        )

        self.assertEqual(state.status, "degraded")
        self.assertNotIn(
            secret,
            state.failures[0].message,
        )
        self.assertIn(
            "RuntimeError",
            state.failures[0].message,
        )

    def test_all_worker_exceptions_make_graph_unavailable(self) -> None:
        def market_worker(*, request):
            del request
            raise RuntimeError("market down")

        def company_worker(*, request, topic):
            del request, topic
            raise RuntimeError("research down")

        state = run_supervisor_graph(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            market_worker=market_worker,
            company_worker=company_worker,
            equities=EQUITIES,
        )

        self.assertEqual(
            state.status,
            "unavailable",
        )
        self.assertEqual(
            len(state.failures),
            3,
        )

    def test_invalid_worker_result_is_rejected_during_aggregation(self) -> None:
        def market_worker(*, request):
            del request
            return _market_result(
                ("MSFT",)
            )

        def company_worker(*, request, topic):
            return _company_result(
                topic=topic,
                symbols=request.requested_symbols,
            )

        with self.assertRaisesRegex(
            SupervisorContractError,
            "outside Supervisor request scope",
        ):
            run_supervisor_graph(
                request_text="Research Apple.",
                requested_symbols=("AAPL",),
                market_worker=market_worker,
                company_worker=company_worker,
                equities=EQUITIES,
            )

    def test_unsupported_symbol_fails_before_any_worker_runs(self) -> None:
        market_worker = Mock()
        company_worker = Mock()

        with self.assertRaisesRegex(
            ControlledToolRequestError,
            "Unsupported symbol",
        ):
            run_supervisor_graph(
                request_text="Compare AAPL and NVDA.",
                requested_symbols=("AAPL", "NVDA"),
                market_worker=market_worker,
                company_worker=company_worker,
                equities=EQUITIES,
            )

        market_worker.assert_not_called()
        company_worker.assert_not_called()

    def test_rejects_noncallable_worker_dependency(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "market_worker must be callable",
        ):
            build_supervisor_graph(
                market_worker=None,  # type: ignore[arg-type]
                company_worker=Mock(),
            )

        with self.assertRaisesRegex(
            TypeError,
            "company_worker must be callable",
        ):
            build_supervisor_graph(
                market_worker=Mock(),
                company_worker=None,  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
