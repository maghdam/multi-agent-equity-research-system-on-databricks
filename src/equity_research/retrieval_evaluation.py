"""Deterministic retrieval-evaluation helpers for the RAG baseline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


SUPPORTED_CUTOFFS = (1, 3, 5)


@dataclass(frozen=True)
class RetrievalEvalCase:
    """Human-labelled expectations for one retrieval query."""

    case_id: str
    query: str
    expected_symbol: str
    expected_source_type: str
    expected_section_code: str | None
    relevant_chunk_ids: frozenset[str]


@dataclass(frozen=True)
class RetrievedChunk:
    """Minimal retrieval result needed for deterministic evaluation."""

    chunk_id: str
    document_id: str
    source_type: str
    configured_symbols: tuple[str, ...]
    section_code: str | None


@dataclass(frozen=True)
class RetrievalCaseMetrics:
    """Metrics for one labelled retrieval case."""

    case_id: str
    hit_at_1: float
    hit_at_3: float
    hit_at_5: float
    reciprocal_rank: float
    symbol_match_at_5: float
    source_type_match_at_5: float
    section_match_at_5: float | None
    duplicate_document_rate_at_5: float


@dataclass(frozen=True)
class RetrievalSuiteMetrics:
    """Macro-averaged metrics across labelled retrieval cases."""

    case_count: int
    hit_at_1: float
    hit_at_3: float
    hit_at_5: float
    mean_reciprocal_rank: float
    symbol_match_at_5: float
    source_type_match_at_5: float
    section_match_at_5: float | None
    duplicate_document_rate_at_5: float


def _require_non_empty(value: str, field_name: str) -> str:
    cleaned = value.strip()

    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty.")

    return cleaned


def validate_eval_case(case: RetrievalEvalCase) -> None:
    """Validate one reviewed retrieval case."""

    _require_non_empty(case.case_id, "case_id")
    _require_non_empty(case.query, "query")
    _require_non_empty(case.expected_symbol, "expected_symbol")
    _require_non_empty(
        case.expected_source_type,
        "expected_source_type",
    )

    if not case.relevant_chunk_ids:
        raise ValueError(
            "relevant_chunk_ids must contain at least one "
            f"human-reviewed chunk for case {case.case_id!r}."
        )

    for chunk_id in case.relevant_chunk_ids:
        _require_non_empty(chunk_id, "relevant_chunk_id")

    if case.expected_section_code is not None:
        _require_non_empty(
            case.expected_section_code,
            "expected_section_code",
        )


def validate_retrieved_chunk(chunk: RetrievedChunk) -> None:
    """Validate one retrieval result before metric calculation."""

    _require_non_empty(chunk.chunk_id, "chunk_id")
    _require_non_empty(chunk.document_id, "document_id")
    _require_non_empty(chunk.source_type, "source_type")

    if not chunk.configured_symbols:
        raise ValueError("configured_symbols must not be empty.")

    for symbol in chunk.configured_symbols:
        _require_non_empty(symbol, "configured_symbol")

    if chunk.section_code is not None:
        _require_non_empty(chunk.section_code, "section_code")


def _top_k(
    retrieved: Sequence[RetrievedChunk],
    k: int,
) -> Sequence[RetrievedChunk]:
    if k <= 0:
        raise ValueError("k must be greater than zero.")

    return retrieved[:k]


def hit_at_k(
    relevant_chunk_ids: frozenset[str],
    retrieved: Sequence[RetrievedChunk],
    k: int,
) -> float:
    """Return 1.0 when any labelled relevant chunk occurs in top-k."""

    return float(
        any(
            chunk.chunk_id in relevant_chunk_ids
            for chunk in _top_k(retrieved, k)
        )
    )


def reciprocal_rank(
    relevant_chunk_ids: frozenset[str],
    retrieved: Sequence[RetrievedChunk],
) -> float:
    """Return reciprocal rank of the first labelled relevant chunk."""

    for rank, chunk in enumerate(retrieved, start=1):
        if chunk.chunk_id in relevant_chunk_ids:
            return 1.0 / rank

    return 0.0


def symbol_match_at_k(
    expected_symbol: str,
    retrieved: Sequence[RetrievedChunk],
    k: int,
) -> float:
    """Return fraction of top-k chunks associated with expected symbol."""

    top = _top_k(retrieved, k)

    if not top:
        return 0.0

    matches = sum(
        expected_symbol in chunk.configured_symbols
        for chunk in top
    )

    return matches / len(top)


def source_type_match_at_k(
    expected_source_type: str,
    retrieved: Sequence[RetrievedChunk],
    k: int,
) -> float:
    """Return fraction of top-k chunks matching expected source type."""

    top = _top_k(retrieved, k)

    if not top:
        return 0.0

    matches = sum(
        chunk.source_type == expected_source_type
        for chunk in top
    )

    return matches / len(top)


def section_match_at_k(
    expected_section_code: str | None,
    retrieved: Sequence[RetrievedChunk],
    k: int,
) -> float | None:
    """Return top-k section match rate when a section is expected."""

    if expected_section_code is None:
        return None

    top = _top_k(retrieved, k)

    if not top:
        return 0.0

    matches = sum(
        chunk.section_code == expected_section_code
        for chunk in top
    )

    return matches / len(top)


def duplicate_document_rate_at_k(
    retrieved: Sequence[RetrievedChunk],
    k: int,
) -> float:
    """Return fraction of top-k slots occupied by duplicate documents."""

    top = _top_k(retrieved, k)

    if not top:
        return 0.0

    distinct_documents = {
        chunk.document_id
        for chunk in top
    }

    duplicate_count = len(top) - len(distinct_documents)

    return duplicate_count / len(top)


def evaluate_case(
    case: RetrievalEvalCase,
    retrieved: Sequence[RetrievedChunk],
) -> RetrievalCaseMetrics:
    """Evaluate one ranked retrieval result against human labels."""

    validate_eval_case(case)

    for chunk in retrieved:
        validate_retrieved_chunk(chunk)

    return RetrievalCaseMetrics(
        case_id=case.case_id,
        hit_at_1=hit_at_k(
            case.relevant_chunk_ids,
            retrieved,
            1,
        ),
        hit_at_3=hit_at_k(
            case.relevant_chunk_ids,
            retrieved,
            3,
        ),
        hit_at_5=hit_at_k(
            case.relevant_chunk_ids,
            retrieved,
            5,
        ),
        reciprocal_rank=reciprocal_rank(
            case.relevant_chunk_ids,
            retrieved,
        ),
        symbol_match_at_5=symbol_match_at_k(
            case.expected_symbol,
            retrieved,
            5,
        ),
        source_type_match_at_5=source_type_match_at_k(
            case.expected_source_type,
            retrieved,
            5,
        ),
        section_match_at_5=section_match_at_k(
            case.expected_section_code,
            retrieved,
            5,
        ),
        duplicate_document_rate_at_5=(
            duplicate_document_rate_at_k(
                retrieved,
                5,
            )
        ),
    )


def _mean(values: Iterable[float]) -> float:
    collected = tuple(values)

    if not collected:
        raise ValueError(
            "At least one metric value is required."
        )

    return sum(collected) / len(collected)


def aggregate_case_metrics(
    metrics: Sequence[RetrievalCaseMetrics],
) -> RetrievalSuiteMetrics:
    """Macro-average retrieval metrics across evaluated cases."""

    if not metrics:
        raise ValueError(
            "At least one evaluated retrieval case is required."
        )

    section_values = tuple(
        metric.section_match_at_5
        for metric in metrics
        if metric.section_match_at_5 is not None
    )

    section_match = (
        _mean(section_values)
        if section_values
        else None
    )

    return RetrievalSuiteMetrics(
        case_count=len(metrics),
        hit_at_1=_mean(
            metric.hit_at_1
            for metric in metrics
        ),
        hit_at_3=_mean(
            metric.hit_at_3
            for metric in metrics
        ),
        hit_at_5=_mean(
            metric.hit_at_5
            for metric in metrics
        ),
        mean_reciprocal_rank=_mean(
            metric.reciprocal_rank
            for metric in metrics
        ),
        symbol_match_at_5=_mean(
            metric.symbol_match_at_5
            for metric in metrics
        ),
        source_type_match_at_5=_mean(
            metric.source_type_match_at_5
            for metric in metrics
        ),
        section_match_at_5=section_match,
        duplicate_document_rate_at_5=_mean(
            metric.duplicate_document_rate_at_5
            for metric in metrics
        ),
    )
