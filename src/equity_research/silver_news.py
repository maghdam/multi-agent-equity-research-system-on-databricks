"""Pure transformation logic for Silver company-news records."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from equity_research.alpaca_news import parse_news_response_page


@dataclass(frozen=True)
class NewsValidationIssue:
    """One validation rule violated by a Bronze news observation."""

    code: str
    field: str | None = None


@dataclass(frozen=True)
class SilverNewsCandidate:
    """One validated Alpaca news observation before version selection."""

    source_system: str
    article_id: int
    headline: str
    symbols: tuple[str, ...]
    article_created_at: datetime
    article_updated_at: datetime
    article_source: str
    url: str
    summary: str | None
    content: str | None
    source_response_id: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class RejectedNewsArticle:
    """Validation result for one article excluded before version selection."""

    article_index: int
    article_id: int | None
    issues: tuple[NewsValidationIssue, ...]
    source_response_id: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class NewsResponseTransformResult:
    """Validated and rejected observations from one Bronze response."""

    accepted: tuple[SilverNewsCandidate, ...]
    rejected: tuple[RejectedNewsArticle, ...]

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

@dataclass(frozen=True)
class NewsVersionSelectionResult:
    """Current validated article versions selected from Bronze history."""

    selected: tuple[SilverNewsCandidate, ...]
    duplicate_count: int
    superseded_count: int

    @property
    def selected_count(self) -> int:
        return len(self.selected)

@dataclass(frozen=True)
class BronzeNewsResponse:
    """Stored Bronze response fields required for Silver transformation."""

    source_system: str
    source_response_id: str
    response_payload_json: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class SilverNewsArticle:
    """One selected in-scope Silver company-news article."""

    source_system: str
    article_id: int
    headline: str
    symbols: tuple[str, ...]
    configured_symbols: tuple[str, ...]
    article_created_at: datetime
    article_updated_at: datetime
    article_source: str
    url: str
    summary: str | None
    content: str | None
    source_response_id: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class NewsSnapshotTransformResult:
    """Complete result of rebuilding the current news snapshot."""

    selected: tuple[SilverNewsArticle, ...]
    rejected: tuple[RejectedNewsArticle, ...]
    bronze_response_count: int
    accepted_candidate_count: int
    out_of_scope_count: int
    duplicate_count: int
    superseded_count: int

    @property
    def selected_count(self) -> int:
        return len(self.selected)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

def transform_news_response(
    *,
    response_payload_json: str,
    source_system: str,
    source_response_id: str,
    fetched_at: datetime,
    ingestion_run_id: str,
) -> NewsResponseTransformResult:
    """Validate one stored Bronze Alpaca news response."""

    normalized_source_system = _required_string(
        source_system,
        "source_system",
    )

    if normalized_source_system != "alpaca":
        raise ValueError("source_system must be alpaca.")

    normalized_source_response_id = _required_string(
        source_response_id,
        "source_response_id",
    )

    normalized_ingestion_run_id = _required_string(
        ingestion_run_id,
        "ingestion_run_id",
    )

    normalized_fetched_at = _require_aware_utc(
        fetched_at,
        "fetched_at",
    )

    if not isinstance(response_payload_json, str):
        raise ValueError("response_payload_json must be a string.")

    if not response_payload_json.strip():
        raise ValueError("response_payload_json must be nonblank.")

    try:
        payload = json.loads(response_payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "response_payload_json must contain valid JSON."
        ) from exc

    response_page = parse_news_response_page(payload)

    accepted: list[SilverNewsCandidate] = []
    rejected: list[RejectedNewsArticle] = []

    for article_index, article in enumerate(response_page.articles):
        candidate, issues, article_id = _transform_article(
            article=article,
            fetched_at=normalized_fetched_at,
            source_system=normalized_source_system,
            source_response_id=normalized_source_response_id,
            ingestion_run_id=normalized_ingestion_run_id,
        )

        if candidate is not None:
            accepted.append(candidate)
            continue

        rejected.append(
            RejectedNewsArticle(
                article_index=article_index,
                article_id=article_id,
                issues=tuple(issues),
                source_response_id=normalized_source_response_id,
                fetched_at=normalized_fetched_at,
                ingestion_run_id=normalized_ingestion_run_id,
            )
        )

    return NewsResponseTransformResult(
        accepted=tuple(accepted),
        rejected=tuple(rejected),
    )

def select_current_news_versions(
    candidates: Sequence[SilverNewsCandidate],
) -> NewsVersionSelectionResult:
    """Select one deterministic current version per provider article."""

    grouped_candidates: dict[
        tuple[str, int],
        list[SilverNewsCandidate],
    ] = {}

    for candidate in candidates:
        if not isinstance(candidate, SilverNewsCandidate):
            raise ValueError(
                "candidates must contain SilverNewsCandidate values."
            )

        key = (
            candidate.source_system,
            candidate.article_id,
        )

        grouped_candidates.setdefault(
            key,
            [],
        ).append(candidate)

    selected: list[SilverNewsCandidate] = []
    duplicate_count = 0
    superseded_count = 0

    for key in sorted(grouped_candidates):
        article_candidates = grouped_candidates[key]

        greatest_updated_at = max(
            candidate.article_updated_at
            for candidate in article_candidates
        )

        current_candidates = [
            candidate
            for candidate in article_candidates
            if candidate.article_updated_at
            == greatest_updated_at
        ]

        superseded_count += (
            len(article_candidates)
            - len(current_candidates)
        )

        content_signatures = {
            _news_content_signature(candidate)
            for candidate in current_candidates
        }

        if len(content_signatures) != 1:
            raise ValueError(
                "Conflicting valid observations exist at the "
                "selected article update timestamp."
            )

        current_candidates.sort(
            key=lambda candidate: (
                candidate.fetched_at,
                candidate.ingestion_run_id,
                candidate.source_response_id,
            )
        )

        selected.append(current_candidates[0])

        duplicate_count += len(current_candidates) - 1

    selected.sort(
        key=lambda candidate: (
            candidate.source_system,
            candidate.article_id,
        )
    )

    return NewsVersionSelectionResult(
        selected=tuple(selected),
        duplicate_count=duplicate_count,
        superseded_count=superseded_count,
    )

def transform_news_snapshot(
    *,
    bronze_responses: Sequence[BronzeNewsResponse],
    configured_symbols: Sequence[str],
) -> NewsSnapshotTransformResult:
    """Rebuild the current in-scope Silver news snapshot from Bronze."""

    normalized_configured_symbols = (
        _normalize_configured_symbols(
            configured_symbols
        )
    )

    accepted_candidates: list[
        SilverNewsCandidate
    ] = []

    rejected: list[RejectedNewsArticle] = []

    for bronze_response in bronze_responses:
        if not isinstance(
            bronze_response,
            BronzeNewsResponse,
        ):
            raise ValueError(
                "bronze_responses must contain "
                "BronzeNewsResponse values."
            )

        response_result = transform_news_response(
            response_payload_json=(
                bronze_response.response_payload_json
            ),
            source_system=bronze_response.source_system,
            source_response_id=(
                bronze_response.source_response_id
            ),
            fetched_at=bronze_response.fetched_at,
            ingestion_run_id=(
                bronze_response.ingestion_run_id
            ),
        )

        accepted_candidates.extend(
            response_result.accepted
        )

        rejected.extend(
            response_result.rejected
        )

    version_result = select_current_news_versions(
        accepted_candidates
    )

    selected: list[SilverNewsArticle] = []
    out_of_scope_count = 0

    for candidate in version_result.selected:
        candidate_symbol_set = set(
            candidate.symbols
        )

        configured_article_symbols = tuple(
            symbol
            for symbol in normalized_configured_symbols
            if symbol in candidate_symbol_set
        )

        if not configured_article_symbols:
            out_of_scope_count += 1
            continue

        selected.append(
            SilverNewsArticle(
                source_system=candidate.source_system,
                article_id=candidate.article_id,
                headline=candidate.headline,
                symbols=candidate.symbols,
                configured_symbols=(
                    configured_article_symbols
                ),
                article_created_at=(
                    candidate.article_created_at
                ),
                article_updated_at=(
                    candidate.article_updated_at
                ),
                article_source=(
                    candidate.article_source
                ),
                url=candidate.url,
                summary=candidate.summary,
                content=candidate.content,
                source_response_id=(
                    candidate.source_response_id
                ),
                fetched_at=candidate.fetched_at,
                ingestion_run_id=(
                    candidate.ingestion_run_id
                ),
            )
        )

    return NewsSnapshotTransformResult(
        selected=tuple(selected),
        rejected=tuple(rejected),
        bronze_response_count=len(bronze_responses),
        accepted_candidate_count=len(
            accepted_candidates
        ),
        out_of_scope_count=out_of_scope_count,
        duplicate_count=(
            version_result.duplicate_count
        ),
        superseded_count=(
            version_result.superseded_count
        ),
    )

def _transform_article(
    *,
    article: Mapping[str, object],
    fetched_at: datetime,
    source_system: str,
    source_response_id: str,
    ingestion_run_id: str,
) -> tuple[
    SilverNewsCandidate | None,
    list[NewsValidationIssue],
    int | None,
]:
    """Validate and normalize one provider article."""

    issues: list[NewsValidationIssue] = []

    article_id = _parse_article_id(
        article.get("id"),
        issues,
    )

    headline = _parse_required_article_string(
        article.get("headline"),
        "headline",
        issues,
    )

    symbols = _parse_symbols(
        article.get("symbols"),
        issues,
    )

    article_created_at = _parse_article_timestamp(
        article.get("created_at"),
        "created_at",
        issues,
    )

    article_updated_at = _parse_article_timestamp(
        article.get("updated_at"),
        "updated_at",
        issues,
    )

    article_source = _parse_required_article_string(
        article.get("source"),
        "source",
        issues,
    )

    url = _parse_url(
        article.get("url"),
        issues,
    )

    summary = _parse_optional_string(
        article.get("summary"),
        "summary",
        issues,
    )

    content = _parse_optional_string(
        article.get("content"),
        "content",
        issues,
    )

    if (
        article_created_at is not None
        and article_updated_at is not None
        and article_created_at > article_updated_at
    ):
        issues.append(
            NewsValidationIssue(
                code="created_after_updated",
                field="created_at",
            )
        )

    if (
        article_updated_at is not None
        and article_updated_at > fetched_at
    ):
        issues.append(
            NewsValidationIssue(
                code="updated_after_fetched",
                field="updated_at",
            )
        )

    if issues:
        return None, issues, article_id

    assert article_id is not None
    assert headline is not None
    assert symbols is not None
    assert article_created_at is not None
    assert article_updated_at is not None
    assert article_source is not None
    assert url is not None

    return (
        SilverNewsCandidate(
            source_system=source_system,
            article_id=article_id,
            headline=headline,
            symbols=symbols,
            article_created_at=article_created_at,
            article_updated_at=article_updated_at,
            article_source=article_source,
            url=url,
            summary=summary,
            content=content,
            source_response_id=source_response_id,
            fetched_at=fetched_at,
            ingestion_run_id=ingestion_run_id,
        ),
        issues,
        article_id,
    )


def _parse_article_id(
    value: object,
    issues: list[NewsValidationIssue],
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        issues.append(
            NewsValidationIssue(
                code="invalid_article_id",
                field="id",
            )
        )
        return None

    return value


def _parse_required_article_string(
    value: object,
    field: str,
    issues: list[NewsValidationIssue],
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        issues.append(
            NewsValidationIssue(
                code="invalid_required_string",
                field=field,
            )
        )
        return None

    return value.strip()


def _parse_optional_string(
    value: object,
    field: str,
    issues: list[NewsValidationIssue],
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        issues.append(
            NewsValidationIssue(
                code="invalid_optional_string",
                field=field,
            )
        )
        return None

    normalized = value.strip()

    return normalized or None


def _parse_symbols(
    value: object,
    issues: list[NewsValidationIssue],
) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        issues.append(
            NewsValidationIssue(
                code="invalid_symbols",
                field="symbols",
            )
        )
        return None

    normalized_symbols: list[str] = []

    for symbol in value:
        if not isinstance(symbol, str) or not symbol.strip():
            issues.append(
                NewsValidationIssue(
                    code="invalid_symbol_tag",
                    field="symbols",
                )
            )
            return None

        normalized_symbols.append(symbol.strip())

    return tuple(normalized_symbols)


def _parse_article_timestamp(
    value: object,
    field: str,
    issues: list[NewsValidationIssue],
) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        issues.append(
            NewsValidationIssue(
                code="invalid_timestamp",
                field=field,
            )
        )
        return None

    normalized = value.strip()

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        issues.append(
            NewsValidationIssue(
                code="invalid_timestamp",
                field=field,
            )
        )
        return None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        issues.append(
            NewsValidationIssue(
                code="timezone_required",
                field=field,
            )
        )
        return None

    return parsed.astimezone(timezone.utc)


def _parse_url(
    value: object,
    issues: list[NewsValidationIssue],
) -> str | None:
    normalized = _parse_required_article_string(
        value,
        "url",
        issues,
    )

    if normalized is None:
        return None

    parsed = urlsplit(normalized)

    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        issues.append(
            NewsValidationIssue(
                code="invalid_citation_url",
                field="url",
            )
        )
        return None

    return normalized


def _required_string(
    value: object,
    parameter: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{parameter} must be a nonblank string.")

    return value.strip()


def _require_aware_utc(
    value: datetime,
    parameter: str,
) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{parameter} must be timezone-aware.")

    return value.astimezone(timezone.utc)

def _news_content_signature(
    candidate: SilverNewsCandidate,
) -> tuple[object, ...]:
    """Return normalized source content used for version equality."""

    return (
        candidate.source_system,
        candidate.article_id,
        candidate.headline,
        frozenset(candidate.symbols),
        candidate.article_created_at,
        candidate.article_updated_at,
        candidate.article_source,
        candidate.url,
        candidate.summary,
        candidate.content,
    )

def _normalize_configured_symbols(
    configured_symbols: Sequence[str],
) -> tuple[str, ...]:
    """Validate the current configured equity-symbol universe."""

    if isinstance(configured_symbols, str):
        raise ValueError(
            "configured_symbols must be a sequence, "
            "not one string."
        )

    normalized = tuple(
        symbol.strip()
        if isinstance(symbol, str)
        else ""
        for symbol in configured_symbols
    )

    if (
        not normalized
        or any(not symbol for symbol in normalized)
    ):
        raise ValueError(
            "configured_symbols must contain at least "
            "one nonblank symbol."
        )

    if len(set(normalized)) != len(normalized):
        raise ValueError(
            "configured_symbols must not contain duplicates."
        )

    return normalized