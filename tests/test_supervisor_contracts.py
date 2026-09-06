"""Offline tests for deterministic Supervisor request and aggregation contracts."""

import sys
import unittest
from datetime import date
from pathlib import Path


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
from equity_research.supervisor_contracts import (  # noqa: E402
    EXPECTED_ROUTES,
    SupervisorContractError,
    SupervisorPlan,
    SupervisorRequest,
    SupervisorWorkerFailure,
    SupervisorWorkerOutcome,
    assemble_supervisor_state,
    build_supervisor_plan,
    failed_worker_outcome,
    successful_worker_outcome,
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
    *,
    limitations: tuple[AgentLimitation, ...] = (),
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
        limitations=limitations,
    )


def _company_result(
    *,
    topic: str,
    symbols: tuple[str, ...],
    limitations: tuple[AgentLimitation, ...] = (),
) -> CompanyResearcherResult:
    characterization = (
        "development"
        if topic == "recent_developments"
        else "company_disclosed_risk"
    )

    findings = tuple(
        ResearchFinding(
            finding_id=f"{topic}-{symbol}",
            topic=topic,
            characterization=characterization,
            symbols=(symbol,),
            statement=f"{symbol} {topic} finding.",
            evidence_ids=(f"{symbol}-{topic}-evidence",),
        )
        for symbol in symbols
    )

    return CompanyResearcherResult(
        findings=findings,
        limitations=limitations,
    )


def _ready_outcomes(
    symbols: tuple[str, ...],
) -> tuple[SupervisorWorkerOutcome, ...]:
    return (
        successful_worker_outcome(
            route_id="market_analysis",
            result=_market_result(symbols),
        ),
        successful_worker_outcome(
            route_id="recent_developments",
            result=_company_result(
                topic="recent_developments",
                symbols=symbols,
            ),
        ),
        successful_worker_outcome(
            route_id="principal_risks",
            result=_company_result(
                topic="principal_risks",
                symbols=symbols,
            ),
        ),
    )


class SupervisorRequestPlanTests(unittest.TestCase):
    def test_builds_single_company_plan(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("aapl",),
            equities=EQUITIES,
        )

        self.assertEqual(
            plan.request.requested_symbols,
            ("AAPL",),
        )
        self.assertEqual(
            plan.request.mode,
            "single_company",
        )
        self.assertEqual(
            plan.routes,
            EXPECTED_ROUTES,
        )

    def test_builds_comparison_plan(self) -> None:
        plan = build_supervisor_plan(
            request_text="Compare Apple and Microsoft.",
            requested_symbols=("MSFT", "AAPL"),
            equities=EQUITIES,
        )

        self.assertEqual(
            plan.request.requested_symbols,
            ("MSFT", "AAPL"),
        )
        self.assertEqual(
            plan.request.mode,
            "comparison",
        )

    def test_rejects_blank_request_text(self) -> None:
        with self.assertRaisesRegex(
            SupervisorContractError,
            "request_text must be a nonblank string",
        ):
            build_supervisor_plan(
                request_text=" ",
                requested_symbols=("AAPL",),
                equities=EQUITIES,
            )

    def test_rejects_unsupported_symbol_before_plan(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolRequestError,
            "Unsupported requested symbols",
        ):
            build_supervisor_plan(
                request_text="Compare AAPL and NVDA.",
                requested_symbols=("AAPL", "NVDA"),
                equities=EQUITIES,
            )

    def test_rejects_duplicate_symbol_before_plan(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolRequestError,
            "must be unique",
        ):
            build_supervisor_plan(
                request_text="Research Apple.",
                requested_symbols=("AAPL", "aapl"),
                equities=EQUITIES,
            )

    def test_rejects_manually_mismatched_mode(self) -> None:
        plan = SupervisorPlan(
            request=SupervisorRequest(
                request_text="Research Apple.",
                requested_symbols=("AAPL",),
                mode="comparison",
            ),
            routes=EXPECTED_ROUTES,
        )

        with self.assertRaisesRegex(
            SupervisorContractError,
            "mode does not match",
        ):
            assemble_supervisor_state(
                plan=plan,
                outcomes=_ready_outcomes(("AAPL",)),
            )

    def test_rejects_manually_unnormalized_symbol(self) -> None:
        plan = SupervisorPlan(
            request=SupervisorRequest(
                request_text="Research Apple.",
                requested_symbols=("aapl",),
                mode="single_company",
            ),
            routes=EXPECTED_ROUTES,
        )

        with self.assertRaisesRegex(
            SupervisorContractError,
            "must already be normalized",
        ):
            assemble_supervisor_state(
                plan=plan,
                outcomes=_ready_outcomes(("AAPL",)),
            )


