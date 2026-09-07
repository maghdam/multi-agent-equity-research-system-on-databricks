from __future__ import annotations

import json
import sys
import unittest
from contextlib import nullcontext
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mlflow.entities import SpanType  # noqa: E402

from equity_research.app_contracts import AppResearchSelection  # noqa: E402
from equity_research.app_followup import (  # noqa: E402
    FOLLOWUP_SYSTEM_PROMPT,
    FollowupAnswerContractError,
    FollowupSessionError,
    MAX_FOLLOWUP_TURNS,
    build_followup_session_payload,
    conversation_from_envelope,
    run_followup_turn,
    run_traced_followup_turn,
    sign_followup_session,
    validate_followup_output,
    verify_followup_session,
)
from equity_research.app_service import (  # noqa: E402
    AppResearchSession,
    AppStructuredSnapshot,
)
from equity_research.company_researcher import (  # noqa: E402
    CompanyResearcherResult,
    ResearchFinding,
)
from equity_research.config import Equity  # noqa: E402
from equity_research.mlflow_tracing import MlflowTracingConfig  # noqa: E402
from equity_research.market_analyst import (  # noqa: E402
    MarketAnalystResult,
    MetricReference,
    StructuredFinding,
)
from equity_research.retrieval_tools import EvidenceRecord  # noqa: E402
from equity_research.structured_data_tools import (  # noqa: E402
    FundamentalMetricsToolResult,
    MarketMetricsToolResult,
)
from equity_research.supervisor_contracts import (  # noqa: E402
    assemble_supervisor_state,
    build_supervisor_plan,
    successful_worker_outcome,
)
from equity_research.supervisor_report import (  # noqa: E402
    EvidenceCitation,
    ReportSection,
    SupervisorReport,
)
from equity_research.supervisor_research_graph import (  # noqa: E402
    SupervisorResearchResult,
)


EVIDENCE_ID = "a" * 64
FILING_ID = "b" * 64
SIGNING_KEY = b"k" * 32
NOW = datetime(
    2026,
    9,
    7,
    12,
    0,
    tzinfo=timezone.utc,
)

EQUITIES = {
    "AAPL": Equity(
        symbol="AAPL",
        display_name="Apple Inc.",
        alpaca_symbol="AAPL",
        sec_cik="0000320193",
    ),
}


def _evidence(
    evidence_id: str,
    *,
    source_type: str,
) -> EvidenceRecord:
    filing = source_type == "filing"

    return EvidenceRecord(
        evidence_id=evidence_id,
        retrieval_rank=1,
        chunk_id=evidence_id,
        document_id=(
            "sec:filing:aapl:item_1a"
            if filing
            else "alpaca:news:101"
        ),
        document_version_id="version-1",
        source_type=source_type,
        source_system=(
            "sec"
            if filing
            else "alpaca"
        ),
        configured_symbols=("AAPL",),
        title=(
            "Apple Form 10-K"
            if filing
            else "LICENSED HEADLINE MUST NOT ENTER FOLLOWUP"
        ),
        evidence_date=(
            date(2025, 10, 31)
            if filing
            else date(2026, 8, 30)
        ),
        source_url=(
            "https://www.sec.gov/Archives/example"
            if filing
            else "https://www.benzinga.com/news/example"
        ),
        source_business_id=(
            "0000320193-25-000079"
            if filing
            else "101"
        ),
        section_code=(
            "item_1a"
            if filing
            else None
        ),
        section_title=(
            "Risk Factors"
            if filing
            else None
        ),
        chunk_index=0,
        text=(
            "RAW RETRIEVED TEXT MUST NOT ENTER FOLLOWUP"
        ),
        source_response_id="response-1",
        source_fetched_at=NOW,
        source_ingestion_run_id="run-1",
    )


