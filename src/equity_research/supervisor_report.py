"""Deterministic structured-report contracts for Supervisor synthesis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from equity_research.company_researcher import CompanyResearcherResult
from equity_research.market_analyst import MarketAnalystResult
from equity_research.supervisor_contracts import (
    SupervisorState,
    SupervisorWorkerFailure,
)


ReportSectionName = Literal[
    "market_performance",
    "fundamental_performance",
    "recent_developments",
    "principal_risks",
    "comparative_assessment",
]


class SupervisorReportContractError(ValueError):
    """Raised when final Supervisor report synthesis violates its contract."""


@dataclass(frozen=True)
class ReportSourceFinding:
    """One validated worker finding exposed to the synthesis model."""

    source_finding_id: str
    route_id: str
    symbols: tuple[str, ...]
    statement: str
    metric_references: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    dimension_or_topic: str


@dataclass(frozen=True)
class ReportSection:
    """One synthesized report section with deterministic finding provenance."""

    section: ReportSectionName
    text: str
    source_finding_ids: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceCitation:
    """One evidence ID inherited from a cited Company Researcher finding."""

    evidence_id: str
    source_finding_ids: tuple[str, ...]


@dataclass(frozen=True)
class SupervisorReport:
    """Validated structured report assembled from worker findings only."""

    mode: str
    symbols: tuple[str, ...]
    status: str
    sections: tuple[ReportSection, ...]
    limitations: tuple[str, ...]
    evidence: tuple[EvidenceCitation, ...]


REQUIRED_BASE_SECTIONS: tuple[ReportSectionName, ...] = (
    "market_performance",
    "fundamental_performance",
    "recent_developments",
    "principal_risks",
)


def build_supervisor_report_context(
    state: SupervisorState,
) -> dict[str, Any]:
    """Build the exact JSON-safe context available to final synthesis."""

    if not isinstance(state, SupervisorState):
        raise SupervisorReportContractError(
            "state must be SupervisorState."
        )

    source_findings = _source_findings(
        state
    )

    return {
        "request": {
            "text": state.request.request_text,
            "mode": state.request.mode,
            "symbols": list(
                state.request.requested_symbols
            ),
            "status": state.status,
        },
        "source_findings": [
            {
                "source_finding_id": item.source_finding_id,
                "route_id": item.route_id,
                "symbols": list(item.symbols),
                "statement": item.statement,
                "metric_references": list(
                    item.metric_references
                ),
                "evidence_ids": list(
                    item.evidence_ids
                ),
                "dimension_or_topic": item.dimension_or_topic,
            }
            for item in source_findings
        ],
        "limitations": [
            {
                "agent": limitation.agent,
                "symbol": limitation.symbol,
                "dimension": limitation.dimension,
                "reason_code": limitation.reason_code,
                "message": limitation.message,
            }
            for limitation in state.limitations
        ],
        "failures": [
            {
                "route_id": failure.route_id,
                "reason_code": failure.reason_code,
                "message": failure.message,
            }
            for failure in state.failures
        ],
    }


def validate_supervisor_report_output(
    raw_output: Mapping[str, Any],
    *,
    state: SupervisorState,
) -> SupervisorReport:
    """Validate final report sections against exact worker finding provenance."""

    if not isinstance(raw_output, Mapping):
        raise SupervisorReportContractError(
            "Supervisor report output must be an object."
        )

    allowed_top = {
        "sections",
        "limitations",
    }
    unknown = set(raw_output) - allowed_top

    if unknown:
        raise SupervisorReportContractError(
            f"Supervisor report output has unknown fields: {sorted(unknown)}."
        )

    raw_sections = raw_output.get(
        "sections"
    )

    if not isinstance(raw_sections, list):
        raise SupervisorReportContractError(
            "Supervisor report sections must be a list."
        )

    raw_limitations = raw_output.get(
        "limitations"
    )

    if not isinstance(raw_limitations, list):
        raise SupervisorReportContractError(
            "Supervisor report limitations must be a list."
        )

    source_findings = {
        item.source_finding_id: item
        for item in _source_findings(state)
    }
    sections: list[ReportSection] = []
    seen_sections: set[str] = set()

    required_sections = list(
        REQUIRED_BASE_SECTIONS
    )

    if state.request.mode == "comparison":
        required_sections.append(
            "comparative_assessment"
        )

    for raw_section in raw_sections:
        section = _parse_section(
            raw_section,
            source_findings=source_findings,
            mode=state.request.mode,
        )

        if section.section in seen_sections:
            raise SupervisorReportContractError(
                f"Duplicate report section: {section.section!r}."
            )

        seen_sections.add(
            section.section
        )
        sections.append(
            section
        )

    missing = [
        section
        for section in required_sections
        if section not in seen_sections
    ]

    if missing:
        raise SupervisorReportContractError(
            f"Supervisor report is missing required sections: {missing}."
        )

    if (
        state.request.mode == "single_company"
        and "comparative_assessment" in seen_sections
    ):
        raise SupervisorReportContractError(
            "Single-company reports must not contain comparative_assessment."
        )

    limitations = _parse_limitations(
        raw_limitations,
        state=state,
    )
    evidence = _evidence_citations(
        sections,
        source_findings=source_findings,
    )

    return SupervisorReport(
        mode=state.request.mode,
        symbols=state.request.requested_symbols,
        status=state.status,
        sections=tuple(sections),
        limitations=limitations,
        evidence=evidence,
    )


def _source_findings(
    state: SupervisorState,
) -> tuple[ReportSourceFinding, ...]:
    findings: list[ReportSourceFinding] = []

    for outcome in state.outcomes:
        result = outcome.result

        if isinstance(
            result,
            MarketAnalystResult,
        ):
            for finding in result.findings:
                findings.append(
                    ReportSourceFinding(
                        source_finding_id=(
                            f"{outcome.route_id}:{finding.finding_id}"
                        ),
                        route_id=outcome.route_id,
                        symbols=finding.symbols,
                        statement=finding.statement,
                        metric_references=tuple(
                            _metric_reference_text(
                                reference
                            )
                            for reference
                            in finding.metric_references
                        ),
                        evidence_ids=(),
                        dimension_or_topic=finding.dimension,
                    )
                )

        elif isinstance(
            result,
            CompanyResearcherResult,
        ):
            for finding in result.findings:
                findings.append(
                    ReportSourceFinding(
                        source_finding_id=(
                            f"{outcome.route_id}:{finding.finding_id}"
                        ),
                        route_id=outcome.route_id,
                        symbols=finding.symbols,
                        statement=finding.statement,
                        metric_references=(),
                        evidence_ids=finding.evidence_ids,
                        dimension_or_topic=finding.topic,
                    )
                )

    ids = [
        finding.source_finding_id
        for finding in findings
    ]

    if len(set(ids)) != len(ids):
        raise SupervisorReportContractError(
            "Worker finding IDs are not unique after route qualification."
        )

    return tuple(findings)


def _metric_reference_text(
    reference,
) -> str:
    return (
        f"{reference.dataset}:"
        f"{reference.symbol}:"
        f"{reference.as_of_date}:"
        f"{'|'.join(reference.fields)}"
    )


def _parse_section(
    raw: object,
    *,
    source_findings: Mapping[str, ReportSourceFinding],
    mode: str,
) -> ReportSection:
    if not isinstance(raw, Mapping):
        raise SupervisorReportContractError(
            "Each Supervisor report section must be an object."
        )

    allowed = {
        "section",
        "text",
        "source_finding_ids",
    }
    unknown = set(raw) - allowed

    if unknown:
        raise SupervisorReportContractError(
            f"Report section has unknown fields: {sorted(unknown)}."
        )

    section = raw.get(
        "section"
    )

    allowed_sections = set(
        REQUIRED_BASE_SECTIONS
    ) | {"comparative_assessment"}

    if section not in allowed_sections:
        raise SupervisorReportContractError(
            f"Unknown report section: {section!r}."
        )

    text = _required_text(
        raw.get("text"),
        "section text",
    )
    raw_ids = raw.get(
        "source_finding_ids"
    )

    if not isinstance(raw_ids, list):
        raise SupervisorReportContractError(
            "source_finding_ids must be a list."
        )

    if not raw_ids:
        raise SupervisorReportContractError(
            f"Report section {section!r} requires source_finding_ids."
        )

    source_ids = tuple(
        _required_text(
            value,
            "source_finding_id",
        )
        for value in raw_ids
    )

    if len(set(source_ids)) != len(source_ids):
        raise SupervisorReportContractError(
            "source_finding_ids must be unique within a section."
        )

    missing = [
        value
        for value in source_ids
        if value not in source_findings
    ]

    if missing:
        raise SupervisorReportContractError(
            f"Report section cites unknown worker findings: {missing}."
        )

    _validate_section_sources(
        section=section,
        source_ids=source_ids,
        source_findings=source_findings,
        mode=mode,
    )

    return ReportSection(
        section=section,
        text=text,
        source_finding_ids=source_ids,
    )


def _validate_section_sources(
    *,
    section: str,
    source_ids: Sequence[str],
    source_findings: Mapping[str, ReportSourceFinding],
    mode: str,
) -> None:
    sources = tuple(
        source_findings[source_id]
        for source_id in source_ids
    )

    if section == "market_performance":
        if any(
            source.route_id != "market_analysis"
            or source.dimension_or_topic != "market"
            for source in sources
        ):
            raise SupervisorReportContractError(
                "market_performance may cite only market-analysis market findings."
            )
        return

    if section == "fundamental_performance":
        if any(
            source.route_id != "market_analysis"
            or source.dimension_or_topic != "fundamental"
            for source in sources
        ):
            raise SupervisorReportContractError(
                "fundamental_performance may cite only fundamental findings."
            )
        return

    if section == "recent_developments":
        if any(
            source.route_id != "recent_developments"
            for source in sources
        ):
            raise SupervisorReportContractError(
                "recent_developments may cite only recent-development findings."
            )
        return

    if section == "principal_risks":
        if any(
            source.route_id != "principal_risks"
            for source in sources
        ):
            raise SupervisorReportContractError(
                "principal_risks may cite only principal-risk findings."
            )
        return

    if section == "comparative_assessment":
        if mode != "comparison":
            raise SupervisorReportContractError(
                "comparative_assessment is allowed only for comparison requests."
            )

        symbols = {
            symbol
            for source in sources
            for symbol in source.symbols
        }

        if len(symbols) < 2:
            raise SupervisorReportContractError(
                "comparative_assessment must cite findings covering both companies."
            )


def _parse_limitations(
    raw_limitations: Sequence[object],
    *,
    state: SupervisorState,
) -> tuple[str, ...]:
    values = tuple(
        _required_text(
            value,
            "report limitation",
        )
        for value in raw_limitations
    )

    if len(set(values)) != len(values):
        raise SupervisorReportContractError(
            "Report limitations must be unique."
        )

    if (
        state.status != "ready"
        and not values
    ):
        raise SupervisorReportContractError(
            "Degraded or unavailable reports require explicit limitations."
        )

    return values


def _evidence_citations(
    sections: Sequence[ReportSection],
    *,
    source_findings: Mapping[str, ReportSourceFinding],
) -> tuple[EvidenceCitation, ...]:
    by_evidence: dict[str, list[str]] = {}

    for section in sections:
        for source_id in section.source_finding_ids:
            source = source_findings[
                source_id
            ]

            for evidence_id in source.evidence_ids:
                source_ids = by_evidence.setdefault(
                    evidence_id,
                    [],
                )

                if source_id not in source_ids:
                    source_ids.append(
                        source_id
                    )

    return tuple(
        EvidenceCitation(
            evidence_id=evidence_id,
            source_finding_ids=tuple(source_ids),
        )
        for evidence_id, source_ids in by_evidence.items()
    )


def _required_text(
    value: object,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SupervisorReportContractError(
            f"{field} must be a nonblank string."
        )

    return value.strip()
