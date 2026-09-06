"""Controlled HYBRID retrieval requests and citation-ready evidence parsing."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

from equity_research.config import Equity, load_equities
from equity_research.structured_data_tools import ControlledToolDataError
from equity_research.tool_scope import resolve_requested_equities


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
MAX_RETRIEVAL_RESULTS = 10
DEFAULT_RETRIEVAL_RESULTS = 5
RETRIEVAL_QUERY_TYPE = "HYBRID"

SourceType = Literal["news", "filing"]

RETRIEVAL_COLUMNS = (
    "chunk_id",
    "document_id",
    "document_version_id",
    "source_type",
    "source_system",
    "configured_symbols",
    "title",
    "evidence_date",
    "source_url",
    "section_code",
    "section_title",
    "chunk_index",
    "chunk_text",
    "source_response_id",
    "source_fetched_at",
    "source_ingestion_run_id",
)


@dataclass(frozen=True)
class EvidenceRecord:
    """One validated retrieval result that may be cited by an agent."""

    evidence_id: str
    retrieval_rank: int
    chunk_id: str
    document_id: str
    document_version_id: str
    source_type: SourceType
    source_system: str
    configured_symbols: tuple[str, ...]
    title: str
    evidence_date: date
    source_url: str
    source_business_id: str
    section_code: str | None
    section_title: str | None
    chunk_index: int
    text: str
    source_response_id: str
    source_fetched_at: datetime
    source_ingestion_run_id: str


def build_retrieval_query_payload(
    *,
    query_text: str,
    requested_symbols: Sequence[str],
    source_type: SourceType | None = None,
    section_code: str | None = None,
    num_results: int = DEFAULT_RETRIEVAL_RESULTS,
    equities: Mapping[str, Equity] | None = None,
) -> dict[str, Any]:
    """Build one controlled Vector Search query using the HYBRID baseline."""

    requested = resolve_requested_equities(
        requested_symbols,
        equities=equities,
    )
    normalized_query = _required_text(
        query_text,
        "query_text",
    )

    if (
        isinstance(num_results, bool)
        or not isinstance(num_results, int)
        or not 1 <= num_results <= MAX_RETRIEVAL_RESULTS
    ):
        raise ControlledToolDataError(
            f"num_results must be an integer between 1 and "
            f"{MAX_RETRIEVAL_RESULTS}."
        )

    if source_type not in {None, "news", "filing"}:
        raise ControlledToolDataError(
            "source_type must be 'news', 'filing', or None."
        )

    normalized_section = None

    if section_code is not None:
        normalized_section = _required_text(
            section_code,
            "section_code",
        )

        if source_type != "filing":
            raise ControlledToolDataError(
                "section_code filtering requires source_type='filing'."
            )

    requested_values = tuple(
        equity.symbol
        for equity in requested
    )

    filters: dict[str, Any] = {
        "configured_symbols": (
            requested_values[0]
            if len(requested_values) == 1
            else list(requested_values)
        )
    }

    if source_type is not None:
        filters["source_type"] = source_type

    if normalized_section is not None:
        filters["section_code"] = normalized_section

    return {
        "columns": list(RETRIEVAL_COLUMNS),
        "num_results": num_results,
        "query_text": normalized_query,
        "query_type": RETRIEVAL_QUERY_TYPE,
        "filters_json": json.dumps(
            filters,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def parse_retrieval_response(
    response: Mapping[str, Any],
    *,
    requested_symbols: Sequence[str],
    expected_source_type: SourceType | None = None,
    equities: Mapping[str, Equity] | None = None,
) -> tuple[EvidenceRecord, ...]:
    """Validate a Vector Search response and return citation-ready evidence."""

    configured = (
        dict(load_equities())
        if equities is None
        else dict(equities)
    )
    requested = resolve_requested_equities(
        requested_symbols,
        equities=configured,
    )
    requested_set = {
        equity.symbol
        for equity in requested
    }

    if expected_source_type not in {
        None,
        "news",
        "filing",
    }:
        raise ControlledToolDataError(
            "expected_source_type must be 'news', 'filing', or None."
        )

    if not isinstance(response, Mapping):
        raise ControlledToolDataError(
            "Vector Search response must be a mapping."
        )

    manifest = response.get("manifest")
    if not isinstance(manifest, Mapping):
        raise ControlledToolDataError(
            "Vector Search response is missing its manifest."
        )

    raw_columns = manifest.get("columns")
    if not isinstance(raw_columns, list):
        raise ControlledToolDataError(
            "Vector Search manifest is missing columns."
        )

    column_names = tuple(
        column.get("name")
        for column in raw_columns
        if isinstance(column, Mapping)
    )

    missing_columns = [
        column
        for column in RETRIEVAL_COLUMNS
        if column not in column_names
    ]

    if missing_columns:
        raise ControlledToolDataError(
            "Vector Search response is missing controlled columns: "
            f"{missing_columns}."
        )

    result = response.get("result")
    if not isinstance(result, Mapping):
        raise ControlledToolDataError(
            "Vector Search response is missing result data."
        )

    data_array = result.get("data_array", [])
    if not isinstance(data_array, list):
        raise ControlledToolDataError(
            "Vector Search data_array must be a list."
        )

    evidence: list[EvidenceRecord] = []

    for rank, raw_row in enumerate(
        data_array,
        start=1,
    ):
        if not isinstance(raw_row, list):
            raise ControlledToolDataError(
                "Vector Search rows must be arrays."
            )

        if len(raw_row) != len(column_names):
            raise ControlledToolDataError(
                "Vector Search row width does not match its manifest."
            )

        row = dict(
            zip(
                column_names,
                raw_row,
                strict=True,
            )
        )

        evidence.append(
            _parse_evidence_row(
                row,
                rank=rank,
                requested_symbols=requested_set,
                configured_symbols=set(configured),
                expected_source_type=expected_source_type,
            )
        )

    return tuple(evidence)


def _parse_evidence_row(
    row: Mapping[str, Any],
    *,
    rank: int,
    requested_symbols: set[str],
    configured_symbols: set[str],
    expected_source_type: SourceType | None,
) -> EvidenceRecord:
    chunk_id = _required_text(
        row["chunk_id"],
        "chunk_id",
    )

    if not SHA256_PATTERN.fullmatch(chunk_id):
        raise ControlledToolDataError(
            "chunk_id must be a lowercase SHA-256 value."
        )

    document_id = _required_text(
        row["document_id"],
        "document_id",
    )
    document_version_id = _required_text(
        row["document_version_id"],
        "document_version_id",
    )

    source_type = row["source_type"]

    if source_type not in {"news", "filing"}:
        raise ControlledToolDataError(
            "retrieval source_type is outside the controlled scope."
        )

    if (
        expected_source_type is not None
        and source_type != expected_source_type
    ):
        raise ControlledToolDataError(
            "retrieval result does not match the requested source_type."
        )

    source_system = _required_text(
        row["source_system"],
        "source_system",
    )

    expected_source_system = (
        "alpaca"
        if source_type == "news"
        else "sec"
    )

    if source_system != expected_source_system:
        raise ControlledToolDataError(
            "retrieval source_system does not match source_type."
        )

    symbols = _parse_symbols(
        row["configured_symbols"],
    )

    if not set(symbols).issubset(
        configured_symbols
    ):
        raise ControlledToolDataError(
            "retrieval result contains an unsupported configured symbol."
        )

    if not set(symbols).intersection(
        requested_symbols
    ):
        raise ControlledToolDataError(
            "retrieval result falls outside the requested company scope."
        )

    title = _required_text(
        row["title"],
        "title",
    )
    evidence_date = _parse_date(
        row["evidence_date"],
        "evidence_date",
    )
    source_url = _required_url(
        row["source_url"],
    )
    section_code = _optional_text(
        row["section_code"],
        "section_code",
    )
    section_title = _optional_text(
        row["section_title"],
        "section_title",
    )

    if source_type == "news":
        if section_code is not None or section_title is not None:
            raise ControlledToolDataError(
                "news retrieval rows must not carry filing-section metadata."
            )
    else:
        if section_code is None or section_title is None:
            raise ControlledToolDataError(
                "filing retrieval rows require section metadata."
            )

    chunk_index = _parse_nonnegative_int(
        row["chunk_index"],
        "chunk_index",
    )
    text = _required_text(
        row["chunk_text"],
        "chunk_text",
    )

    source_business_id = _source_business_id(
        document_id=document_id,
        source_type=source_type,
        section_code=section_code,
    )

    return EvidenceRecord(
        evidence_id=chunk_id,
        retrieval_rank=rank,
        chunk_id=chunk_id,
        document_id=document_id,
        document_version_id=document_version_id,
        source_type=source_type,
        source_system=source_system,
        configured_symbols=symbols,
        title=title,
        evidence_date=evidence_date,
        source_url=source_url,
        source_business_id=source_business_id,
        section_code=section_code,
        section_title=section_title,
        chunk_index=chunk_index,
        text=text,
        source_response_id=_required_text(
            row["source_response_id"],
            "source_response_id",
        ),
        source_fetched_at=_parse_datetime(
            row["source_fetched_at"],
            "source_fetched_at",
        ),
        source_ingestion_run_id=_required_text(
            row["source_ingestion_run_id"],
            "source_ingestion_run_id",
        ),
    )


def _parse_symbols(
    value: object,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ControlledToolDataError(
            "configured_symbols must be an array."
        )

    symbols = tuple(
        _required_text(
            item,
            "configured symbol",
        )
        for item in value
    )

    if not symbols:
        raise ControlledToolDataError(
            "configured_symbols must not be empty."
        )

    if tuple(sorted(set(symbols))) != symbols:
        raise ControlledToolDataError(
            "configured_symbols must be sorted and unique."
        )

    return symbols


def _source_business_id(
    *,
    document_id: str,
    source_type: SourceType,
    section_code: str | None,
) -> str:
    if source_type == "news":
        prefix = "alpaca:news:"

        if not document_id.startswith(prefix):
            raise ControlledToolDataError(
                "news document_id has an invalid controlled identity."
            )

        return _required_text(
            document_id[len(prefix):],
            "news article identity",
        )

    prefix = "sec:filing:"

    if not document_id.startswith(prefix):
        raise ControlledToolDataError(
            "filing document_id has an invalid controlled identity."
        )

    remainder = document_id[len(prefix):]

    if ":" not in remainder:
        raise ControlledToolDataError(
            "filing document_id is missing its section identity."
        )

    accession_number, document_section = remainder.rsplit(
        ":",
        1,
    )

    if (
        section_code is None
        or document_section != section_code
    ):
        raise ControlledToolDataError(
            "filing document_id section does not match section_code."
        )

    return _required_text(
        accession_number,
        "filing accession identity",
    )


def _required_url(
    value: object,
) -> str:
    url = _required_text(
        value,
        "source_url",
    )
    parsed = urlparse(url)

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
    ):
        raise ControlledToolDataError(
            "source_url must be an absolute HTTP(S) URL."
        )

    return url


def _parse_date(
    value: object,
    field: str,
) -> date:
    text = _required_text(
        value,
        field,
    )

    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ControlledToolDataError(
            f"{field} must be an ISO date."
        ) from exc


def _parse_datetime(
    value: object,
    field: str,
) -> datetime:
    text = _required_text(
        value,
        field,
    )

    try:
        parsed = datetime.fromisoformat(
            text.replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError as exc:
        raise ControlledToolDataError(
            f"{field} must be an ISO timestamp."
        ) from exc

    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        return parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


def _parse_nonnegative_int(
    value: object,
    field: str,
) -> int:
    if isinstance(value, bool):
        raise ControlledToolDataError(
            f"{field} must be a nonnegative integer."
        )

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ControlledToolDataError(
            f"{field} must be a nonnegative integer."
        ) from exc

    if parsed < 0:
        raise ControlledToolDataError(
            f"{field} must be a nonnegative integer."
        )

    return parsed


def _optional_text(
    value: object,
    field: str,
) -> str | None:
    if value is None:
        return None

    return _required_text(
        value,
        field,
    )


def _required_text(
    value: object,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ControlledToolDataError(
            f"{field} must be a nonblank string."
        )

    return value.strip()