def _session() -> AppResearchSession:
    market_result = MarketAnalystResult(
        findings=(
            StructuredFinding(
                finding_id="m1",
                dimension="market",
                symbols=("AAPL",),
                statement=(
                    "AAPL 60-session return was 9.74%."
                ),
                metric_references=(
                    MetricReference(
                        dataset="market_metrics",
                        symbol="AAPL",
                        as_of_date=date(2026, 9, 4),
                        fields=("return_60d",),
                    ),
                ),
            ),
            StructuredFinding(
                finding_id="f1",
                dimension="fundamental",
                symbols=("AAPL",),
                statement=(
                    "AAPL revenue TTM was 466.82 billion USD."
                ),
                metric_references=(
                    MetricReference(
                        dataset="fundamental_metrics",
                        symbol="AAPL",
                        as_of_date=date(2026, 7, 31),
                        fields=("revenue_ttm",),
                    ),
                ),
            ),
        ),
        limitations=(),
    )
    recent_result = CompanyResearcherResult(
        findings=(
            ResearchFinding(
                finding_id="fd1",
                topic="recent_developments",
                characterization="development",
                symbols=("AAPL",),
                statement=(
                    "Apple announced a device leasing strategy."
                ),
                evidence_ids=(EVIDENCE_ID,),
            ),
        ),
        limitations=(),
    )
    risk_result = CompanyResearcherResult(
        findings=(
            ResearchFinding(
                finding_id="fr1",
                topic="principal_risks",
                characterization="company_disclosed_risk",
                symbols=("AAPL",),
                statement=(
                    "Apple disclosed supply-chain risks."
                ),
                evidence_ids=(FILING_ID,),
            ),
        ),
        limitations=(),
    )
    plan = build_supervisor_plan(
        request_text="Research Apple.",
        requested_symbols=("AAPL",),
        equities=EQUITIES,
    )
    state = assemble_supervisor_state(
        plan=plan,
        outcomes=(
            successful_worker_outcome(
                route_id="market_analysis",
                result=market_result,
            ),
            successful_worker_outcome(
                route_id="recent_developments",
                result=recent_result,
            ),
            successful_worker_outcome(
                route_id="principal_risks",
                result=risk_result,
            ),
        ),
    )
    report = SupervisorReport(
        mode="single_company",
        symbols=("AAPL",),
        status="ready",
        sections=(
            ReportSection(
                section="market_performance",
                status="available",
                text="AAPL 60-session return was 9.74%.",
                source_finding_ids=("market_analysis:m1",),
            ),
            ReportSection(
                section="fundamental_performance",
                status="available",
                text="AAPL revenue TTM was 466.82 billion USD.",
                source_finding_ids=("market_analysis:f1",),
            ),
            ReportSection(
                section="recent_developments",
                status="available",
                text="Apple announced a device leasing strategy.",
                source_finding_ids=("recent_developments:fd1",),
            ),
            ReportSection(
                section="principal_risks",
                status="available",
                text="Apple disclosed supply-chain risks.",
                source_finding_ids=("principal_risks:fr1",),
            ),
        ),
        limitations=(),
        evidence=(
            EvidenceCitation(
                evidence_id=EVIDENCE_ID,
                source_finding_ids=("recent_developments:fd1",),
            ),
            EvidenceCitation(
                evidence_id=FILING_ID,
                source_finding_ids=("principal_risks:fr1",),
            ),
        ),
        synthesis_mode="model",
    )

    return AppResearchSession(
        selection=AppResearchSelection(
            requested_symbols=("AAPL",),
            market_window_sessions=60,
        ),
        request_text="Research Apple.",
        structured=AppStructuredSnapshot(
            market_results=(
                MarketMetricsToolResult(
                    symbol="AAPL",
                    display_name="Apple Inc.",
                    status="unavailable",
                    reason_code="fixture",
                    limitation="Fixture market cards unavailable.",
                    metric=None,
                ),
            ),
            fundamental_results=(
                FundamentalMetricsToolResult(
                    symbol="AAPL",
                    display_name="Apple Inc.",
                    status="unavailable",
                    reason_code="fixture",
                    limitation="Fixture fundamental cards unavailable.",
                    metric=None,
                ),
            ),
            narrative_evidence=(
                _evidence(
                    EVIDENCE_ID,
                    source_type="news",
                ),
                _evidence(
                    FILING_ID,
                    source_type="filing",
                ),
            ),
        ),
        research=SupervisorResearchResult(
            state=state,
            report=report,
        ),
    )


