"""Offline tests for deterministic Supervisor final-report contracts."""

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
    assemble_supervisor_state,
    build_supervisor_plan,
    successful_worker_outcome,
)
from equity_research.supervisor_report import (  # noqa: E402
    SupervisorReportContractError,
    build_deterministic_supervisor_report,
    build_supervisor_report_context,
    validate_supervisor_report_output,
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


def _market_result(
    symbols: tuple[str, ...],
    *,
    omit_market_for: str | None = None,
    limitations: tuple[AgentLimitation, ...] = (),
) -> MarketAnalystResult:
    findings = []

    for symbol in symbols:
        if symbol != omit_market_for:
            findings.append(
                StructuredFinding(
                    finding_id=f"market_{symbol}",
                    dimension="market",
                    symbols=(symbol,),
                    statement=f"{symbol} market statement.",
                    metric_references=(
                        MetricReference(
                            dataset="market_metrics",
                            symbol=symbol,
                            as_of_date=date(2026, 9, 4),
                            fields=("return_20d", "close"),
                        ),
                    ),
                )
            )

        findings.append(
            StructuredFinding(
                finding_id=f"fundamental_{symbol}",
                dimension="fundamental",
                symbols=(symbol,),
                statement=f"{symbol} fundamental statement.",
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
            )
        )

    return MarketAnalystResult(
        findings=tuple(findings),
        limitations=limitations,
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
                finding_id=f"{symbol}:{topic}",
                topic=topic,
                characterization=characterization,
                symbols=(symbol,),
                statement=f"{symbol} {topic} statement.",
                evidence_ids=(
                    (
                        "a" * 64
                        if symbol == "AAPL"
                        else "b" * 64
                    ),
                ),
            )
            for symbol in symbols
        ),
        limitations=(),
    )


def _degraded_recent_result() -> CompanyResearcherResult:
    return CompanyResearcherResult(
        findings=(
            ResearchFinding(
                finding_id="AAPL:recent_developments",
                topic="recent_developments",
                characterization="development",
                symbols=("AAPL",),
                statement="AAPL recent_developments statement.",
                evidence_ids=("a" * 64,),
            ),
        ),
        limitations=(
            AgentLimitation(
                agent="company_researcher",
                symbol="MSFT",
                dimension="recent_developments",
                reason_code="insufficient_evidence",
                message="No grounded recent-development evidence for MSFT.",
            ),
        ),
    )


def _state(
    symbols: tuple[str, ...],
    *,
    market_result: MarketAnalystResult | None = None,
    recent_result: CompanyResearcherResult | None = None,
):
    plan = build_supervisor_plan(
        request_text=(
            "Research Apple."
            if len(symbols) == 1
            else "Compare Apple and Microsoft."
        ),
        requested_symbols=symbols,
        equities=EQUITIES,
    )

    return assemble_supervisor_state(
        plan=plan,
        outcomes=(
            successful_worker_outcome(
                route_id="market_analysis",
                result=(
                    market_result
                    if market_result is not None
                    else _market_result(symbols)
                ),
            ),
            successful_worker_outcome(
                route_id="recent_developments",
                result=(
                    recent_result
                    if recent_result is not None
                    else _company_result(
                        topic="recent_developments",
                        symbols=symbols,
                    )
                ),
            ),
            successful_worker_outcome(
                route_id="principal_risks",
                result=_company_result(
                    topic="principal_risks",
                    symbols=symbols,
                ),
            ),
        ),
    )


def _single_output():
    return {
        "sections": [
            {
                "section": "market_performance",
                "status": "available",
                "text": "Apple market performance summary.",
                "source_finding_ids": [
                    "market_analysis:market_AAPL",
                ],
            },
            {
                "section": "fundamental_performance",
                "status": "available",
                "text": "Apple fundamental performance summary.",
                "source_finding_ids": [
                    "market_analysis:fundamental_AAPL",
                ],
            },
            {
                "section": "recent_developments",
                "status": "available",
                "text": "Apple recent developments summary.",
                "source_finding_ids": [
                    "recent_developments:AAPL:recent_developments",
                ],
            },
            {
                "section": "principal_risks",
                "status": "available",
                "text": "Apple principal risks summary.",
                "source_finding_ids": [
                    "principal_risks:AAPL:principal_risks",
                ],
            },
        ],
        "limitations": [],
    }


