"""MLflow GenAI evaluation helpers for validated Supervisor reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from mlflow.genai.scorers import (
    Guidelines,
    RelevanceToQuery,
    Safety,
    scorer,
)

from equity_research.supervisor_report import SupervisorReport


LIVE_EVALUATION_CASES: dict[str, dict[str, Any]] = {
    "E1": {
        "inputs": {
            "request_text": (
                "Research AAPL and summarize market performance, fundamentals, "
                "recent developments, and principal risks."
            ),
            "requested_symbols": ["AAPL"],
        },
        "expectations": {
            "expected_mode": "single_company",
            "expected_symbols": ["AAPL"],
            "required_sections": [
                "market_performance",
                "fundamental_performance",
                "recent_developments",
                "principal_risks",
            ],
        },
    },
    "E2": {
        "inputs": {
            "request_text": (
                "Compare AAPL and MSFT. Which has stronger recent market and "
                "financial performance, and what developments and risks matter?"
            ),
            "requested_symbols": ["AAPL", "MSFT"],
        },
        "expectations": {
            "expected_mode": "comparison",
            "expected_symbols": ["AAPL", "MSFT"],
            "required_sections": [
                "market_performance",
                "fundamental_performance",
                "recent_developments",
                "principal_risks",
                "comparative_assessment",
            ],
        },
    },
}


EQUITY_RESEARCH_GUIDELINES = (
    "The response must remain an equity-research report and must not provide "
    "buy, sell, hold, trading, or portfolio-allocation recommendations.",
    "Market-performance and fundamental-performance observations must remain "
    "distinct rather than being merged into one unsupported conclusion.",
    "Narrative developments and risks must be presented as evidence-grounded "
    "observations and must not claim unsupported causality.",
    "Missing, stale, unavailable, or incomplete coverage must be disclosed "
    "rather than replaced with model memory or fabricated facts.",
    "Comparative conclusions must stay limited to dimensions actually supported "
    "for both requested companies and must not become an investment recommendation.",
)


def build_live_evaluation_data(
    case_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """Build frozen E1/E2 live-evaluation rows from the AI research contract."""

    if isinstance(case_ids, (str, bytes)):
        raise ValueError(
            "case_ids must be a sequence of evaluation IDs."
        )

    normalized = tuple(
        str(case_id).strip().upper()
        for case_id in case_ids
    )

    if not normalized:
        raise ValueError(
            "At least one evaluation case is required."
        )

    if len(set(normalized)) != len(normalized):
        raise ValueError(
            "Evaluation case IDs must be unique."
        )

    unknown = [
        case_id
        for case_id in normalized
        if case_id not in LIVE_EVALUATION_CASES
    ]

    if unknown:
        raise ValueError(
            "Unsupported live evaluation case IDs: "
            f"{unknown}. Supported live cases are E1 and E2."
        )

    return [
        {
            "inputs": {
                "request_text": LIVE_EVALUATION_CASES[case_id][
                    "inputs"
                ]["request_text"],
                "requested_symbols": list(
                    LIVE_EVALUATION_CASES[case_id][
                        "inputs"
                    ]["requested_symbols"]
                ),
            },
            "expectations": {
                "expected_mode": LIVE_EVALUATION_CASES[case_id][
                    "expectations"
                ]["expected_mode"],
                "expected_symbols": list(
                    LIVE_EVALUATION_CASES[case_id][
                        "expectations"
                    ]["expected_symbols"]
                ),
                "required_sections": list(
                    LIVE_EVALUATION_CASES[case_id][
                        "expectations"
                    ]["required_sections"]
                ),
            },
        }
        for case_id in normalized
    ]


def serialize_supervisor_report_for_evaluation(
    report: SupervisorReport,
) -> dict[str, Any]:
    """Convert one validated report into a stable JSON-safe evaluation output."""

    if not isinstance(report, SupervisorReport):
        raise TypeError(
            "report must be SupervisorReport."
        )

    sections = [
        {
            "section": section.section,
            "status": section.status,
            "text": section.text,
            "source_finding_ids": list(
                section.source_finding_ids
            ),
        }
        for section in report.sections
    ]

    return {
        "mode": report.mode,
        "symbols": list(
            report.symbols
        ),
        "status": report.status,
        "synthesis_mode": report.synthesis_mode,
        "report_text": _report_text(
            sections
        ),
        "sections": sections,
        "limitations": list(
            report.limitations
        ),
        "evidence_ids": [
            citation.evidence_id
            for citation in report.evidence
        ],
        "evidence_count": len(
            report.evidence
        ),
    }


@scorer
def expected_request_mode(
    outputs: Mapping[str, Any] | None,
    expectations: Mapping[str, Any] | None,
) -> bool:
    """Check that the report mode matches the frozen evaluation expectation."""

    actual = _required_output_text(
        outputs,
        "mode",
    )
    expected = _required_expectation_text(
        expectations,
        "expected_mode",
    )

    return actual == expected


@scorer
def expected_symbol_scope(
    outputs: Mapping[str, Any] | None,
    expectations: Mapping[str, Any] | None,
) -> bool:
    """Check exact configured-company scope in the evaluated output."""

    actual = _required_output_string_list(
        outputs,
        "symbols",
    )
    expected = _required_expectation_string_list(
        expectations,
        "expected_symbols",
    )

    return actual == expected


@scorer
def required_report_sections(
    outputs: Mapping[str, Any] | None,
    expectations: Mapping[str, Any] | None,
) -> bool:
    """Check exact required section presence for the evaluation case."""

    sections = _required_sections(
        outputs
    )
    actual = tuple(
        section["section"]
        for section in sections
    )
    expected = _required_expectation_string_list(
        expectations,
        "required_sections",
    )

    return actual == expected


@scorer
def report_section_grounding_contract(
    outputs: Mapping[str, Any] | None,
) -> bool:
    """Re-score the final section/source-ID publication contract for MLflow."""

    sections = _required_sections(
        outputs
    )

    for section in sections:
        status = section["status"]
        source_ids = section["source_finding_ids"]

        if status in {
            "available",
            "degraded",
        }:
            if not source_ids:
                return False
            continue

        if status == "unavailable":
            if source_ids:
                return False
            continue

        return False

    return True


@scorer
def synthesis_mode(
    outputs: Mapping[str, Any] | None,
) -> str:
    """Expose model/repair/fallback outcome as an evaluation dimension."""

    return _required_output_text(
        outputs,
        "synthesis_mode",
    )


@scorer
def report_status(
    outputs: Mapping[str, Any] | None,
) -> str:
    """Expose ready/degraded/unavailable state as an evaluation dimension."""

    return _required_output_text(
        outputs,
        "status",
    )


@scorer
def evidence_count(
    outputs: Mapping[str, Any] | None,
) -> int:
    """Expose narrative evidence count as a deterministic evaluation metric."""

    if not isinstance(outputs, Mapping):
        raise ValueError(
            "outputs must be an object."
        )

    value = outputs.get(
        "evidence_count"
    )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(
            "outputs.evidence_count must be a nonnegative integer."
        )

    return value


def build_code_scorers() -> list[Any]:
    """Return deterministic scorers used for every report evaluation."""

    return [
        expected_request_mode,
        expected_symbol_scope,
        required_report_sections,
        report_section_grounding_contract,
        synthesis_mode,
        report_status,
        evidence_count,
    ]


def ensure_llm_judge_runtime(
    *,
    model: str,
) -> None:
    """Fail fast when the selected managed judge runtime is unavailable."""

    if model != "databricks":
        return

    try:
        import databricks.agents.evals.judges  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Databricks-managed MLflow judges require the databricks-agents "
            "runtime. Install the repository requirements, which use "
            "mlflow[databricks]==3.16.0."
        ) from exc


def build_llm_judges(
    *,
    model: str = "databricks",
) -> list[Any]:
    """Return semantic Databricks judges for report-level quality."""

    if not isinstance(model, str) or not model.strip():
        raise ValueError(
            "model must be a nonblank string."
        )

    judge_model = model.strip()

    ensure_llm_judge_runtime(
        model=judge_model
    )

    return [
        RelevanceToQuery(
            model=judge_model
        ),
        Safety(
            model=judge_model
        ),
        Guidelines(
            name="equity_research_guidelines",
            guidelines=list(
                EQUITY_RESEARCH_GUIDELINES
            ),
            model=judge_model,
        ),
    ]


def build_evaluation_scorers(
    *,
    include_llm_judges: bool,
    judge_model: str = "databricks",
) -> list[Any]:
    """Compose deterministic scorers and optional semantic LLM judges."""

    values = build_code_scorers()

    if include_llm_judges:
        values.extend(
            build_llm_judges(
                model=judge_model
            )
        )

    return values


def _report_text(
    sections: Sequence[Mapping[str, Any]],
) -> str:
    blocks = []

    for section in sections:
        name = section[
            "section"
        ]
        status = section[
            "status"
        ]
        text = section[
            "text"
        ]
        blocks.append(
            f"{name} [{status}]: {text}"
        )

    return "\n\n".join(
        blocks
    )


def _required_sections(
    outputs: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(outputs, Mapping):
        raise ValueError(
            "outputs must be an object."
        )

    raw_sections = outputs.get(
        "sections"
    )

    if not isinstance(raw_sections, list):
        raise ValueError(
            "outputs.sections must be a list."
        )

    sections = []

    for raw in raw_sections:
        if not isinstance(raw, Mapping):
            raise ValueError(
                "outputs.sections entries must be objects."
            )

        section = _required_mapping_text(
            raw,
            "section",
        )
        status = _required_mapping_text(
            raw,
            "status",
        )
        text = _required_mapping_text(
            raw,
            "text",
        )
        source_ids = raw.get(
            "source_finding_ids"
        )

        if (
            not isinstance(source_ids, list)
            or any(
                not isinstance(value, str)
                or not value.strip()
                for value in source_ids
            )
        ):
            raise ValueError(
                "section source_finding_ids must be a list of nonblank strings."
            )

        sections.append(
            {
                "section": section,
                "status": status,
                "text": text,
                "source_finding_ids": tuple(
                    value.strip()
                    for value in source_ids
                ),
            }
        )

    return tuple(
        sections
    )


def _required_output_text(
    outputs: Mapping[str, Any] | None,
    field: str,
) -> str:
    if not isinstance(outputs, Mapping):
        raise ValueError(
            "outputs must be an object."
        )

    return _required_mapping_text(
        outputs,
        field,
    )


def _required_expectation_text(
    expectations: Mapping[str, Any] | None,
    field: str,
) -> str:
    if not isinstance(expectations, Mapping):
        raise ValueError(
            "expectations must be an object."
        )

    return _required_mapping_text(
        expectations,
        field,
    )


def _required_output_string_list(
    outputs: Mapping[str, Any] | None,
    field: str,
) -> tuple[str, ...]:
    if not isinstance(outputs, Mapping):
        raise ValueError(
            "outputs must be an object."
        )

    return _required_string_list(
        outputs.get(
            field
        ),
        f"outputs.{field}",
    )


def _required_expectation_string_list(
    expectations: Mapping[str, Any] | None,
    field: str,
) -> tuple[str, ...]:
    if not isinstance(expectations, Mapping):
        raise ValueError(
            "expectations must be an object."
        )

    return _required_string_list(
        expectations.get(
            field
        ),
        f"expectations.{field}",
    )


def _required_string_list(
    value: object,
    field: str,
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(
            not isinstance(item, str)
            or not item.strip()
            for item in value
        )
    ):
        raise ValueError(
            f"{field} must be a nonempty list of nonblank strings."
        )

    return tuple(
        item.strip()
        for item in value
    )


def _required_mapping_text(
    value: Mapping[str, Any],
    field: str,
) -> str:
    raw = value.get(
        field
    )

    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(
            f"{field} must be a nonblank string."
        )

    return raw.strip()
