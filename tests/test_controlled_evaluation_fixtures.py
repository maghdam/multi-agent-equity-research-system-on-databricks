"""Offline tests for controlled E4-E6 execution fixtures."""

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.config import Equity  # noqa: E402
from equity_research.controlled_evaluation_fixtures import (  # noqa: E402
    e4_company_worker,
    e4_market_worker,
    e4_report_synthesizer,
    e5_company_worker,
    e5_market_worker,
    e5_report_synthesizer,
)
from equity_research.supervisor_contracts import SupervisorRequest  # noqa: E402
from equity_research.supervisor_research_graph import (  # noqa: E402
    run_supervisor_research_graph,
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


class ControlledE4FixtureTests(unittest.TestCase):
    def test_e4_propagates_stale_msft_market_data_without_substitution(
        self,
    ) -> None:
        result = run_supervisor_research_graph(
            request_text=(
                "Compare AAPL and MSFT. Summarize market performance, "
                "fundamentals, recent developments, and principal risks."
            ),
            requested_symbols=(
                "AAPL",
                "MSFT",
            ),
            market_worker=e4_market_worker,
            company_worker=e4_company_worker,
            report_synthesizer=e4_report_synthesizer,
            equities=EQUITIES,
        )

        self.assertEqual(
            result.state.status,
            "degraded",
        )
        self.assertEqual(
            len(result.state.limitations),
            1,
        )
        limitation = result.state.limitations[0]
        self.assertEqual(
            (
                limitation.agent,
                limitation.symbol,
                limitation.dimension,
                limitation.reason_code,
            ),
            (
                "market_analyst",
                "MSFT",
                "market",
                "stale",
            ),
        )

        self.assertEqual(
            result.report.status,
            "degraded",
        )
        self.assertEqual(
            result.report.synthesis_mode,
            "deterministic_fallback",
        )

        sections = {
            section.section: section
            for section in result.report.sections
        }
        market = sections[
            "market_performance"
        ]
        fundamental = sections[
            "fundamental_performance"
        ]
        comparative = sections[
            "comparative_assessment"
        ]

        self.assertEqual(
            market.status,
            "degraded",
        )
        self.assertEqual(
            market.source_finding_ids,
            (
                "market_analysis:market_AAPL",
            ),
        )
        self.assertNotIn(
            "market_analysis:market_MSFT",
            market.source_finding_ids,
        )
        self.assertEqual(
            fundamental.status,
            "available",
        )
        self.assertTrue(
            {
                "market_analysis:fundamental_AAPL",
                "market_analysis:fundamental_MSFT",
            }.issubset(
                set(
                    fundamental.source_finding_ids
                )
            )
        )
        self.assertTrue(
            all(
                not source_id.startswith(
                    "market_analysis:market_"
                )
                for source_id in comparative.source_finding_ids
            )
        )
        self.assertTrue(
            any(
                "MSFT" in value
                and "market" in value
                and "(stale)" in value
                for value in result.report.limitations
            )
        )

    def test_e5_omits_unsupported_recent_developments_and_discloses_gap(
        self,
    ) -> None:
        result = run_supervisor_research_graph(
            request_text=(
                "Research AAPL and summarize market performance, fundamentals, "
                "recent developments, and principal risks."
            ),
            requested_symbols=("AAPL",),
            market_worker=e5_market_worker,
            company_worker=e5_company_worker,
            report_synthesizer=e5_report_synthesizer,
            equities=EQUITIES,
        )

        self.assertEqual(
            result.state.status,
            "degraded",
        )
        self.assertEqual(
            len(result.state.limitations),
            1,
        )
        limitation = result.state.limitations[0]
        self.assertEqual(
            (
                limitation.agent,
                limitation.symbol,
                limitation.dimension,
                limitation.reason_code,
            ),
            (
                "company_researcher",
                None,
                "recent_developments",
                "insufficient_evidence",
            ),
        )

        sections = {
            section.section: section
            for section in result.report.sections
        }
        recent = sections[
            "recent_developments"
        ]
        risks = sections[
            "principal_risks"
        ]

        self.assertEqual(
            result.report.status,
            "degraded",
        )
        self.assertEqual(
            result.report.synthesis_mode,
            "deterministic_fallback",
        )
        self.assertEqual(
            recent.status,
            "unavailable",
        )
        self.assertEqual(
            recent.source_finding_ids,
            (),
        )
        self.assertEqual(
            risks.status,
            "available",
        )
        self.assertEqual(
            risks.source_finding_ids,
            (
                "principal_risks:AAPL:principal_risks",
            ),
        )
        self.assertEqual(
            tuple(
                citation.evidence_id
                for citation in result.report.evidence
            ),
            ("e" * 64,),
        )
        self.assertTrue(
            any(
                "recent_developments" in value
                and "(insufficient_evidence)" in value
                for value in result.report.limitations
            )
        )

    def test_e4_fixture_rejects_wrong_scope(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "requires comparison scope",
        ):
            e4_market_worker(
                request=SupervisorRequest(
                    request_text="Research AAPL.",
                    requested_symbols=("AAPL",),
                    mode="single_company",
                )
            )


    def test_e5_fixture_rejects_wrong_scope(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "requires single-company scope",
        ):
            e5_market_worker(
                request=SupervisorRequest(
                    request_text="Compare AAPL and MSFT.",
                    requested_symbols=("AAPL", "MSFT"),
                    mode="comparison",
                )
            )


if __name__ == "__main__":
    unittest.main()
