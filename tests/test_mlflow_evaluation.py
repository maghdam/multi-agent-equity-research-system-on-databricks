"""Offline tests for MLflow Supervisor-report evaluation helpers."""

import builtins
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.mlflow_evaluation import (  # noqa: E402
    EQUITY_RESEARCH_GUIDELINES,
    build_code_scorers,
    _narrative_grounding_payload,
    _run_grounding_guidelines_with_parse_retry,
    build_live_evaluation_data,
    build_narrative_trace_grounding_judge,
    build_evaluation_scorers,
    build_llm_judges,
    build_scope_rejection_scorers,
    evidence_count,
    expected_request_mode,
    expected_scope_rejection,
    expected_symbol_scope,
    no_downstream_execution,
    report_section_grounding_contract,
    report_status,
    require_managed_evaluation_dataset_runtime,
    required_report_sections,
    serialize_scope_rejection_for_evaluation,
    serialize_supervisor_report_for_evaluation,
    summarize_observability_spans,
    summarize_trace_assessments,
    supported_universe_disclosure,
    synthesis_mode,
)
from equity_research.supervisor_report import (  # noqa: E402
    EvidenceCitation,
    ReportSection,
    SupervisorReport,
)
from equity_research.tool_scope import ControlledToolRequestError  # noqa: E402


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


class ManagedEvaluationDatasetRuntimeTests(unittest.TestCase):
    def test_missing_optional_runtime_has_actionable_error(self) -> None:
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "databricks.agents.datasets":
                raise ImportError(
                    "synthetic missing databricks-agents"
                )
            return real_import(
                name,
                *args,
                **kwargs,
            )

        from unittest.mock import patch

        with patch(
            "builtins.__import__",
            side_effect=fake_import,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "requirements-evaluation-dataset.txt",
            ):
                require_managed_evaluation_dataset_runtime()


class MlflowAssessmentSummaryTests(unittest.TestCase):
    def test_summarizes_feedback_without_trace_payloads(self) -> None:
        assessments = [
            SimpleNamespace(
                name="guideline_evidence_grounded_narrative",
                value=False,
                rationale="The report makes one unsupported narrative claim.",
                error=None,
            ),
            SimpleNamespace(
                name="safety",
                value=True,
                rationale="No unsafe content.",
                error=None,
            ),
        ]

        summaries = summarize_trace_assessments(
            assessments
        )

        self.assertEqual(
            summaries,
            [
                {
                    "name": "guideline_evidence_grounded_narrative",
                    "value": False,
                    "rationale": (
                        "The report makes one unsupported narrative claim."
                    ),
                    "error": None,
                },
                {
                    "name": "safety",
                    "value": True,
                    "rationale": "No unsafe content.",
                    "error": None,
                },
            ],
        )

    def test_summarizes_serialized_mapping_assessment(self) -> None:
        summaries = summarize_trace_assessments(
            [
                {
                    "name": "guideline_evidence_grounded_narrative",
                    "value": False,
                    "rationale": "Serialized rationale.",
                    "error": {
                        "error_message": "Serialized error."
                    },
                }
            ]
        )

        self.assertEqual(
            summaries,
            [
                {
                    "name": "guideline_evidence_grounded_narrative",
                    "value": False,
                    "rationale": "Serialized rationale.",
                    "error": "Serialized error.",
                }
            ],
        )

    def test_summarizes_assessment_error_message(self) -> None:
        assessments = [
            SimpleNamespace(
                name="judge",
                value=None,
                rationale=None,
                error=SimpleNamespace(
                    error_message="judge unavailable"
                ),
            )
        ]

        summaries = summarize_trace_assessments(
            assessments
        )

        self.assertEqual(
            summaries[0]["error"],
            "judge unavailable",
        )

    def test_scope_rejection_span_is_in_observability_summary(
        self,
    ) -> None:
        attributes = {
            "mlflow.spanType": "AGENT",
            "equity_research.component": "scope_validation",
            "equity_research.request_mode": "unsupported_scope",
            "equity_research.rejection_reason": "unsupported_symbol",
            "equity_research.unsupported_symbol_count": 1,
        }
        span = SimpleNamespace(
            name="supervisor_scope_validation",
            get_attribute=lambda key: attributes.get(key),
        )

        summaries = summarize_observability_spans(
            [span]
        )

        self.assertEqual(
            len(summaries),
            1,
        )
        self.assertEqual(
            summaries[0]["name"],
            "supervisor_scope_validation",
        )
        self.assertEqual(
            summaries[0]["request_mode"],
            "unsupported_scope",
        )
        self.assertEqual(
            summaries[0]["rejection_reason"],
            "unsupported_symbol",
        )
        self.assertEqual(
            summaries[0]["unsupported_symbol_count"],
            1,
        )

    def test_observability_span_summary_is_whitelisted_and_privacy_safe(
        self,
    ) -> None:
        attributes = {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "system.ai.gpt-oss-20b",
            "mlflow.chat.tokenUsage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
            "equity_research.component": "market_analyst",
            "equity_research.attempt": "initial",
            "private_payload": "must-not-appear",
        }
        included = SimpleNamespace(
            name="market_analyst_20b_initial",
            get_attribute=lambda key: attributes.get(key),
            inputs={
                "messages": "must-not-appear",
            },
            outputs={
                "raw_text": "must-not-appear",
            },
        )
        ignored = SimpleNamespace(
            name="langgraph_internal_node",
            get_attribute=lambda key: attributes.get(key),
        )

        summaries = summarize_observability_spans(
            [
                included,
                ignored,
            ]
        )

        self.assertEqual(
            len(summaries),
            1,
        )
        self.assertEqual(
            summaries[0]["name"],
            "market_analyst_20b_initial",
        )
        self.assertEqual(
            summaries[0]["token_usage"]["total_tokens"],
            15,
        )
        self.assertEqual(
            summaries[0]["attempt"],
            "initial",
        )
        self.assertNotIn(
            "private_payload",
            str(summaries),
        )
        self.assertNotIn(
            "must-not-appear",
            str(summaries),
        )


