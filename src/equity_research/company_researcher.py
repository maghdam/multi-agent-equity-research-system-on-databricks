"""Deterministic Company Researcher input/output contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from equity_research.agent_contracts import (
    AgentContractError,
    AgentLimitation,
)
from equity_research.config import Equity
from equity_research.retrieval_tools import EvidenceRecord
from equity_research.tool_scope import resolve_requested_equities


ResearchTopic = Literal["recent_developments", "principal_risks"]
FindingCharacterization = Literal[
    "development",
    "company_disclosed_risk",
    "risk_context",
]


@dataclass(frozen=True)
class ResearchFinding:
    """One narrative finding grounded in supplied controlled evidence."""

    finding_id: str
    topic: ResearchTopic
    characterization: FindingCharacterization
    symbols: tuple[str, ...]
    statement: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CompanyResearcherResult:
    """Validated narrative findings plus any explicit evidence limitation."""

    findings: tuple[ResearchFinding, ...]
    limitations: tuple[AgentLimitation, ...]


def build_company_researcher_context(
    *,
    topic: ResearchTopic,
    requested_symbols: Sequence[str],
    evidence: Sequence[EvidenceRecord],
    equities: Mapping[str, Equity] | None = None,
) -> dict[str, Any]:
    """Build the exact JSON-safe evidence context available to the worker."""

    normalized_topic = _require_topic(topic)
    requested = resolve_requested_equities(
        requested_symbols,
        equities=equities,
    )
    symbols = tuple(
        equity.symbol
        for equity in requested
    )
    evidence_by_id = _index_evidence(
        evidence,
        requested_symbols=set(symbols),
    )

    if (
        normalized_topic == "recent_developments"
        and any(
            item.source_type != "news"
            for item in evidence_by_id.values()
        )
    ):
        raise AgentContractError(
            "Recent-development context may contain only news evidence."
        )

    return {
        "topic": normalized_topic,
        "requested_symbols": list(symbols),
        "evidence": [
            _evidence_payload(
                evidence_by_id[evidence_id]
            )
            for evidence_id in evidence_by_id
        ],
    }


def validate_company_researcher_output(
    raw_output: Mapping[str, Any],
    *,
    topic: ResearchTopic,
    requested_symbols: Sequence[str],
    evidence: Sequence[EvidenceRecord],
    equities: Mapping[str, Equity] | None = None,
) -> CompanyResearcherResult:
    """Validate narrative findings against the exact supplied evidence set."""

    if not isinstance(raw_output, Mapping):
        raise AgentContractError(
            "Company Researcher output must be an object."
        )

    unknown = set(raw_output) - {
        "findings",
        "insufficient_evidence",
    }

    if unknown:
        raise AgentContractError(
            "Company Researcher output has unknown fields: "
            f"{sorted(unknown)}."
        )

    normalized_topic = _require_topic(topic)
    requested = resolve_requested_equities(
        requested_symbols,
        equities=equities,
    )
    symbols = tuple(
        equity.symbol
        for equity in requested
    )
    symbol_set = set(symbols)
    evidence_by_id = _index_evidence(
        evidence,
        requested_symbols=symbol_set,
    )

    raw_findings = raw_output.get("findings")

    if not isinstance(raw_findings, list):
        raise AgentContractError(
            "Company Researcher findings must be a list."
        )

    insufficient_raw = raw_output.get(
        "insufficient_evidence"
    )
    insufficient = None

    if insufficient_raw is not None:
        insufficient = _required_text(
            insufficient_raw,
            "insufficient_evidence",
        )

    if not evidence_by_id and raw_findings:
        raise AgentContractError(
            "Company Researcher cannot return findings without evidence."
        )

    if not raw_findings and insufficient is None:
        raise AgentContractError(
            "No findings require an insufficient_evidence explanation."
        )

    findings: list[ResearchFinding] = []
    seen_ids: set[str] = set()

    for raw in raw_findings:
        if not isinstance(raw, Mapping):
            raise AgentContractError(
                "Each Company Researcher finding must be an object."
            )

        unknown_finding_fields = set(raw) - {
            "finding_id",
            "topic",
            "characterization",
            "symbols",
            "statement",
            "evidence_ids",
        }

        if unknown_finding_fields:
            raise AgentContractError(
                "Company Researcher finding has unknown fields: "
                f"{sorted(unknown_finding_fields)}."
            )

        finding_id = _required_text(
            raw.get("finding_id"),
            "finding_id",
        )

        if finding_id in seen_ids:
            raise AgentContractError(
                f"Duplicate Company Researcher finding_id: {finding_id}."
            )
        seen_ids.add(finding_id)

        finding_topic = raw.get("topic")

        if finding_topic != normalized_topic:
            raise AgentContractError(
                "Finding topic must match the Company Researcher request."
            )

        characterization = raw.get(
            "characterization"
        )

        _validate_characterization(
            topic=normalized_topic,
            characterization=characterization,
        )

        finding_symbols = _parse_symbol_tuple(
            raw.get("symbols"),
            requested_symbols=symbol_set,
        )
        statement = _required_text(
            raw.get("statement"),
            "statement",
        )
        evidence_ids = _parse_evidence_ids(
            raw.get("evidence_ids"),
            evidence_by_id=evidence_by_id,
        )

        cited = tuple(
            evidence_by_id[evidence_id]
            for evidence_id in evidence_ids
        )

        _validate_evidence_scope(
            cited,
            finding_symbols=finding_symbols,
        )
        _validate_evidence_type(
            cited,
            topic=normalized_topic,
            characterization=characterization,
        )

        findings.append(
            ResearchFinding(
                finding_id=finding_id,
                topic=normalized_topic,
                characterization=characterization,
                symbols=finding_symbols,
                statement=statement,
                evidence_ids=evidence_ids,
            )
        )

    limitations: list[AgentLimitation] = []

    if insufficient is not None:
        limitations.append(
            AgentLimitation(
                agent="company_researcher",
                symbol=None,
                dimension=normalized_topic,
                reason_code="insufficient_evidence",
                message=insufficient,
            )
        )

    return CompanyResearcherResult(
        findings=tuple(findings),
        limitations=tuple(limitations),
    )


def _index_evidence(
    evidence: Sequence[EvidenceRecord],
    *,
    requested_symbols: set[str],
) -> dict[str, EvidenceRecord]:
    if isinstance(evidence, (str, bytes)):
        raise AgentContractError(
            "evidence must be a sequence of EvidenceRecord values."
        )

    indexed: dict[str, EvidenceRecord] = {}

    for item in evidence:
        if not isinstance(item, EvidenceRecord):
            raise AgentContractError(
                "evidence contains an invalid value."
            )

        if item.evidence_id in indexed:
            raise AgentContractError(
                f"Duplicate evidence_id: {item.evidence_id}."
            )

        if not set(item.configured_symbols).intersection(
            requested_symbols
        ):
            raise AgentContractError(
                "Evidence falls outside requested company scope."
            )

        indexed[item.evidence_id] = item

    return indexed


def _evidence_payload(
    item: EvidenceRecord,
) -> dict[str, Any]:
    return {
        "evidence_id": item.evidence_id,
        "source_type": item.source_type,
        "source_system": item.source_system,
        "configured_symbols": list(
            item.configured_symbols
        ),
        "title": item.title,
        "evidence_date": item.evidence_date.isoformat(),
        "source_url": item.source_url,
        "source_business_id": item.source_business_id,
        "section_code": item.section_code,
        "section_title": item.section_title,
        "retrieval_rank": item.retrieval_rank,
        "untrusted_text": item.text,
    }


def _validate_characterization(
    *,
    topic: ResearchTopic,
    characterization: object,
) -> None:
    if topic == "recent_developments":
        if characterization != "development":
            raise AgentContractError(
                "Recent-development findings must use "
                "characterization='development'."
            )
        return

    if characterization not in {
        "company_disclosed_risk",
        "risk_context",
    }:
        raise AgentContractError(
            "Principal-risk findings must be characterized as "
            "'company_disclosed_risk' or 'risk_context'."
        )


def _validate_evidence_type(
    evidence: Sequence[EvidenceRecord],
    *,
    topic: ResearchTopic,
    characterization: FindingCharacterization,
) -> None:
    source_types = {
        item.source_type
        for item in evidence
    }

    if topic == "recent_developments":
        if source_types != {"news"}:
            raise AgentContractError(
                "Recent-development findings may cite only news evidence."
            )
        return

    if (
        characterization == "company_disclosed_risk"
        and source_types != {"filing"}
    ):
        raise AgentContractError(
            "Company-disclosed risk findings may cite only filing evidence."
        )

    if (
        characterization == "risk_context"
        and "news" not in source_types
    ):
        raise AgentContractError(
            "Risk-context findings require at least one news evidence item."
        )


def _validate_evidence_scope(
    evidence: Sequence[EvidenceRecord],
    *,
    finding_symbols: Sequence[str],
) -> None:
    covered: set[str] = set()

    for item in evidence:
        covered.update(
            item.configured_symbols
        )

    if not set(finding_symbols).issubset(
        covered
    ):
        raise AgentContractError(
            "Cited evidence does not cover every finding symbol."
        )


def _parse_evidence_ids(
    value: object,
    *,
    evidence_by_id: Mapping[str, EvidenceRecord],
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise AgentContractError(
            "Each Company Researcher finding requires evidence_ids."
        )

    evidence_ids = tuple(
        _required_text(
            item,
            "evidence_id",
        )
        for item in value
    )

    if len(set(evidence_ids)) != len(evidence_ids):
        raise AgentContractError(
            "evidence_ids must be unique within a finding."
        )

    unknown = [
        evidence_id
        for evidence_id in evidence_ids
        if evidence_id not in evidence_by_id
    ]

    if unknown:
        raise AgentContractError(
            f"Finding cites unavailable evidence IDs: {unknown}."
        )

    return evidence_ids


def _parse_symbol_tuple(
    value: object,
    *,
    requested_symbols: set[str],
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise AgentContractError(
            "finding symbols must be a nonempty list."
        )

    symbols = tuple(
        _required_text(
            item,
            "finding symbol",
        ).upper()
        for item in value
    )

    if len(set(symbols)) != len(symbols):
        raise AgentContractError(
            "finding symbols must be unique."
        )

    if not set(symbols).issubset(
        requested_symbols
    ):
        raise AgentContractError(
            "finding symbols must stay within requested scope."
        )

    return symbols


def _require_topic(
    topic: object,
) -> ResearchTopic:
    if topic not in {
        "recent_developments",
        "principal_risks",
    }:
        raise AgentContractError(
            "topic must be 'recent_developments' or 'principal_risks'."
        )

    return topic


def _required_text(
    value: object,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentContractError(
            f"{field} must be a nonblank string."
        )

    return value.strip()
