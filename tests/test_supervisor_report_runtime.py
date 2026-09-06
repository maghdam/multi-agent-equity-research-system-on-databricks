"""Offline tests for GPT OSS 120B Supervisor final synthesis runtime."""

import json
import sys
import unittest
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch


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
    assemble_supervisor_state,
    build_supervisor_plan,
    successful_worker_outcome,
)
from equity_research.supervisor_report import (  # noqa: E402
    SupervisorReportContractError,
    build_supervisor_report_context,
)
from equity_research.supervisor_report_prompts import (  # noqa: E402
    SUPERVISOR_MAX_TOKENS,
    SUPERVISOR_MODEL,
    SUPERVISOR_REASONING_EFFORT,
    SUPERVISOR_REPORT_RESPONSE_FORMAT,
    build_supervisor_report_model_request,
    build_supervisor_report_repair_request,
)
from equity_research.supervisor_report_runtime import (  # noqa: E402
    run_supervisor_report_synthesis,
)
from equity_research.worker_agent_runtime import (  # noqa: E402
    AgentModelResponseError,
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


def _state(
    symbols: tuple[str, ...] = ("AAPL",),
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

    market_findings = []
    development_findings = []
    risk_findings = []

    for symbol in symbols:
        market_findings.extend(
            [
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
                            fields=("return_20d",),
                        ),
                    ),
                ),
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
                ),
            ]
        )
        evidence_id = (
            "a" * 64
            if symbol == "AAPL"
            else "b" * 64
        )
        development_findings.append(
            ResearchFinding(
                finding_id=f"{symbol}:development",
                topic="recent_developments",
                characterization="development",
                symbols=(symbol,),
                statement=f"{symbol} development statement.",
                evidence_ids=(evidence_id,),
            )
        )
        risk_findings.append(
            ResearchFinding(
                finding_id=f"{symbol}:risk",
                topic="principal_risks",
                characterization="company_disclosed_risk",
                symbols=(symbol,),
                statement=f"{symbol} risk statement.",
                evidence_ids=(evidence_id,),
            )
        )

    return assemble_supervisor_state(
        plan=plan,
        outcomes=(
            successful_worker_outcome(
                route_id="market_analysis",
                result=MarketAnalystResult(
                    findings=tuple(market_findings),
                    limitations=(),
                ),
            ),
            successful_worker_outcome(
                route_id="recent_developments",
                result=CompanyResearcherResult(
                    findings=tuple(development_findings),
                    limitations=(),
                ),
            ),
            successful_worker_outcome(
                route_id="principal_risks",
                result=CompanyResearcherResult(
                    findings=tuple(risk_findings),
                    limitations=(),
                ),
            ),
        ),
    )


def _single_report_output():
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
                    "recent_developments:AAPL:development",
                ],
            },
            {
                "section": "principal_risks",
                "status": "available",
                "text": "Apple principal risks summary.",
                "source_finding_ids": [
                    "principal_risks:AAPL:risk",
                ],
            },
        ],
        "limitations": [],
    }


def _chat_response(
    output,
    *,
    reasoning_block: bool = False,
):
    text = json.dumps(
        output,
        separators=(",", ":"),
    )
    content = text

    if reasoning_block:
        content = [
            {
                "type": "reasoning",
                "reasoning": "hidden reasoning",
            },
            {
                "type": "text",
                "text": text,
            },
        ]

    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": content,
                },
            }
        ]
    }


