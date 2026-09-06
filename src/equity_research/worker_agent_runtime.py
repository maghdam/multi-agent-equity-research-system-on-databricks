"""Runtime helpers for validated worker-agent model calls."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from equity_research.agent_contracts import AgentContractError
from equity_research.company_researcher import (
    CompanyResearcherResult,
    ResearchTopic,
    build_company_researcher_context,
    validate_company_researcher_output,
)
from equity_research.config import Equity
from equity_research.databricks_cli_runtime import (
    query_chat_completions_via_cli,
)
from equity_research.market_analyst import (
    MarketAnalystResult,
    build_market_analyst_context,
    validate_market_analyst_output,
)
from equity_research.retrieval_tools import EvidenceRecord
from equity_research.structured_data_tools import (
    FundamentalMetricsToolResult,
    MarketMetricsToolResult,
)
from equity_research.worker_agent_prompts import (
    build_company_researcher_model_request,
    build_market_analyst_model_request,
    build_market_analyst_repair_request,
)


class AgentModelResponseError(RuntimeError):
    """Raised when a worker model response cannot be safely interpreted."""


def parse_structured_chat_response(
    response: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract one final JSON object from a non-streaming chat response."""

    if not isinstance(response, Mapping):
        raise AgentModelResponseError(
            "Chat response must be an object."
        )

    choices = response.get("choices")

    if not isinstance(choices, list) or len(choices) != 1:
        raise AgentModelResponseError(
            "Chat response must contain exactly one choice."
        )

    choice = choices[0]

    if not isinstance(choice, Mapping):
        raise AgentModelResponseError(
            "Chat response choice must be an object."
        )

    finish_reason = choice.get("finish_reason")

    if finish_reason not in {None, "stop"}:
        raise AgentModelResponseError(
            "Chat response did not finish normally: "
            f"finish_reason={finish_reason!r}."
        )

    message = choice.get("message")

    if not isinstance(message, Mapping):
        raise AgentModelResponseError(
            "Chat response choice is missing its message."
        )

    role = message.get("role")

    if role not in {None, "assistant"}:
        raise AgentModelResponseError(
            f"Unexpected chat response role: {role!r}."
        )

    text = _extract_final_text(
        message.get("content")
    )

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentModelResponseError(
            "Worker model text block is not valid JSON."
        ) from exc

    if not isinstance(parsed, dict):
        raise AgentModelResponseError(
            "Worker model structured output must be a JSON object."
        )

    return parsed


def run_market_analyst(
    *,
    requested_symbols: Sequence[str],
    market_results: Sequence[MarketMetricsToolResult],
    fundamental_results: Sequence[FundamentalMetricsToolResult],
    profile: str | None = None,
    equities: Mapping[str, Equity] | None = None,
    model_query: Callable[..., Mapping[str, Any]] = (
        query_chat_completions_via_cli
    ),
) -> MarketAnalystResult:
    """Run GPT OSS 20B and validate its Market Analyst output."""

    context = build_market_analyst_context(
        requested_symbols=requested_symbols,
        market_results=market_results,
        fundamental_results=fundamental_results,
        equities=equities,
    )
    payload = build_market_analyst_model_request(
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
        return validate_market_analyst_output(
            raw_output,
            requested_symbols=requested_symbols,
            market_results=market_results,
            fundamental_results=fundamental_results,
            equities=equities,
        )
    except AgentContractError as exc:
        repair_payload = build_market_analyst_repair_request(
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

        return validate_market_analyst_output(
            repaired_output,
            requested_symbols=requested_symbols,
            market_results=market_results,
            fundamental_results=fundamental_results,
            equities=equities,
        )


def run_company_researcher(
    *,
    topic: ResearchTopic,
    requested_symbols: Sequence[str],
    evidence: Sequence[EvidenceRecord],
    profile: str | None = None,
    equities: Mapping[str, Equity] | None = None,
    model_query: Callable[..., Mapping[str, Any]] = (
        query_chat_completions_via_cli
    ),
) -> CompanyResearcherResult:
    """Run GPT OSS 20B and validate its Company Researcher output."""

    context = build_company_researcher_context(
        topic=topic,
        requested_symbols=requested_symbols,
        evidence=evidence,
        equities=equities,
    )
    payload = build_company_researcher_model_request(
        context
    )
    response = model_query(
        payload=payload,
        profile=profile,
    )
    raw_output = parse_structured_chat_response(
        response
    )

    return validate_company_researcher_output(
        raw_output,
        topic=topic,
        requested_symbols=requested_symbols,
        evidence=evidence,
        equities=equities,
    )


def _extract_final_text(
    content: object,
) -> str:
    if isinstance(content, str):
        if not content.strip():
            raise AgentModelResponseError(
                "Worker model returned blank text."
            )

        return content.strip()

    if not isinstance(content, list):
        raise AgentModelResponseError(
            "Worker model message content must be text or content blocks."
        )

    text_blocks: list[str] = []

    for block in content:
        if not isinstance(block, Mapping):
            raise AgentModelResponseError(
                "Worker model content blocks must be objects."
            )

        block_type = block.get("type")

        if block_type == "reasoning":
            continue

        if block_type != "text":
            continue

        text_value = block.get("text")

        if not isinstance(text_value, str) or not text_value.strip():
            raise AgentModelResponseError(
                "Worker model text block must contain nonblank text."
            )

        text_blocks.append(
            text_value.strip()
        )

    if len(text_blocks) != 1:
        raise AgentModelResponseError(
            "Worker model response must contain exactly one final text block."
        )

    return text_blocks[0]