class SupervisorAggregationTests(unittest.TestCase):
    def test_ready_when_all_routes_succeed_without_limitations(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )

        state = assemble_supervisor_state(
            plan=plan,
            outcomes=_ready_outcomes(("AAPL",)),
        )

        self.assertEqual(state.status, "ready")
        self.assertEqual(state.limitations, ())
        self.assertEqual(state.failures, ())
        self.assertEqual(
            tuple(outcome.route_id for outcome in state.outcomes),
            (
                "market_analysis",
                "recent_developments",
                "principal_risks",
            ),
        )

    def test_worker_limitation_makes_state_degraded(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )
        limitation = AgentLimitation(
            agent="market_analyst",
            symbol="AAPL",
            dimension="market",
            reason_code="stale",
            message="AAPL market metrics are stale.",
        )
        market = _market_result(
            ("AAPL",),
            limitations=(limitation,),
        )
        market = MarketAnalystResult(
            findings=tuple(
                finding
                for finding in market.findings
                if finding.dimension != "market"
            ),
            limitations=(limitation,),
        )

        outcomes = list(
            _ready_outcomes(("AAPL",))
        )
        outcomes[0] = successful_worker_outcome(
            route_id="market_analysis",
            result=market,
        )

        state = assemble_supervisor_state(
            plan=plan,
            outcomes=outcomes,
        )

        self.assertEqual(state.status, "degraded")
        self.assertEqual(
            state.limitations,
            (limitation,),
        )

    def test_one_hard_failure_makes_state_degraded(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )
        outcomes = list(
            _ready_outcomes(("AAPL",))
        )
        outcomes[1] = failed_worker_outcome(
            route_id="recent_developments",
            reason_code="model_error",
            message="Company Researcher invocation failed.",
        )

        state = assemble_supervisor_state(
            plan=plan,
            outcomes=outcomes,
        )

        self.assertEqual(state.status, "degraded")
        self.assertEqual(len(state.failures), 1)
        self.assertEqual(
            state.failures[0].route_id,
            "recent_developments",
        )

    def test_all_hard_failures_make_state_unavailable(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )

        state = assemble_supervisor_state(
            plan=plan,
            outcomes=(
                failed_worker_outcome(
                    route_id="market_analysis",
                    reason_code="tool_error",
                    message="Gold tools unavailable.",
                ),
                failed_worker_outcome(
                    route_id="recent_developments",
                    reason_code="retrieval_error",
                    message="News retrieval unavailable.",
                ),
                failed_worker_outcome(
                    route_id="principal_risks",
                    reason_code="retrieval_error",
                    message="Filing retrieval unavailable.",
                ),
            ),
        )

        self.assertEqual(state.status, "unavailable")
        self.assertEqual(len(state.failures), 3)

    def test_rejects_missing_route_outcome(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )

        with self.assertRaisesRegex(
            SupervisorContractError,
            "exactly match the planned routes",
        ):
            assemble_supervisor_state(
                plan=plan,
                outcomes=_ready_outcomes(("AAPL",))[:2],
            )

    def test_rejects_duplicate_route_outcome(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )
        market = successful_worker_outcome(
            route_id="market_analysis",
            result=_market_result(("AAPL",)),
        )

        with self.assertRaisesRegex(
            SupervisorContractError,
            "Duplicate Supervisor outcome",
        ):
            assemble_supervisor_state(
                plan=plan,
                outcomes=(
                    market,
                    market,
                    successful_worker_outcome(
                        route_id="principal_risks",
                        result=_company_result(
                            topic="principal_risks",
                            symbols=("AAPL",),
                        ),
                    ),
                ),
            )

    def test_rejects_wrong_result_type_for_market_route(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )
        outcomes = list(
            _ready_outcomes(("AAPL",))
        )
        outcomes[0] = successful_worker_outcome(
            route_id="market_analysis",
            result=_company_result(
                topic="recent_developments",
                symbols=("AAPL",),
            ),
        )

        with self.assertRaisesRegex(
            SupervisorContractError,
            "requires MarketAnalystResult",
        ):
            assemble_supervisor_state(
                plan=plan,
                outcomes=outcomes,
            )

    def test_rejects_company_result_with_wrong_topic(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )
        outcomes = list(
            _ready_outcomes(("AAPL",))
        )
        outcomes[1] = successful_worker_outcome(
            route_id="recent_developments",
            result=_company_result(
                topic="principal_risks",
                symbols=("AAPL",),
            ),
        )

        with self.assertRaisesRegex(
            SupervisorContractError,
            "topic does not match",
        ):
            assemble_supervisor_state(
                plan=plan,
                outcomes=outcomes,
            )

    def test_rejects_out_of_scope_market_finding(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )
        outcomes = list(
            _ready_outcomes(("AAPL",))
        )
        outcomes[0] = successful_worker_outcome(
            route_id="market_analysis",
            result=_market_result(("MSFT",)),
        )

        with self.assertRaisesRegex(
            SupervisorContractError,
            "outside Supervisor request scope",
        ):
            assemble_supervisor_state(
                plan=plan,
                outcomes=outcomes,
            )

    def test_comparison_rejects_silent_company_coverage_omission(self) -> None:
        plan = build_supervisor_plan(
            request_text="Compare Apple and Microsoft.",
            requested_symbols=("AAPL", "MSFT"),
            equities=EQUITIES,
        )
        outcomes = list(
            _ready_outcomes(("AAPL", "MSFT"))
        )
        outcomes[1] = successful_worker_outcome(
            route_id="recent_developments",
            result=_company_result(
                topic="recent_developments",
                symbols=("AAPL",),
            ),
        )

        with self.assertRaisesRegex(
            SupervisorContractError,
            "silently omits requested-symbol coverage",
        ):
            assemble_supervisor_state(
                plan=plan,
                outcomes=outcomes,
            )

    def test_comparison_allows_missing_company_when_limitation_is_explicit(
        self,
    ) -> None:
        plan = build_supervisor_plan(
            request_text="Compare Apple and Microsoft.",
            requested_symbols=("AAPL", "MSFT"),
            equities=EQUITIES,
        )
        limitation = AgentLimitation(
            agent="company_researcher",
            symbol=None,
            dimension="recent_developments",
            reason_code="insufficient_evidence",
            message="No sufficient MSFT development evidence was available.",
        )
        outcomes = list(
            _ready_outcomes(("AAPL", "MSFT"))
        )
        outcomes[1] = successful_worker_outcome(
            route_id="recent_developments",
            result=_company_result(
                topic="recent_developments",
                symbols=("AAPL",),
                limitations=(limitation,),
            ),
        )

        state = assemble_supervisor_state(
            plan=plan,
            outcomes=outcomes,
        )

        self.assertEqual(state.status, "degraded")
        self.assertIn(
            limitation,
            state.limitations,
        )

    def test_rejects_failed_outcome_with_mismatched_failure_route(self) -> None:
        plan = build_supervisor_plan(
            request_text="Research Apple.",
            requested_symbols=("AAPL",),
            equities=EQUITIES,
        )
        malformed = SupervisorWorkerOutcome(
            route_id="market_analysis",
            status="failed",
            result=None,
            failure=SupervisorWorkerFailure(
                route_id="recent_developments",
                reason_code="tool_error",
                message="Bad route.",
            ),
        )
        outcomes = list(
            _ready_outcomes(("AAPL",))
        )
        outcomes[0] = malformed

        with self.assertRaisesRegex(
            SupervisorContractError,
            "failure route does not match",
        ):
            assemble_supervisor_state(
                plan=plan,
                outcomes=outcomes,
            )

    def test_rejects_blank_failure_message(self) -> None:
        with self.assertRaisesRegex(
            SupervisorContractError,
            "message must be a nonblank string",
        ):
            failed_worker_outcome(
                route_id="market_analysis",
                reason_code="tool_error",
                message=" ",
            )


if __name__ == "__main__":
    unittest.main()
