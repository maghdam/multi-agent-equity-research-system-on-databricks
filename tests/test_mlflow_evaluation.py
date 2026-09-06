"""Offline tests for MLflow Supervisor-report evaluation helpers."""

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.mlflow_evaluation import (  # noqa: E402
    EQUITY_RESEARCH_GUIDELINES,
    build_code_scorers,
    build_live_evaluation_data,
    build_evaluation_scorers,
    build_llm_judges,
    evidence_count,
    expected_request_mode,
    expected_symbol_scope,
    report_section_grounding_contract,
    report_status,
    required_report_sections,
    serialize_supervisor_report_for_evaluation,
    synthesis_mode,
)
from equity_research.supervisor_report import (  # noqa: E402
    EvidenceCitation,
    ReportSection,
    SupervisorReport,
)


def _report() -> SupervisorReport:
    return SupervisorReport(
        mode="single_company",
        symbols=("AAPL",),
        status="ready",
        sections=(
            ReportSection(
                section="market_performance",
                status="available",
                text="Apple market performance.",
                source_finding_ids=("market_analysis:m1",),
            ),
            ReportSection(
                section="fundamental_performance",
                status="available",
                text="Apple fundamentals.",
                source_finding_ids=("market_analysis:f1",),
            ),
            ReportSection(
                section="recent_developments",
                status="available",
                text="Apple recent development.",
                source_finding_ids=("recent_developments:d1",),
            ),
            ReportSection(
                section="principal_risks",
                status="available",
                text="Apple principal risk.",
                source_finding_ids=("principal_risks:r1",),
            ),
        ),
        limitations=(),
        evidence=(
            EvidenceCitation(
                evidence_id="a" * 64,
                source_finding_ids=("recent_developments:d1",),
            ),
            EvidenceCitation(
                evidence_id="b" * 64,
                source_finding_ids=("principal_risks:r1",),
            ),
        ),
        synthesis_mode="model",
    )


def _expectations() -> dict:
    return {
        "expected_mode": "single_company",
        "expected_symbols": ["AAPL"],
        "required_sections": [
            "market_performance",
            "fundamental_performance",
            "recent_developments",
            "principal_risks",
        ],
    }


class MlflowEvaluationCaseTests(unittest.TestCase):
    def test_builds_frozen_e1_and_e2_rows(self) -> None:
        rows = build_live_evaluation_data(
            ("E1", "E2")
        )

        self.assertEqual(
            len(rows),
            2,
        )
        self.assertEqual(
            rows[0]["inputs"]["requested_symbols"],
            ["AAPL"],
        )
        self.assertEqual(
            rows[0]["expectations"]["expected_mode"],
            "single_company",
        )
        self.assertEqual(
            rows[1]["inputs"]["requested_symbols"],
            ["AAPL", "MSFT"],
        )
        self.assertEqual(
            rows[1]["expectations"]["expected_mode"],
            "comparison",
        )
        self.assertEqual(
            rows[1]["expectations"]["required_sections"][-1],
            "comparative_assessment",
        )

    def test_rejects_unsupported_or_duplicate_live_case_ids(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Supported live cases are E1 and E2",
        ):
            build_live_evaluation_data(
                ("E3",)
            )

        with self.assertRaisesRegex(
            ValueError,
            "must be unique",
        ):
            build_live_evaluation_data(
                ("E1", "e1")
            )


class MlflowEvaluationSerializationTests(unittest.TestCase):
    def test_serializes_validated_report_to_json_safe_output(self) -> None:
        output = serialize_supervisor_report_for_evaluation(
            _report()
        )

        self.assertEqual(
            output["mode"],
            "single_company",
        )
        self.assertEqual(
            output["symbols"],
            ["AAPL"],
        )
        self.assertEqual(
            output["status"],
            "ready",
        )
        self.assertEqual(
            output["synthesis_mode"],
            "model",
        )
        self.assertEqual(
            output["evidence_count"],
            2,
        )
        self.assertEqual(
            output["evidence_ids"],
            [
                "a" * 64,
                "b" * 64,
            ],
        )
        self.assertIn(
            "market_performance [available]",
            output["report_text"],
        )
        self.assertIn(
            "principal_risks [available]",
            output["report_text"],
        )

    def test_serializer_rejects_non_report(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "report must be SupervisorReport",
        ):
            serialize_supervisor_report_for_evaluation(
                object()  # type: ignore[arg-type]
            )


class MlflowCodeScorerTests(unittest.TestCase):
    def test_exact_mode_symbol_and_section_scorers_pass(self) -> None:
        output = serialize_supervisor_report_for_evaluation(
            _report()
        )
        expectations = _expectations()

        self.assertTrue(
            expected_request_mode(
                outputs=output,
                expectations=expectations,
            ).value
        )
        self.assertTrue(
            expected_symbol_scope(
                outputs=output,
                expectations=expectations,
            ).value
        )
        self.assertTrue(
            required_report_sections(
                outputs=output,
                expectations=expectations,
            ).value
        )

    def test_scope_scorer_rejects_wrong_symbol(self) -> None:
        output = serialize_supervisor_report_for_evaluation(
            _report()
        )
        expectations = _expectations()
        expectations["expected_symbols"] = ["MSFT"]

        self.assertFalse(
            expected_symbol_scope(
                outputs=output,
                expectations=expectations,
            ).value
        )

    def test_section_grounding_scorer_rejects_available_without_sources(
        self,
    ) -> None:
        output = serialize_supervisor_report_for_evaluation(
            _report()
        )
        output["sections"][0]["source_finding_ids"] = []

        self.assertFalse(
            report_section_grounding_contract(
                outputs=output
            ).value
        )

    def test_status_mode_and_evidence_scorers_expose_observability_values(
        self,
    ) -> None:
        output = serialize_supervisor_report_for_evaluation(
            _report()
        )

        self.assertEqual(
            synthesis_mode(
                outputs=output
            ).value,
            "model",
        )
        self.assertEqual(
            report_status(
                outputs=output
            ).value,
            "ready",
        )
        self.assertEqual(
            evidence_count(
                outputs=output
            ).value,
            2,
        )

    def test_code_scorer_set_is_stable(self) -> None:
        scorers = build_code_scorers()

        self.assertEqual(
            [value.name for value in scorers],
            [
                "expected_request_mode",
                "expected_symbol_scope",
                "required_report_sections",
                "report_section_grounding_contract",
                "synthesis_mode",
                "report_status",
                "evidence_count",
            ],
        )


class MlflowJudgeConfigurationTests(unittest.TestCase):
    def test_builds_databricks_semantic_judges(self) -> None:
        judges = build_llm_judges(
            model="databricks"
        )

        self.assertEqual(
            [judge.name for judge in judges],
            [
                "relevance_to_query",
                "safety",
                "equity_research_guidelines",
            ],
        )
        self.assertTrue(
            all(
                judge.model == "databricks"
                for judge in judges
            )
        )
        self.assertGreaterEqual(
            len(EQUITY_RESEARCH_GUIDELINES),
            5,
        )

    def test_combined_scorers_can_exclude_or_include_llm_judges(self) -> None:
        code_only = build_evaluation_scorers(
            include_llm_judges=False
        )
        combined = build_evaluation_scorers(
            include_llm_judges=True,
            judge_model="databricks",
        )

        self.assertEqual(
            len(code_only),
            7,
        )
        self.assertEqual(
            len(combined),
            10,
        )

    def test_rejects_blank_judge_model(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "model must be a nonblank string",
        ):
            build_llm_judges(
                model=" "
            )


if __name__ == "__main__":
    unittest.main()