def _comparison_output():
    return {
        "sections": [
            {
                "section": "market_performance",
                "status": "available",
                "text": "Apple and Microsoft market comparison.",
                "source_finding_ids": [
                    "market_analysis:market_AAPL",
                    "market_analysis:market_MSFT",
                ],
            },
            {
                "section": "fundamental_performance",
                "status": "available",
                "text": "Apple and Microsoft fundamental comparison.",
                "source_finding_ids": [
                    "market_analysis:fundamental_AAPL",
                    "market_analysis:fundamental_MSFT",
                ],
            },
            {
                "section": "recent_developments",
                "status": "available",
                "text": "Recent developments for both companies.",
                "source_finding_ids": [
                    "recent_developments:AAPL:recent_developments",
                    "recent_developments:MSFT:recent_developments",
                ],
            },
            {
                "section": "principal_risks",
                "status": "available",
                "text": "Principal risks for both companies.",
                "source_finding_ids": [
                    "principal_risks:AAPL:principal_risks",
                    "principal_risks:MSFT:principal_risks",
                ],
            },
            {
                "section": "comparative_assessment",
                "status": "available",
                "text": "Measured comparative assessment.",
                "source_finding_ids": [
                    "market_analysis:market_AAPL",
                    "market_analysis:market_MSFT",
                    "market_analysis:fundamental_AAPL",
                    "market_analysis:fundamental_MSFT",
                    "recent_developments:AAPL:recent_developments",
                    "recent_developments:MSFT:recent_developments",
                    "principal_risks:AAPL:principal_risks",
                    "principal_risks:MSFT:principal_risks",
                ],
            },
        ],
        "limitations": [],
    }


class SupervisorReportContextTests(unittest.TestCase):
    def test_context_exposes_route_qualified_worker_provenance(self) -> None:
        context = build_supervisor_report_context(
            _state(("AAPL",))
        )

        source_by_id = {
            item["source_finding_id"]: item
            for item in context["source_findings"]
        }

        self.assertIn(
            "market_analysis:market_AAPL",
            source_by_id,
        )
        self.assertEqual(
            source_by_id[
                "market_analysis:market_AAPL"
            ]["metric_references"],
            [
                "market_metrics:AAPL:2026-09-04:return_20d|close",
            ],
        )
        self.assertEqual(
            source_by_id[
                "recent_developments:AAPL:recent_developments"
            ]["evidence_ids"],
            ["a" * 64],
        )