class SupervisorReportPromptTests(unittest.TestCase):
    def test_builds_exact_controlled_120b_request(self) -> None:
        context = build_supervisor_report_context(
            _state()
        )

        payload = build_supervisor_report_model_request(
            context
        )

        self.assertEqual(
            payload["model"],
            "system.ai.gpt-oss-120b",
        )
        self.assertEqual(
            SUPERVISOR_MODEL,
            "system.ai.gpt-oss-120b",
        )
        self.assertEqual(
            payload["reasoning_effort"],
            "medium",
        )
        self.assertEqual(
            SUPERVISOR_REASONING_EFFORT,
            "medium",
        )
        self.assertEqual(
            payload["max_tokens"],
            SUPERVISOR_MAX_TOKENS,
        )
        self.assertEqual(
            payload["temperature"],
            0,
        )
        self.assertIs(
            payload["stream"],
            False,
        )
        self.assertEqual(
            payload["response_format"],
            SUPERVISOR_REPORT_RESPONSE_FORMAT,
        )
        self.assertTrue(
            payload["response_format"]["json_schema"]["strict"]
        )

        user_content = payload["messages"][1]["content"]
        self.assertIn(
            '"source_finding_id":"market_analysis:market_AAPL"',
            user_content,
        )
        self.assertIn(
            '"evidence_ids":',
            user_content,
        )

    def test_supervisor_prompt_forbids_unbacked_comparative_inference(
        self,
    ) -> None:
        payload = build_supervisor_report_model_request(
            build_supervisor_report_context(
                _state(("AAPL", "MSFT"))
            )
        )
        system_message = payload["messages"][0]["content"]

        for phrase in (
            "above/below",
            "higher/lower",
            "larger/smaller",
            "present the values side by side",
            "Golden Cross",
            "13F",
        ):
            self.assertIn(
                phrase,
                system_message,
            )

    def test_schema_and_prompt_support_degraded_sections(self) -> None:
        payload = build_supervisor_report_model_request(
            build_supervisor_report_context(
                _state(("AAPL", "MSFT"))
            )
        )

        status_enum = (
            payload["response_format"]["json_schema"]["schema"]
            ["properties"]["sections"]["items"]["properties"]
            ["status"]["enum"]
        )
        self.assertEqual(
            status_enum,
            [
                "available",
                "degraded",
                "unavailable",
            ],
        )

        system_message = payload["messages"][0]["content"]
        normalized_system_message = " ".join(
            system_message.split()
        )
        self.assertIn(
            "degraded: grounded findings remain available",
            normalized_system_message,
        )
        self.assertIn(
            "comparison-eligible base dimensions only",
            normalized_system_message,
        )
        self.assertIn(
            "do not cite that dimension or make a comparative statement",
            normalized_system_message,
        )
        self.assertIn(
            "do not turn an observed event into an inferred motive",
            normalized_system_message,
        )

    def test_repair_request_includes_exact_validator_error(self) -> None:
        context = build_supervisor_report_context(
            _state()
        )
        payload = build_supervisor_report_repair_request(
            context,
            validation_error=(
                "Report introduces an unsupported comparative relation "
                "'below' that is absent from cited worker findings."
            ),
        )

        self.assertEqual(
            payload["model"],
            "system.ai.gpt-oss-120b",
        )
        self.assertEqual(
            len(payload["messages"]),
            3,
        )
        repair_message = payload["messages"][-1]["content"]
        self.assertIn(
            "unsupported comparative relation 'below'",
            repair_message,
        )
        self.assertIn(
            "Regenerate the entire report",
            repair_message,
        )
        self.assertIn(
            "proactively avoid every guarded relation term",
            repair_message,
        )
        for guarded_term in (
            "higher",
            "strong",
            "better",
            "outperformed",
        ):
            self.assertIn(
                guarded_term,
                repair_message,
            )

    def test_repair_request_rejects_blank_validation_error(self) -> None:
        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "validation_error must be a nonblank string",
        ):
            build_supervisor_report_repair_request(
                build_supervisor_report_context(
                    _state()
                ),
                validation_error=" ",
            )

    def test_prompt_builder_rejects_non_mapping_context(self) -> None:
        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "context must be an object",
        ):
            build_supervisor_report_model_request(
                ["not", "mapping"]  # type: ignore[arg-type]
            )


