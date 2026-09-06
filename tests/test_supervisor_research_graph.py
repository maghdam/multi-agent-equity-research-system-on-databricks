"""Offline tests for the app-facing terminal Supervisor research graph."""

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
from equity_research.supervisor_research_graph import (  # noqa: E402
    build_supervisor_research_graph,
    run_supervisor_research_graph,
)
from equity_research.supervisor_report import SupervisorReport  # noqa: E402
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


def _market_worker(
    *,
    request,
):
    return _market_result(
        request.requested_symbols
    )


def _company_worker(
    *,
    request,
    topic,
):
    return _company_result(
        topic=topic,
        symbols=request.requested_symbols,
    )


def _report_for_state(
    state,
    *,
    mode: str | None = None,
    symbols: tuple[str, ...] | None = None,
    status: str | None = None,
) -> SupervisorReport:
    return SupervisorReport(
        mode=(
            state.request.mode
            if mode is None
            else mode
        ),
        symbols=(
            state.request.requested_symbols
            if symbols is None
            else symbols
        ),
        status=(
            state.status
            if status is None
            else status
        ),
        sections=(),
        limitations=(),
        evidence=(),
    )


class SupervisorResearchGraphTests(unittest.TestCase):
    def test_compiled_graph_runs_workers_then_terminal_synthesis(self) -> None:
        report_synthesizer = Mock(
            side_effect=lambda *, state: _report_for_state(state)
        )
        graph = build_supervisor_research_graph(
            market_worker=_market_worker,
            company_worker=_company_worker,
            report_synthesizer=report_synthesizer,
        )

        from equity_research.supervisor_contracts import build_supervisor_plan

        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )
        output = graph.invoke(
            {
                "plan": plan,
            }
        )

        self.assertEqual(
            set(output),
            {
                "supervisor_state",
                "report",
            },
        )
        self.assertEqual(
            output["supervisor_state"].status,
            "ready",
        )
        self.assertEqual(
            output["report"].status,
            "ready",
        )
        report_synthesizer.assert_called_once_with(
            state=output["supervisor_state"],
        )

    def test_run_returns_state_and_report_for_comparison(self) -> None:
        result = run_supervisor_research_graph(
            request_text="Compare Apple and Microsoft.",
            requested_symbols=("aapl", "msft"),
            market_worker=_market_worker,
            company_worker=_company_worker,
            report_synthesizer=(
                lambda *, state: _report_for_state(state)
            ),
            equities=EQUITIES,
        )

        self.assertEqual(
            result.state.request.requested_symbols,
            ("AAPL", "MSFT"),
        )
        self.assertEqual(
            result.state.status,
            "ready",
        )
        self.assertEqual(
            result.report.mode,
            "comparison",
        )
        self.assertEqual(
            result.report.symbols,
            ("AAPL", "MSFT"),
        )

    def test_degraded_worker_state_reaches_terminal_synthesis(self) -> None:
        def company_worker(*, request, topic):
            if topic == "recent_developments":
                raise RuntimeError(
                    "retrieval unavailable"
                )

            return _company_result(
                topic=topic,
                symbols=request.requested_symbols,
            )

        seen_statuses = []

        def report_synthesizer(*, state):
            seen_statuses.append(
                state.status
            )
            return _report_for_state(
                state
            )

        result = run_supervisor_research_graph(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            market_worker=_market_worker,
            company_worker=company_worker,
            report_synthesizer=report_synthesizer,
            equities=EQUITIES,
        )

        self.assertEqual(
            seen_statuses,
            ["degraded"],
        )
        self.assertEqual(
            result.state.status,
            "degraded",
        )
        self.assertEqual(
            result.report.status,
            "degraded",
        )

    def test_unsupported_symbol_fails_before_workers_or_synthesis(self) -> None:
        market_worker = Mock()
        company_worker = Mock()
        report_synthesizer = Mock()

        with self.assertRaises(
            ControlledToolRequestError,
        ):
            run_supervisor_research_graph(
                request_text="Research Nvidia.",
                requested_symbols=("NVDA",),
                market_worker=market_worker,
                company_worker=company_worker,
                report_synthesizer=report_synthesizer,
                equities=EQUITIES,
            )

        market_worker.assert_not_called()
        company_worker.assert_not_called()
        report_synthesizer.assert_not_called()

    def test_rejects_non_report_synthesizer_result(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "must return SupervisorReport",
        ):
            run_supervisor_research_graph(
                request_text="Research Apple.",
                requested_symbols=("AAPL",),
                market_worker=_market_worker,
                company_worker=_company_worker,
                report_synthesizer=lambda *, state: {
                    "status": state.status,
                },
                equities=EQUITIES,
            )

    def test_rejects_report_symbol_mismatch(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "symbols do not match",
        ):
            run_supervisor_research_graph(
                request_text="Research Apple.",
                requested_symbols=("AAPL",),
                market_worker=_market_worker,
                company_worker=_company_worker,
                report_synthesizer=(
                    lambda *, state: _report_for_state(
                        state,
                        symbols=("MSFT",),
                    )
                ),
                equities=EQUITIES,
            )

    def test_rejects_report_status_mismatch(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "status does not match",
        ):
            run_supervisor_research_graph(
                request_text="Research Apple.",
                requested_symbols=("AAPL",),
                market_worker=_market_worker,
                company_worker=_company_worker,
                report_synthesizer=(
                    lambda *, state: _report_for_state(
                        state,
                        status="degraded",
                    )
                ),
                equities=EQUITIES,
            )

    def test_rejects_noncallable_report_synthesizer(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "report_synthesizer must be callable",
        ):
            build_supervisor_research_graph(
                market_worker=_market_worker,
                company_worker=_company_worker,
                report_synthesizer=None,  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
