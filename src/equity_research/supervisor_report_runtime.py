"""Runtime for GPT OSS 120B final Supervisor report synthesis."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Callable

from equity_research.databricks_cli_runtime import (
    query_chat_completions_via_cli,
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

    context = build_supervisor_report_context(
        state
    )
    payload = build_supervisor_report_model_request(
        context
    )
    response = model_query(
        payload=payload,
        profile=profile,
    )
    raw_output = parse_structured_chat_response(
        response
    )

    try:
        return validate_supervisor_report_output(
            raw_output,
            state=state,
        )
    except SupervisorReportContractError as exc:
        repair_payload = build_supervisor_report_repair_request(
            context,
            validation_error=str(exc),
        )
        repair_response = model_query(
            payload=repair_payload,
            profile=profile,
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
            return build_deterministic_supervisor_report(
                state
            )

        return replace(
            repaired_report,
            synthesis_mode="repaired_model",
        )
