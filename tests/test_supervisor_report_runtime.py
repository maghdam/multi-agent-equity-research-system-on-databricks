"""Offline tests for GPT OSS 120B Supervisor final synthesis runtime."""

import json
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

    def test_rejects_invented_worker_finding_id_after_model_call(self) -> None:
        output = _single_report_output()
        output["sections"][0]["source_finding_ids"] = [
            "market_analysis:invented"
        ]

        with self.assertRaisesRegex(
            SupervisorReportContractError,
            "unknown worker findings",
        ):
            run_supervisor_report_synthesis(
                state=_state(),
                model_query=Mock(
                    return_value=_chat_response(
                        output
                    )
                ),
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

        with self.assertRaisesRegex(
            AgentModelResponseError,
            "not valid JSON",
        ):
            run_supervisor_report_synthesis(
                state=_state(),
                model_query=Mock(
                    return_value=response
                ),
            )

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

        with self.assertRaisesRegex(
            AgentModelResponseError,
            "did not finish normally",
        ):
            run_supervisor_report_synthesis(
                state=_state(),
                model_query=Mock(
                    return_value=response
                ),
            )

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