class SupervisorReportValidationTests(unittest.TestCase):
    def test_accepts_valid_single_company_report(self) -> None:
        report = validate_supervisor_report_output(
            _single_output(),
            state=_state(("AAPL",)),
        )

        self.assertEqual(
            report.mode,
            "single_company",
        )
        self.assertEqual(
            len(report.sections),
            4,
        )
        self.assertEqual(
            tuple(
                citation.evidence_id
                for citation in report.evidence
            ),
            ("a" * 64,),
        )

    def test_accepts_valid_comparison_report(self) -> None:
        report = validate_supervisor_report_output(
            _comparison_output(),
            state=_state(("AAPL", "MSFT")),
        )

        self.assertEqual(
            report.mode,
            "comparison",
        )
        self.assertEqual(
            len(report.sections),
            5,
        )
        self.assertEqual(
            {
                citation.evidence_id
                for citation in report.evidence
            },
            {
                "a" * 64,
                "b" * 64,
            },
        )

    def test_degraded_comparison_excludes_incomplete_dimension(self) -> None:
        state = _state(
            ("AAPL", "MSFT"),
            recent_result=_degraded_recent_result(),
        )
        output = _comparison_output()
        output["sections"][2] = {
            "section": "recent_developments",
            "status": "degraded",
            "text": "AAPL has a grounded recent development; MSFT coverage is missing.",
            "source_finding_ids": [
                "recent_developments:AAPL:recent_developments",
            ],
        }
        output["sections"][4]["status"] = "degraded"
        output["sections"][4]["source_finding_ids"] = [
            "market_analysis:market_AAPL",
            "market_analysis:market_MSFT",
            "market_analysis:fundamental_AAPL",
            "market_analysis:fundamental_MSFT",
            "principal_risks:AAPL:principal_risks",
            "principal_risks:MSFT:principal_risks",
        ]
        output["limitations"] = [
            "MSFT recent-development evidence is unavailable.",
        ]

        report = validate_supervisor_report_output(
            output,
            state=state,
        )

        comparative = next(
            section
            for section in report.sections
            if section.section == "comparative_assessment"
        )
        self.assertNotIn(
            "recent_developments:AAPL:recent_developments",
            comparative.source_finding_ids,
        )

    def test_comparison_rejects_source_from_incomplete_dimension(self) -> None:
        state = _state(
            ("AAPL", "MSFT"),
            recent_result=_degraded_recent_result(),
        )
        output = _comparison_output()
        output["sections"][2] = {
            "section": "recent_developments",
            "status": "degraded",
            "text": "AAPL has a grounded recent development; MSFT coverage is missing.",
            "source_finding_ids": [
                "recent_developments:AAPL:recent_developments",
            ],
        }
        output["sections"][4]["status"] = "degraded"
        output["sections"][4]["source_finding_ids"] = [
            "market_analysis:market_AAPL",
            "market_analysis:market_MSFT",
            "market_analysis:fundamental_AAPL",
            "market_analysis:fundamental_MSFT",
            "recent_developments:AAPL:recent_developments",
            "principal_risks:AAPL:principal_risks",
            "principal_risks:MSFT:principal_risks",
        ]
        output["limitations"] = [
            "MSFT recent-development evidence is unavailable.",
        ]

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "lacks grounded coverage for every requested company",
        ):
            validate_supervisor_report_output(
                output,
                state=state,
            )

    def test_deterministic_comparison_omits_incomplete_dimension(self) -> None:
        report = build_deterministic_supervisor_report(
            _state(
                ("AAPL", "MSFT"),
                recent_result=_degraded_recent_result(),
            )
        )

        comparative = next(
            section
            for section in report.sections
            if section.section == "comparative_assessment"
        )
        self.assertEqual(
            comparative.status,
            "degraded",
        )
        self.assertNotIn(
            "recent_developments:AAPL:recent_developments",
            comparative.source_finding_ids,
        )
        self.assertNotIn(
            "Recent developments:",
            comparative.text,
        )

    def test_rejects_unknown_worker_finding_reference(self) -> None:
        output = _single_output()
        output["sections"][0]["source_finding_ids"] = [
            "market_analysis:not_real"
        ]

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "unknown worker findings",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL",)),
            )

    def test_rejects_wrong_source_class_for_market_section(self) -> None:
        output = _single_output()
        output["sections"][0]["source_finding_ids"] = [
            "recent_developments:AAPL:recent_developments"
        ]

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "market_performance may cite only",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL",)),
            )

    def test_rejects_duplicate_report_section(self) -> None:
        output = _single_output()
        output["sections"].append(
            dict(output["sections"][0])
        )

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "Duplicate report section",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL",)),
            )

    def test_single_company_rejects_comparative_assessment(self) -> None:
        output = _single_output()
        output["sections"].append(
            {
                "section": "comparative_assessment",
                "status": "available",
                "text": "Invalid comparison.",
                "source_finding_ids": [
                    "market_analysis:market_AAPL",
                ],
            }
        )

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "comparative_assessment",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL",)),
            )

    def test_comparison_requires_comparative_assessment(self) -> None:
        output = _comparison_output()
        output["sections"] = [
            section
            for section in output["sections"]
            if section["section"] != "comparative_assessment"
        ]

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "missing required sections",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL", "MSFT")),
            )

    def test_comparative_assessment_must_cover_both_companies(self) -> None:
        output = _comparison_output()
        output["sections"][-1]["source_finding_ids"] = [
            "market_analysis:market_AAPL",
        ]

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "covering both companies",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL", "MSFT")),
            )

    def test_available_section_requires_source_findings(self) -> None:
        output = _single_output()
        output["sections"][0]["source_finding_ids"] = []

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "requires source_finding_ids",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL",)),
            )

    def test_unavailable_section_rejects_source_findings(self) -> None:
        limitation = AgentLimitation(
            agent="market_analyst",
            symbol="AAPL",
            dimension="market",
            reason_code="stale",
            message="Market data is stale.",
        )
        state = _state(
            ("AAPL",),
            market_result=_market_result(
                ("AAPL",),
                omit_market_for="AAPL",
                limitations=(limitation,),
            ),
        )
        output = _single_output()
        output["sections"][0] = {
            "section": "market_performance",
            "status": "unavailable",
            "text": "Market performance unavailable because data is stale.",
            "source_finding_ids": [
                "market_analysis:fundamental_AAPL",
            ],
        }
        output["limitations"] = [
            "Market data is stale.",
        ]

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "must not cite findings",
        ):
            validate_supervisor_report_output(
                output,
                state=state,
            )

    def test_allows_unavailable_section_with_matching_limitation(self) -> None:
        limitation = AgentLimitation(
            agent="market_analyst",
            symbol="AAPL",
            dimension="market",
            reason_code="stale",
            message="Market data is stale.",
        )
        state = _state(
            ("AAPL",),
            market_result=_market_result(
                ("AAPL",),
                omit_market_for="AAPL",
                limitations=(limitation,),
            ),
        )
        output = _single_output()
        output["sections"][0] = {
            "section": "market_performance",
            "status": "unavailable",
            "text": "Market performance unavailable because data is stale.",
            "source_finding_ids": [],
        }
        output["limitations"] = [
            "Market data is stale.",
        ]

        report = validate_supervisor_report_output(
            output,
            state=state,
        )

        self.assertEqual(
            report.status,
            "degraded",
        )
        self.assertEqual(
            report.sections[0].status,
            "unavailable",
        )

    def test_rejects_unavailable_section_without_matching_limitation(self) -> None:
        output = _single_output()
        output["sections"][0] = {
            "section": "market_performance",
            "status": "unavailable",
            "text": "Market unavailable.",
            "source_finding_ids": [],
        }

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "cannot be unavailable",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL",)),
            )

    def test_degraded_report_requires_explicit_report_limitation(self) -> None:
        limitation = AgentLimitation(
            agent="market_analyst",
            symbol="AAPL",
            dimension="market",
            reason_code="stale",
            message="Market data is stale.",
        )
        state = _state(
            ("AAPL",),
            market_result=_market_result(
                ("AAPL",),
                omit_market_for="AAPL",
                limitations=(limitation,),
            ),
        )
        output = _single_output()
        output["sections"][0] = {
            "section": "market_performance",
            "status": "unavailable",
            "text": "Market performance unavailable.",
            "source_finding_ids": [],
        }

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "require explicit limitations",
        ):
            validate_supervisor_report_output(
                output,
                state=state,
            )

    def test_allows_degraded_comparison_section_with_partial_findings(
        self,
    ) -> None:
        limitation = AgentLimitation(
            agent="company_researcher",
            symbol="MSFT",
            dimension="recent_developments",
            reason_code="insufficient_evidence",
            message="No company-specific MSFT developments were found.",
        )
        aapl_recent = _company_result(
            topic="recent_developments",
            symbols=("AAPL",),
        )
        recent_result = CompanyResearcherResult(
            findings=aapl_recent.findings,
            limitations=(limitation,),
        )
        state = _state(
            ("AAPL", "MSFT"),
            recent_result=recent_result,
        )
        output = _comparison_output()

        recent_section = output["sections"][2]
        recent_section["status"] = "degraded"
        recent_section["text"] = (
            "Apple has a grounded recent development; MSFT is unavailable."
        )
        recent_section["source_finding_ids"] = [
            "recent_developments:AAPL:recent_developments",
        ]

        comparative = output["sections"][-1]
        comparative["status"] = "degraded"
        comparative["source_finding_ids"] = [
            source_id
            for source_id in comparative["source_finding_ids"]
            if source_id != "recent_developments:MSFT:recent_developments"
        ]
        output["limitations"] = [
            "MSFT recent developments are unavailable because evidence is "
            "insufficient.",
        ]

        report = validate_supervisor_report_output(
            output,
            state=state,
        )

        self.assertEqual(
            report.status,
            "degraded",
        )
        self.assertEqual(
            report.sections[2].status,
            "degraded",
        )
        self.assertIn(
            "a" * 64,
            {
                citation.evidence_id
                for citation in report.evidence
            },
        )

    def test_rejects_unavailable_section_when_grounded_findings_remain(
        self,
    ) -> None:
        limitation = AgentLimitation(
            agent="company_researcher",
            symbol="MSFT",
            dimension="recent_developments",
            reason_code="insufficient_evidence",
            message="No company-specific MSFT developments were found.",
        )
        aapl_recent = _company_result(
            topic="recent_developments",
            symbols=("AAPL",),
        )
        state = _state(
            ("AAPL", "MSFT"),
            recent_result=CompanyResearcherResult(
                findings=aapl_recent.findings,
                limitations=(limitation,),
            ),
        )
        output = _comparison_output()
        output["sections"][2] = {
            "section": "recent_developments",
            "status": "unavailable",
            "text": "Recent developments unavailable.",
            "source_finding_ids": [],
        }
        output["sections"][-1]["status"] = "degraded"
        output["sections"][-1]["source_finding_ids"] = [
            source_id
            for source_id in output["sections"][-1]["source_finding_ids"]
            if source_id != "recent_developments:MSFT:recent_developments"
        ]
        output["limitations"] = [
            "MSFT recent developments are unavailable.",
        ]

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "cannot be unavailable while grounded worker findings remain",
        ):
            validate_supervisor_report_output(
                output,
                state=state,
            )

    def test_comparative_assessment_inherits_grounded_section_sources(
        self,
    ) -> None:
        output = _comparison_output()
        output["sections"][-1]["source_finding_ids"].remove(
            "recent_developments:AAPL:recent_developments"
        )

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "must inherit source_finding_ids",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL", "MSFT")),
            )

    def test_deterministic_fallback_preserves_degraded_comparison_provenance(
        self,
    ) -> None:
        limitation = AgentLimitation(
            agent="company_researcher",
            symbol="MSFT",
            dimension="recent_developments",
            reason_code="insufficient_evidence",
            message="No company-specific MSFT developments were found.",
        )
        aapl_recent = _company_result(
            topic="recent_developments",
            symbols=("AAPL",),
        )
        state = _state(
            ("AAPL", "MSFT"),
            recent_result=CompanyResearcherResult(
                findings=aapl_recent.findings,
                limitations=(limitation,),
            ),
        )

        report = build_deterministic_supervisor_report(
            state
        )

        self.assertEqual(
            report.status,
            "degraded",
        )
        self.assertEqual(
            report.synthesis_mode,
            "deterministic_fallback",
        )
        recent = next(
            section
            for section in report.sections
            if section.section == "recent_developments"
        )
        comparative = next(
            section
            for section in report.sections
            if section.section == "comparative_assessment"
        )
        self.assertEqual(
            recent.status,
            "degraded",
        )
        self.assertEqual(
            recent.source_finding_ids,
            (
                "recent_developments:AAPL:recent_developments",
            ),
        )
        self.assertIn(
            "recent_developments:AAPL:recent_developments",
            comparative.source_finding_ids,
        )
        self.assertIn(
            "a" * 64,
            {
                citation.evidence_id
                for citation in report.evidence
            },
        )
        self.assertTrue(
            report.limitations
        )

    def test_rejects_unbacked_qualitative_assessment(self) -> None:
        output = _comparison_output()
        output["sections"][-1]["text"] = (
            "Both companies posted strong financial results."
        )

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "unsupported comparative relation 'strong'",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL", "MSFT")),
            )

    def test_rejects_unbacked_comparative_relation(self) -> None:
        output = _comparison_output()
        output["sections"][-1]["text"] = (
            "Apple assets are larger than Microsoft's."
        )

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "unsupported comparative relation 'larger'",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL", "MSFT")),
            )

    def test_accepts_numeric_claim_copied_from_cited_worker_finding(
        self,
    ) -> None:
        market_result = MarketAnalystResult(
            findings=(
                StructuredFinding(
                    finding_id="market_AAPL",
                    dimension="market",
                    symbols=("AAPL",),
                    statement="AAPL market statement.",
                    metric_references=(
                        MetricReference(
                            dataset="market_metrics",
                            symbol="AAPL",
                            as_of_date=date(2026, 9, 4),
                            fields=("return_20d", "close"),
                        ),
                    ),
                ),
                StructuredFinding(
                    finding_id="fundamental_AAPL",
                    dimension="fundamental",
                    symbols=("AAPL",),
                    statement=(
                        "Apple reported trailing-12-month net income of "
                        "$128.9 billion."
                    ),
                    metric_references=(
                        MetricReference(
                            dataset="fundamental_metrics",
                            symbol="AAPL",
                            as_of_date=date(2026, 7, 31),
                            fields=("net_income_ttm",),
                        ),
                    ),
                ),
            ),
            limitations=(),
        )
        state = _state(
            ("AAPL",),
            market_result=market_result,
        )
        output = _single_output()
        output["sections"][1]["text"] = (
            "Apple reported TTM net income of $128.9 billion."
        )

        report = validate_supervisor_report_output(
            output,
            state=state,
        )

        self.assertEqual(
            report.sections[1].status,
            "available",
        )

    def test_rejects_final_report_numeric_decimal_place_shift(
        self,
    ) -> None:
        market_result = MarketAnalystResult(
            findings=(
                StructuredFinding(
                    finding_id="market_AAPL",
                    dimension="market",
                    symbols=("AAPL",),
                    statement="AAPL market statement.",
                    metric_references=(
                        MetricReference(
                            dataset="market_metrics",
                            symbol="AAPL",
                            as_of_date=date(2026, 9, 4),
                            fields=("return_20d", "close"),
                        ),
                    ),
                ),
                StructuredFinding(
                    finding_id="fundamental_AAPL",
                    dimension="fundamental",
                    symbols=("AAPL",),
                    statement=(
                        "Apple reported trailing-12-month net income of "
                        "$128.9 billion."
                    ),
                    metric_references=(
                        MetricReference(
                            dataset="fundamental_metrics",
                            symbol="AAPL",
                            as_of_date=date(2026, 7, 31),
                            fields=("net_income_ttm",),
                        ),
                    ),
                ),
            ),
            limitations=(),
        )
        state = _state(
            ("AAPL",),
            market_result=market_result,
        )
        output = _single_output()
        output["sections"][1]["text"] = (
            "Apple reported TTM net income of $12.89 billion."
        )

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "numerical claims absent from cited worker findings",
        ):
            validate_supervisor_report_output(
                output,
                state=state,
            )

    def test_rejects_unknown_top_level_field(self) -> None:
        output = _single_output()
        output["extra"] = "not allowed"

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "unknown fields",
        ):
            validate_supervisor_report_output(
                output,
                state=_state(("AAPL",)),
            )


if __name__ == "__main__":
    unittest.main()
