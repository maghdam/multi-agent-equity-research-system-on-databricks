"""Prompt and structured-output schema for final Supervisor synthesis."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from equity_research.supervisor_report import SupervisorReportContractError


SUPERVISOR_MODEL = "system.ai.gpt-oss-120b"
SUPERVISOR_REASONING_EFFORT = "medium"
SUPERVISOR_MAX_TOKENS = 8192

SUPERVISOR_REPORT_SYSTEM_PROMPT = """You are the final Supervisor in a
controlled equity-research system.

Use only the application-controlled JSON context supplied in this request.
The source_findings are already validated outputs from specialized worker
agents. Never use model memory, web knowledge, hidden assumptions, forecasts,
trading recommendations, or unsupported causal claims.

Every available report section must cite only source_finding_ids that appear in
the supplied source_findings. Use the correct source class for each section:
market_performance uses market-analysis market findings;
fundamental_performance uses market-analysis fundamental findings;
recent_developments uses recent-development findings;
principal_risks uses principal-risk findings.

For comparison mode, include comparative_assessment and ground it in findings
covering both requested companies. Compare only the measured dimensions
actually supported by supplied findings. Do not turn the comparison into a
buy/sell/hold recommendation.

Do not invent citations, evidence IDs, metric references, dates, companies, or
facts. Do not introduce numerical claims that are absent from the cited worker
statements. Preserve material dates and caveats from the supplied findings.

For numerical synthesis, do not derive a new directional or comparative
relationship from raw numbers unless that exact relationship is already stated
in a cited worker finding. In particular, do not newly infer above/below,
higher/lower, larger/smaller, stronger/weaker, or similar relationships. When
the cited worker findings provide values but do not explicitly state the
relationship, present the values side by side without adding a directional
conclusion. Never state a relationship that contradicts the cited values or
worker statements.

For recent_developments, do not revive worker noise that is clearly outside the
research contract. Exclude insider-share transactions, 13F/institutional
holdings, analyst/price-target commentary, moving-average or Golden Cross
signals, and other technical-analysis observations.

When a section is unavailable because of supplied limitations or failures,
mark it unavailable, cite no source findings for that section, and explain the
limitation. Include explicit report limitations whenever the Supervisor state
is degraded or unavailable.

Return only the JSON structure required by the supplied response schema.
"""

SUPERVISOR_REPORT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "supervisor_report",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "section": {
                                "type": "string",
                                "enum": [
                                    "market_performance",
                                    "fundamental_performance",
                                    "recent_developments",
                                    "principal_risks",
                                    "comparative_assessment",
                                ],
                            },
                            "status": {
                                "type": "string",
                                "enum": [
                                    "available",
                                    "unavailable",
                                ],
                            },
                            "text": {
                                "type": "string",
                            },
                            "source_finding_ids": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                },
                            },
                        },
                        "required": [
                            "section",
                            "status",
                            "text",
                            "source_finding_ids",
                        ],
                    },
                },
                "limitations": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                },
            },
            "required": [
                "sections",
                "limitations",
            ],
        },
    },
}


def build_supervisor_report_model_request(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the controlled GPT OSS 120B final-synthesis request."""

    if not isinstance(context, Mapping):
        raise SupervisorReportContractError(
            "Supervisor report context must be an object."
        )

    context_json = json.dumps(
        dict(context),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return {
        "model": SUPERVISOR_MODEL,
        "messages": [
            {
                "role": "system",
                "content": SUPERVISOR_REPORT_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "Synthesize only this application-controlled Supervisor "
                    "context:\n"
                    f"{context_json}"
                ),
            },
        ],
        "response_format": dict(
            SUPERVISOR_REPORT_RESPONSE_FORMAT
        ),
        "max_tokens": SUPERVISOR_MAX_TOKENS,
        "temperature": 0,
        "reasoning_effort": SUPERVISOR_REASONING_EFFORT,
        "stream": False,
    }