def _response(
    value: dict,
) -> dict:
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        value
                    ),
                },
            }
        ]
    }


class AppFollowupTests(unittest.TestCase):
    def test_signed_session_excludes_raw_provider_text(self) -> None:
        payload = build_followup_session_payload(
            _session()
        )
        serialized = json.dumps(
            payload
        )

        self.assertNotIn(
            "RAW RETRIEVED TEXT",
            serialized,
        )
        self.assertNotIn(
            "LICENSED HEADLINE",
            serialized,
        )
        self.assertIn(
            "www.benzinga.com",
            serialized,
        )

        envelope = sign_followup_session(
            payload,
            signing_key=SIGNING_KEY,
        )
        verified = verify_followup_session(
            envelope,
            signing_key=SIGNING_KEY,
        )

        self.assertEqual(
            verified,
            payload,
        )

        tampered = json.loads(
            json.dumps(envelope)
        )
        tampered["payload"]["research"]["symbols"] = [
            "MSFT"
        ]

        with self.assertRaisesRegex(
            FollowupSessionError,
            "signature",
        ):
            verify_followup_session(
                tampered,
                signing_key=SIGNING_KEY,
            )

    def test_output_requires_known_grounded_sources_and_numbers(self) -> None:
        payload = build_followup_session_payload(
            _session()
        )

        answer = validate_followup_output(
            {
                "answer": "AAPL 60-session return was 9.74%.",
                "source_ids": [
                    "market_analysis:m1"
                ],
                "evidence_ids": [],
                "limitation": "",
            },
            session_payload=payload,
        )

        self.assertEqual(
            answer.source_ids,
            ("market_analysis:m1",),
        )

        with self.assertRaisesRegex(
            FollowupAnswerContractError,
            "numerical",
        ):
            validate_followup_output(
                {
                    "answer": "AAPL 60-session return was 99.99%.",
                    "source_ids": [
                        "market_analysis:m1"
                    ],
                    "evidence_ids": [],
                    "limitation": "",
                },
                session_payload=payload,
            )

        with self.assertRaisesRegex(
            FollowupAnswerContractError,
            "unknown source",
        ):
            validate_followup_output(
                {
                    "answer": "Unsupported source.",
                    "source_ids": [
                        "made-up-source"
                    ],
                    "evidence_ids": [],
                    "limitation": "",
                },
                session_payload=payload,
            )

    def test_output_requires_evidence_to_link_to_cited_source(self) -> None:
        payload = build_followup_session_payload(
            _session()
        )

        valid = validate_followup_output(
            {
                "answer": (
                    "Apple announced a device leasing strategy."
                ),
                "source_ids": [
                    "recent_developments:fd1"
                ],
                "evidence_ids": [
                    EVIDENCE_ID
                ],
                "limitation": "",
            },
            session_payload=payload,
        )

        self.assertEqual(
            valid.evidence_ids,
            (EVIDENCE_ID,),
        )

        with self.assertRaisesRegex(
            FollowupAnswerContractError,
            "linked",
        ):
            validate_followup_output(
                {
                    "answer": (
                        "Apple announced a device leasing strategy."
                    ),
                    "source_ids": [
                        "recent_developments:fd1"
                    ],
                    "evidence_ids": [
                        FILING_ID
                    ],
                    "limitation": "",
                },
                session_payload=payload,
            )

    def test_unsupported_relationship_is_rejected(self) -> None:
        payload = build_followup_session_payload(
            _session()
        )

        with self.assertRaisesRegex(
            FollowupAnswerContractError,
            "relationship",
        ):
            validate_followup_output(
                {
                    "answer": (
                        "AAPL had a higher 60-session return of 9.74%."
                    ),
                    "source_ids": [
                        "market_analysis:m1"
                    ],
                    "evidence_ids": [],
                    "limitation": "",
                },
                session_payload=payload,
            )

    def test_turn_repairs_unsupported_relationship_with_exact_values(
        self,
    ) -> None:
        payload = build_followup_session_payload(
            _session()
        )
        envelope = sign_followup_session(
            payload,
            signing_key=SIGNING_KEY,
        )
        model_query = Mock(
            side_effect=[
                _response(
                    {
                        "answer": (
                            "AAPL had a higher 60-session return of 9.74%."
                        ),
                        "source_ids": [
                            "market_analysis:m1"
                        ],
                        "evidence_ids": [],
                        "limitation": "",
                    }
                ),
                _response(
                    {
                        "answer": (
                            "AAPL 60-session return was 9.74%. "
                            "The active research does not provide an explicit "
                            "qualitative ranking."
                        ),
                        "source_ids": [
                            "market_analysis:m1"
                        ],
                        "evidence_ids": [],
                        "limitation": "",
                    }
                ),
            ]
        )

        result = run_followup_turn(
            envelope,
            question="Was AAPL's 60-session return higher?",
            signing_key=SIGNING_KEY,
            model_query=model_query,
        )

        self.assertEqual(
            model_query.call_count,
            2,
        )
        self.assertIn(
            "explicit qualitative ranking",
            result.answer.answer,
        )
        repair_payload = (
            model_query.call_args_list[
                1
            ].kwargs[
                "payload"
            ]
        )
        repair_instruction = (
            repair_payload[
                "messages"
            ][
                -1
            ][
                "content"
            ]
        )
        self.assertIn(
            "unsupported relationship",
            repair_instruction,
        )
        self.assertIn(
            "exact cited comparison values",
            repair_instruction,
        )

    def test_system_prompt_handles_unsupported_comparison_wording(self) -> None:
        self.assertIn(
            "do not echo that unsupported wording",
            FOLLOWUP_SYSTEM_PROMPT,
        )
        self.assertIn(
            "explicit qualitative ranking",
            FOLLOWUP_SYSTEM_PROMPT,
        )

    def test_turn_repairs_malformed_structured_response(self) -> None:
        payload = build_followup_session_payload(
            _session()
        )
        envelope = sign_followup_session(
            payload,
            signing_key=SIGNING_KEY,
        )
        model_query = Mock(
            side_effect=[
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": "not-json",
                            },
                        }
                    ]
                },
                _response(
                    {
                        "answer": (
                            "Apple announced a device leasing strategy."
                        ),
                        "source_ids": [
                            "recent_developments:fd1"
                        ],
                        "evidence_ids": [
                            EVIDENCE_ID
                        ],
                        "limitation": "",
                    }
                ),
            ]
        )

        result = run_followup_turn(
            envelope,
            question="What changed recently?",
            signing_key=SIGNING_KEY,
            model_query=model_query,
        )

        self.assertEqual(
            model_query.call_count,
            2,
        )
        self.assertEqual(
            result.answer.evidence_ids,
            (EVIDENCE_ID,),
        )

    def test_turn_repairs_once_and_preserves_bounded_history(self) -> None:
        payload = build_followup_session_payload(
            _session()
        )
        payload["conversation"] = [
            {
                "question": f"Prior question {index}",
                "answer": "Apple disclosed supply-chain risks.",
                "source_ids": [
                    "principal_risks:fr1"
                ],
                "evidence_ids": [
                    FILING_ID
                ],
                "limitation": None,
            }
            for index in range(
                MAX_FOLLOWUP_TURNS
            )
        ]
        envelope = sign_followup_session(
            payload,
            signing_key=SIGNING_KEY,
        )
        model_query = Mock(
            side_effect=[
                _response(
                    {
                        "answer": (
                            "AAPL 60-session return was 99.99%."
                        ),
                        "source_ids": [
                            "market_analysis:m1"
                        ],
                        "evidence_ids": [],
                        "limitation": "",
                    }
                ),
                _response(
                    {
                        "answer": (
                            "AAPL 60-session return was 9.74%."
                        ),
                        "source_ids": [
                            "market_analysis:m1"
                        ],
                        "evidence_ids": [],
                        "limitation": "",
                    }
                ),
            ]
        )

        result = run_followup_turn(
            envelope,
            question="What was the 60-session return?",
            signing_key=SIGNING_KEY,
            model_query=model_query,
        )

        self.assertEqual(
            model_query.call_count,
            2,
        )
        self.assertEqual(
            result.answer.answer,
            "AAPL 60-session return was 9.74%.",
        )
        conversation = conversation_from_envelope(
            result.envelope,
            signing_key=SIGNING_KEY,
        )
        self.assertEqual(
            len(conversation),
            MAX_FOLLOWUP_TURNS,
        )
        self.assertEqual(
            conversation[-1]["question"],
            "What was the 60-session return?",
        )


    def test_traced_turn_records_question_and_validated_answer(self) -> None:
        payload = build_followup_session_payload(
            _session()
        )
        envelope = sign_followup_session(
            payload,
            signing_key=SIGNING_KEY,
        )
        answer = SimpleNamespace(
            answer="Apple announced a device leasing strategy.",
            source_ids=("recent_developments:fd1",),
            evidence_ids=(EVIDENCE_ID,),
            limitation=None,
        )
        expected = SimpleNamespace(
            envelope={
                "payload": "updated",
                "signature": "fixture",
            },
            answer=answer,
        )
        span = Mock()

        with (
            patch(
                "equity_research.app_followup.configure_mlflow_tracing",
            ) as configure,
            patch(
                "equity_research.app_followup.mlflow.tracing.context",
                return_value=nullcontext(),
            ) as tracing_context,
            patch(
                "equity_research.app_followup.mlflow.start_span",
                return_value=nullcontext(
                    span
                ),
            ) as start_span,
            patch(
                "equity_research.app_followup.run_followup_turn",
                return_value=expected,
            ) as turn_runner,
        ):
            result = run_traced_followup_turn(
                envelope,
                question="What changed recently?",
                signing_key=SIGNING_KEY,
                tracing_config=MlflowTracingConfig(
                    experiment_id="123456789",
                    environment="databricks_app",
                ),
                model_query=Mock(),
            )

        self.assertIs(
            result,
            expected,
        )
        configure.assert_called_once()
        tracing_kwargs = tracing_context.call_args.kwargs
        self.assertEqual(
            tracing_kwargs["tags"]["interaction_type"],
            "followup_question",
        )
        self.assertEqual(
            tracing_kwargs["tags"]["symbols"],
            "AAPL",
        )
        self.assertEqual(
            tracing_kwargs["tags"]["request_mode"],
            "single_company",
        )
        self.assertNotIn(
            "user",
            tracing_kwargs["tags"],
        )
        start_span.assert_called_once_with(
            name="app_followup_turn",
            span_type=SpanType.AGENT,
        )
        span.set_inputs.assert_called_once()
        traced_inputs = span.set_inputs.call_args.args[0]
        self.assertEqual(
            traced_inputs["question"],
            "What changed recently?",
        )
        self.assertEqual(
            traced_inputs["market_window_sessions"],
            60,
        )
        turn_runner.assert_called_once()
        span.set_outputs.assert_called_once_with(
            {
                "answer": "Apple announced a device leasing strategy.",
                "source_ids": [
                    "recent_developments:fd1"
                ],
                "evidence_ids": [
                    EVIDENCE_ID
                ],
                "limitation": None,
            }
        )


if __name__ == "__main__":
    unittest.main()