class SupervisorReportRuntimeTests(unittest.TestCase):
    def test_runs_120b_and_returns_validated_report(self) -> None:
        model_query = Mock(
            return_value=_chat_response(
                _single_report_output()
            )
        )
        state = _state()

        report = run_supervisor_report_synthesis(
            state=state,
            profile="profile-1",
            model_query=model_query,
        )

        self.assertEqual(
            report.mode,
            "single_company",
        )
        self.assertEqual(
            report.status,
            "ready",
        )
        self.assertEqual(
            report.synthesis_mode,
            "model",
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

        model_query.assert_called_once()
        kwargs = model_query.call_args.kwargs
        self.assertEqual(
            kwargs["profile"],
            "profile-1",
        )
        self.assertEqual(
            kwargs["payload"]["model"],
            "system.ai.gpt-oss-120b",
        )
        self.assertIs(
            kwargs["payload"]["stream"],
            False,
        )

    def test_repairs_one_deterministic_validation_failure(self) -> None:
        invalid = _single_report_output()
        invalid["sections"][0]["source_finding_ids"] = [
            "market_analysis:invented"
        ]
        valid = _single_report_output()
        model_query = Mock(
            side_effect=[
                _chat_response(invalid),
                _chat_response(valid),
            ]
        )

        report = run_supervisor_report_synthesis(
            state=_state(),
            profile="profile-1",
            model_query=model_query,
        )

        self.assertEqual(
            report.status,
            "ready",
        )
        self.assertEqual(
            report.synthesis_mode,
            "repaired_model",
        )
        self.assertEqual(
            model_query.call_count,
            2,
        )
        repair_payload = model_query.call_args_list[1].kwargs[
            "payload"
        ]
        self.assertIn(
            "unknown worker findings",
            repair_payload["messages"][-1]["content"],
        )

    def test_second_invalid_report_uses_deterministic_fallback(
        self,
    ) -> None:
        invalid = _single_report_output()
        invalid["sections"][0]["source_finding_ids"] = [
            "market_analysis:invented"
        ]
        model_query = Mock(
            side_effect=[
                _chat_response(invalid),
                _chat_response(invalid),
            ]
        )

        report = run_supervisor_report_synthesis(
            state=_state(),
            model_query=model_query,
        )

        self.assertEqual(
            report.status,
            "ready",
        )
        self.assertEqual(
            report.synthesis_mode,
            "deterministic_fallback",
        )
        self.assertEqual(
            model_query.call_count,
            2,
        )
        self.assertNotIn(
            "market_analysis:invented",
            {
                source_id
                for section in report.sections
                for source_id in section.source_finding_ids
            },
        )

    def test_synthesis_span_records_repair_and_repaired_model_outcome(
        self,
    ) -> None:
        invalid = _single_report_output()
        invalid["sections"][0]["source_finding_ids"] = [
            "market_analysis:invented"
        ]
        valid = _single_report_output()
        span = Mock()

        with patch(
            "equity_research.supervisor_report_runtime."
            "optional_mlflow_span",
            return_value=nullcontext(
                span
            ),
        ):
            report = run_supervisor_report_synthesis(
                state=_state(),
                model_query=Mock(
                    side_effect=[
                        _chat_response(invalid),
                        _chat_response(valid),
                    ]
                ),
            )

        self.assertEqual(
            report.synthesis_mode,
            "repaired_model",
        )
        final_attributes = span.set_attributes.call_args_list[
            -1
        ].args[0]
        self.assertEqual(
            final_attributes,
            {
                "equity_research.repair_count": 1,
                "equity_research.synthesis_mode": "repaired_model",
                "equity_research.report_status": "ready",
            },
        )
        span.set_outputs.assert_called_once_with(
            {
                "status": "ready",
                "synthesis_mode": "repaired_model",
                "section_count": 4,
                "evidence_count": 1,
                "repair_count": 1,
            }
        )

    def test_synthesis_span_records_deterministic_fallback_outcome(
        self,
    ) -> None:
        invalid = _single_report_output()
        invalid["sections"][0]["source_finding_ids"] = [
            "market_analysis:invented"
        ]
        span = Mock()

        with patch(
            "equity_research.supervisor_report_runtime."
            "optional_mlflow_span",
            return_value=nullcontext(
                span
            ),
        ):
            report = run_supervisor_report_synthesis(
                state=_state(),
                model_query=Mock(
                    side_effect=[
                        _chat_response(invalid),
                        _chat_response(invalid),
                    ]
                ),
            )

        self.assertEqual(
            report.synthesis_mode,
            "deterministic_fallback",
        )
        final_attributes = span.set_attributes.call_args_list[
            -1
        ].args[0]
        self.assertEqual(
            final_attributes[
                "equity_research.repair_count"
            ],
            1,
        )
        self.assertEqual(
            final_attributes[
                "equity_research.synthesis_mode"
            ],
            "deterministic_fallback",
        )
        output = span.set_outputs.call_args.args[0]
        self.assertEqual(
            output["repair_count"],
            1,
        )
        self.assertEqual(
            output["synthesis_mode"],
            "deterministic_fallback",
        )

    def test_accepts_reasoning_plus_single_final_text_block(self) -> None:
        report = run_supervisor_report_synthesis(
            state=_state(),
            model_query=Mock(
                return_value=_chat_response(
                    _single_report_output(),
                    reasoning_block=True,
                )
            ),
        )

        self.assertEqual(
            report.sections[0].section,
            "market_performance",
        )

    def test_invented_worker_finding_never_survives_fallback(self) -> None:
        output = _single_report_output()
        output["sections"][0]["source_finding_ids"] = [
            "market_analysis:invented"
        ]

        report = run_supervisor_report_synthesis(
            state=_state(),
            model_query=Mock(
                return_value=_chat_response(
                    output
                )
            ),
        )

        self.assertEqual(
            report.synthesis_mode,
            "deterministic_fallback",
        )
        self.assertNotIn(
            "market_analysis:invented",
            {
                source_id
                for section in report.sections
                for source_id in section.source_finding_ids
            },
        )

    def test_malformed_repair_response_still_fails(self) -> None:
        invalid = _single_report_output()
        invalid["sections"][0]["source_finding_ids"] = [
            "market_analysis:invented"
        ]
        malformed = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "not json",
                    },
                }
            ]
        }
        model_query = Mock(
            side_effect=[
                _chat_response(invalid),
                malformed,
            ]
        )

        with self.assertRaisesRegex(
            AgentModelResponseError,
            "not valid JSON",
        ):
            run_supervisor_report_synthesis(
                state=_state(),
                model_query=model_query,
            )

        self.assertEqual(
            model_query.call_count,
            2,
        )

    def test_rejects_non_json_model_response(self) -> None:
        response = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "not json",
                    },
                }
            ]
        }

        model_query = Mock(
            return_value=response
        )

        with self.assertRaisesRegex(
            AgentModelResponseError,
            "not valid JSON",
        ):
            run_supervisor_report_synthesis(
                state=_state(),
                model_query=model_query,
            )

        model_query.assert_called_once()

    def test_rejects_truncated_model_response(self) -> None:
        response = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {
                        "role": "assistant",
                        "content": "{}",
                    },
                }
            ]
        }

        model_query = Mock(
            return_value=response
        )

        with self.assertRaisesRegex(
            AgentModelResponseError,
            "did not finish normally",
        ):
            run_supervisor_report_synthesis(
                state=_state(),
                model_query=model_query,
            )

        model_query.assert_called_once()

    def test_rejects_noncallable_model_query(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "model_query must be callable",
        ):
            run_supervisor_report_synthesis(
                state=_state(),
                model_query=None,  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