class MlflowEvaluationCaseTests(unittest.TestCase):
    def test_builds_frozen_e1_e2_and_e3_rows(self) -> None:
        rows = build_live_evaluation_data(
            ("E1", "E2", "E3")
        )

        self.assertEqual(
            len(rows),
            3,
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
            rows[0]["tags"],
            {
                "case_id": "E1",
                "category": "grounded_single_company",
                "source": "ai_research_contract",
            },
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
        self.assertEqual(
            rows[2]["inputs"]["requested_symbols"],
            ["AAPL", "NVDA"],
        )
        self.assertEqual(
            rows[2]["tags"]["category"],
            "unsupported_scope_rejection",
        )
        self.assertEqual(
            rows[2]["expectations"],
            {
                "expected_rejection_reason": "unsupported_symbol",
                "expected_requested_symbols": ["AAPL", "NVDA"],
                "expected_unsupported_symbols": ["NVDA"],
                "expected_supported_symbols": ["AAPL", "MSFT"],
            },
        )

    def test_rejects_unsupported_or_duplicate_live_case_ids(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Supported live cases are E1, E2, and E3",
        ):
            build_live_evaluation_data(
                ("E4",)
            )

        with self.assertRaisesRegex(
            ValueError,
            "must be unique",
        ):
            build_live_evaluation_data(
                ("E1", "e1")
            )


class MlflowScopeRejectionTests(unittest.TestCase):
    def test_serializes_e3_without_copying_exception_message(self) -> None:
        secret = "provider text that must not be copied"
        output = serialize_scope_rejection_for_evaluation(
            requested_symbols=("AAPL", "NVDA"),
            supported_symbols=("MSFT", "AAPL"),
            error=ControlledToolRequestError(
                secret
            ),
            downstream_calls={
                "market_worker": 0,
                "company_worker": 0,
                "report_synthesizer": 0,
            },
        )

        self.assertEqual(
            output,
            {
                "outcome": "rejected",
                "reason_code": "unsupported_symbol",
                "error_type": "ControlledToolRequestError",
                "requested_symbols": ["AAPL", "NVDA"],
                "unsupported_symbols": ["NVDA"],
                "supported_symbols": ["AAPL", "MSFT"],
                "downstream_calls": {
                    "company_worker": 0,
                    "market_worker": 0,
                    "report_synthesizer": 0,
                },
            },
        )
        self.assertNotIn(
            secret,
            str(output),
        )

    def test_e3_scope_rejection_scorers_pass_exact_contract(self) -> None:
        output = serialize_scope_rejection_for_evaluation(
            requested_symbols=("AAPL", "NVDA"),
            supported_symbols=("AAPL", "MSFT"),
            error=ControlledToolRequestError(
                "Unsupported symbol."
            ),
            downstream_calls={
                "market_worker": 0,
                "company_worker": 0,
                "report_synthesizer": 0,
            },
        )
        expectations = build_live_evaluation_data(
            ("E3",)
        )[0]["expectations"]

        self.assertTrue(
            expected_scope_rejection(
                outputs=output,
                expectations=expectations,
            )
        )
        self.assertTrue(
            supported_universe_disclosure(
                outputs=output,
                expectations=expectations,
            )
        )
        self.assertTrue(
            no_downstream_execution(
                outputs=output
            )
        )
        self.assertEqual(
            [
                scorer.name
                for scorer in build_scope_rejection_scorers()
            ],
            [
                "expected_scope_rejection",
                "supported_universe_disclosure",
                "no_downstream_execution",
            ],
        )

    def test_e3_no_downstream_execution_fails_on_any_boundary_call(
        self,
    ) -> None:
        output = serialize_scope_rejection_for_evaluation(
            requested_symbols=("AAPL", "NVDA"),
            supported_symbols=("AAPL", "MSFT"),
            error=ControlledToolRequestError(
                "Unsupported symbol."
            ),
            downstream_calls={
                "market_worker": 1,
                "company_worker": 0,
                "report_synthesizer": 0,
            },
        )

        self.assertFalse(
            no_downstream_execution(
                outputs=output
            )
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
            )
        )
        self.assertTrue(
            expected_symbol_scope(
                outputs=output,
                expectations=expectations,
            )
        )
        self.assertTrue(
            required_report_sections(
                outputs=output,
                expectations=expectations,
            )
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
            )
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
            )
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
            ),
            "model",
        )
        self.assertEqual(
            report_status(
                outputs=output
            ),
            "ready",
        )
        self.assertEqual(
            evidence_count(
                outputs=output
            ),
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
            model="databricks:/databricks-gpt-oss-120b"
        )

        self.assertEqual(
            [judge.name for judge in judges],
            [
                "relevance_to_query",
                "safety",
                "narrative_trace_groundedness",
                "guideline_no_investment_recommendation",
                "guideline_market_fundamental_separation",
                "guideline_evidence_grounded_narrative",
                "guideline_coverage_limitations",
                "guideline_bounded_comparison",
            ],
        )
        self.assertTrue(
            all(
                getattr(
                    judge,
                    "model",
                    "databricks:/databricks-gpt-oss-120b",
                )
                == "databricks:/databricks-gpt-oss-120b"
                for judge in judges
            )
        )
        self.assertGreaterEqual(
            len(EQUITY_RESEARCH_GUIDELINES),
            5,
        )

    def test_builds_trace_aware_narrative_grounding_judge(self) -> None:
        judge = build_narrative_trace_grounding_judge(
            model="databricks:/databricks-gpt-oss-120b"
        )

        self.assertEqual(
            judge.name,
            "narrative_trace_groundedness",
        )

    def test_narrative_grounding_payload_uses_only_cited_retrieval_evidence(
        self,
    ) -> None:
        output = serialize_supervisor_report_for_evaluation(
            _report()
        )
        trace = Mock()
        trace.search_spans.return_value = [
            SimpleNamespace(
                outputs=[
                    {
                        "id": "a" * 64,
                        "page_content": "Apple launched a new product.",
                        "metadata": {
                            "source_type": "news",
                            "configured_symbols": ["AAPL"],
                            "evidence_date": "2026-08-30",
                        },
                    },
                    {
                        "id": "c" * 64,
                        "page_content": "Uncited retrieved text.",
                        "metadata": {
                            "source_type": "news",
                            "configured_symbols": ["AAPL"],
                            "evidence_date": "2026-08-29",
                        },
                    },
                ]
            ),
            SimpleNamespace(
                outputs=[
                    {
                        "id": "b" * 64,
                        "page_content": "Apple disclosed a principal risk.",
                        "metadata": {
                            "source_type": "filing",
                            "configured_symbols": ["AAPL"],
                            "evidence_date": "2026-07-31",
                        },
                    }
                ]
            ),
        ]

        judge_inputs, judge_outputs = _narrative_grounding_payload(
            outputs=output,
            trace=trace,
        )

        self.assertEqual(
            [
                item["evidence_id"]
                for item in judge_inputs["retrieved_evidence"]
            ],
            [
                "a" * 64,
                "b" * 64,
            ],
        )
        self.assertEqual(
            [
                item["section"]
                for item in judge_outputs["narrative_sections"]
            ],
            [
                "recent_developments",
                "principal_risks",
            ],
        )
        self.assertNotIn(
            "market_performance",
            str(judge_outputs),
        )

    def test_narrative_grounding_retries_one_parse_failure(self) -> None:
        judge = Mock(
            side_effect=[
                RuntimeError(
                    "Failed to parse response from judge model. Response:"
                ),
                SimpleNamespace(
                    value="yes",
                    rationale="Grounded after bounded retry.",
                ),
            ]
        )

        feedback = _run_grounding_guidelines_with_parse_retry(
            judge,
            inputs={
                "retrieved_evidence": [],
            },
            outputs={
                "narrative_sections": [],
                "limitations": [],
            },
        )

        self.assertEqual(
            judge.call_count,
            2,
        )
        self.assertEqual(
            feedback.value,
            "yes",
        )

    def test_narrative_grounding_does_not_retry_nonparse_failure(self) -> None:
        judge = Mock(
            side_effect=RuntimeError(
                "judge service unavailable"
            )
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "judge service unavailable",
        ):
            _run_grounding_guidelines_with_parse_retry(
                judge,
                inputs={
                    "retrieved_evidence": [],
                },
                outputs={
                    "narrative_sections": [],
                    "limitations": [],
                },
            )

        self.assertEqual(
            judge.call_count,
            1,
        )

    def test_combined_scorers_can_exclude_or_include_llm_judges(self) -> None:
        code_only = build_evaluation_scorers(
            include_llm_judges=False
        )
        combined = build_evaluation_scorers(
            include_llm_judges=True,
            judge_model="databricks:/databricks-gpt-oss-120b",
        )

        self.assertEqual(
            len(code_only),
            7,
        )
        self.assertEqual(
            len(combined),
            15,
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
