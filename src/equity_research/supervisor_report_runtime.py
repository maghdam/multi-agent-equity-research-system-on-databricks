"""Runtime for GPT OSS 120B final Supervisor report synthesis."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Callable

from mlflow.entities import SpanType

from equity_research.databricks_cli_runtime import (
    query_chat_completions_via_cli,
)
from equity_research.mlflow_runtime_spans import (
    optional_mlflow_span,
    run_traced_chat_completion,
)
from equity_research.supervisor_contracts import SupervisorState
from equity_research.supervisor_report import (
    SupervisorReport,
    SupervisorReportContractError,
    build_deterministic_supervisor_report,
    build_supervisor_report_context,
    validate_supervisor_report_output,
)
from equity_research.supervisor_report_prompts import (
    build_supervisor_report_model_request,
    build_supervisor_report_repair_request,
)
from equity_research.worker_agent_runtime import (
    parse_structured_chat_response,
)


def run_supervisor_report_synthesis(
    *,
    state: SupervisorState,
    profile: str | None = None,
    model_query: Callable[..., Mapping[str, Any]] = (
        query_chat_completions_via_cli
    ),
) -> SupervisorReport:
    """Run GPT OSS 120B and deterministically validate the final report."""

    if not callable(model_query):
        raise TypeError(
            "model_query must be callable."
        )

    with optional_mlflow_span(
        name="supervisor_report_synthesis",
        span_type=SpanType.AGENT,
    ) as synthesis_span:
        if synthesis_span is not None:
            synthesis_span.set_inputs(
                {
                    "mode": state.request.mode,
                    "symbols": list(
                        state.request.requested_symbols
                    ),
                    "state_status": state.status,
                    "worker_outcome_count": len(
                        state.outcomes
                    ),
                    "limitation_count": len(
                        state.limitations
                    ),
                    "failure_count": len(
                        state.failures
                    ),
                }
            )
            synthesis_span.set_attributes(
                {
                    "equity_research.component": (
                        "supervisor_report_synthesis"
                    ),
                    "equity_research.model_role": "supervisor",
                }
            )

        context = build_supervisor_report_context(
            state
        )
        payload = build_supervisor_report_model_request(
            context
        )
        response = run_traced_chat_completion(
            span_name="supervisor_120b_initial",
            component="supervisor_report_synthesis",
            attempt="initial",
            payload=payload,
            profile=profile,
            model_query=model_query,
            safe_inputs={
                "mode": state.request.mode,
                "symbols": list(
                    state.request.requested_symbols
                ),
                "worker_outcome_count": len(
                    state.outcomes
                ),
            },
        )
        raw_output = parse_structured_chat_response(
            response
        )

        try:
            report = validate_supervisor_report_output(
                raw_output,
                state=state,
            )
        except SupervisorReportContractError as exc:
            repair_payload = build_supervisor_report_repair_request(
                context,
                validation_error=str(exc),
            )
            repair_response = run_traced_chat_completion(
                span_name="supervisor_120b_repair",
                component="supervisor_report_synthesis",
                attempt="repair",
                payload=repair_payload,
                profile=profile,
                model_query=model_query,
                safe_inputs={
                    "mode": state.request.mode,
                    "symbols": list(
                        state.request.requested_symbols
                    ),
                    "worker_outcome_count": len(
                        state.outcomes
                    ),
                },
            )
            repaired_output = parse_structured_chat_response(
                repair_response
            )

            try:
                repaired_report = validate_supervisor_report_output(
                    repaired_output,
                    state=state,
                )
            except SupervisorReportContractError:
                report = build_deterministic_supervisor_report(
                    state
                )
                _record_synthesis_span(
                    synthesis_span,
                    report=report,
                    repair_count=1,
                )
                return report

            report = replace(
                repaired_report,
                synthesis_mode="repaired_model",
            )
            _record_synthesis_span(
                synthesis_span,
                report=report,
                repair_count=1,
            )
            return report

        _record_synthesis_span(
            synthesis_span,
            report=report,
            repair_count=0,
        )
        return report


def _record_synthesis_span(
    span,
    *,
    report: SupervisorReport,
    repair_count: int,
) -> None:
    if span is None:
        return

    span.set_attributes(
        {
            "equity_research.repair_count": repair_count,
            "equity_research.synthesis_mode": report.synthesis_mode,
            "equity_research.report_status": report.status,
        }
    )
    span.set_outputs(
        {
            "status": report.status,
            "synthesis_mode": report.synthesis_mode,
            "section_count": len(
                report.sections
            ),
            "evidence_count": len(
                report.evidence
            ),
            "repair_count": repair_count,
        }
    )

