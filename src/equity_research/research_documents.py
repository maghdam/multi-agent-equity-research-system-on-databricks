"""Pure-Python preparation of citation-ready RAG research documents."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from equity_research.silver_filing_sections import SilverFilingSection
from equity_research.silver_news import SilverNewsArticle


CLEANING_STRATEGY_VERSION = "research-text-v1"

SOURCE_TYPE_NEWS = "news"
SOURCE_TYPE_FILING = "filing"

TEXT_ORIGIN_CONTENT = "content"
TEXT_ORIGIN_SUMMARY = "summary"
TEXT_ORIGIN_FILING_SECTION = "filing_section"

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
WHITESPACE_PATTERN = re.compile(r"\s+")

UNTRUSTED_HTML_TAGS = {
    "script",
    "style",
    "noscript",
    "head",
    "template",
}


@dataclass(frozen=True)
class ResearchDocument:
    """One current retrieval-eligible source document version."""

    document_id: str
    document_version_id: str
    cleaning_strategy_version: str
    source_type: str
    source_system: str
    configured_symbols: tuple[str, ...]
    title: str
    document_text: str
    document_text_sha256: str
    text_origin: str
    evidence_date: date
    source_url: str
    article_id: int | None
    article_source: str | None
    article_created_at: datetime | None
    article_updated_at: datetime | None
    cik: str | None
    accession_number: str | None
    filing_form: str | None
    filing_date: date | None
    report_date: date | None
    section_code: str | None
    section_title: str | None
    source_response_id: str
    source_fetched_at: datetime
    source_ingestion_run_id: str


@dataclass(frozen=True)
class ResearchDocumentsSnapshotResult:
    """Complete deterministic current research-document snapshot."""

    documents: tuple[ResearchDocument, ...]
    news_input_count: int
    news_document_count: int
    news_no_text_count: int
    filing_input_count: int
    filing_document_count: int

    @property
    def document_count(self) -> int:
        return len(self.documents)


def build_research_documents_snapshot(
    *,
    news_articles: Sequence[SilverNewsArticle],
    filing_sections: Sequence[SilverFilingSection],
    configured_symbols: Collection[str],
) -> ResearchDocumentsSnapshotResult:
    """Build one deterministic current retrieval-document snapshot."""

    universe = _normalize_configured_universe(configured_symbols)
    documents: list[ResearchDocument] = []
    news_no_text_count = 0

    for article in news_articles:
        document = build_news_research_document(
            article,
            configured_symbols=universe,
        )
        if document is None:
            news_no_text_count += 1
        else:
            documents.append(document)

    for section in filing_sections:
        documents.append(
            build_filing_research_document(
                section,
                configured_symbols=universe,
            )
        )

    ordered = tuple(
        sorted(
            documents,
            key=lambda document: (
                document.source_type,
                document.document_id,
            ),
        )
    )
    _validate_document_snapshot(ordered)

    return ResearchDocumentsSnapshotResult(
        documents=ordered,
        news_input_count=len(news_articles),
        news_document_count=len(news_articles) - news_no_text_count,
        news_no_text_count=news_no_text_count,
        filing_input_count=len(filing_sections),
        filing_document_count=len(filing_sections),
    )


def build_news_research_document(
    article: SilverNewsArticle,
    *,
    configured_symbols: Collection[str],
) -> ResearchDocument | None:
    """Build one retrieval document from one validated Silver news row."""

    if not isinstance(article, SilverNewsArticle):
        raise ValueError("article must be a SilverNewsArticle.")

    universe = _normalize_configured_universe(configured_symbols)

    if article.source_system != "alpaca":
        raise ValueError("news source_system must be alpaca.")

    if isinstance(article.article_id, bool) or not isinstance(article.article_id, int):
        raise ValueError("article_id must be an integer.")
    if article.article_id <= 0:
        raise ValueError("article_id must be positive.")

    article_symbols = _validate_scoped_symbols(
        article.configured_symbols,
        universe=universe,
        field="configured_symbols",
    )
    headline = _required_string(article.headline, "headline")
    article_source = _required_string(article.article_source, "article_source")
    source_url = _validate_source_url(article.url)
    created_at = _require_utc(article.article_created_at, "article_created_at")
    updated_at = _require_utc(article.article_updated_at, "article_updated_at")
    fetched_at = _require_utc(article.fetched_at, "fetched_at")

    if created_at > updated_at:
        raise ValueError("article_created_at must not be after article_updated_at.")
    if updated_at > fetched_at:
        raise ValueError("article_updated_at must not be after fetched_at.")

    source_response_id = _required_string(
        article.source_response_id,
        "source_response_id",
    )
    ingestion_run_id = _required_string(
        article.ingestion_run_id,
        "ingestion_run_id",
    )

    cleaned_content = _clean_news_text(article.content)

    if cleaned_content is not None:
        document_text = cleaned_content
        text_origin = TEXT_ORIGIN_CONTENT
    else:
        cleaned_summary = _clean_news_text(article.summary)
        if cleaned_summary is None:
            return None
        document_text = cleaned_summary
        text_origin = TEXT_ORIGIN_SUMMARY

    document_id = f"alpaca:news:{article.article_id}"
    document_text_sha256 = _sha256_text(document_text)

    version_payload = {
        "article_created_at": _canonical_datetime(created_at),
        "article_source": article_source,
        "article_updated_at": _canonical_datetime(updated_at),
        "cleaning_strategy_version": CLEANING_STRATEGY_VERSION,
        "configured_symbols": list(article_symbols),
        "document_id": document_id,
        "document_text_sha256": document_text_sha256,
        "headline": headline,
        "source_url": source_url,
        "text_origin": text_origin,
    }

    return ResearchDocument(
        document_id=document_id,
        document_version_id=_sha256_canonical(version_payload),
        cleaning_strategy_version=CLEANING_STRATEGY_VERSION,
        source_type=SOURCE_TYPE_NEWS,
        source_system="alpaca",
        configured_symbols=article_symbols,
        title=headline,
        document_text=document_text,
        document_text_sha256=document_text_sha256,
        text_origin=text_origin,
        evidence_date=created_at.date(),
        source_url=source_url,
        article_id=article.article_id,
        article_source=article_source,
        article_created_at=created_at,
        article_updated_at=updated_at,
        cik=None,
        accession_number=None,
        filing_form=None,
        filing_date=None,
        report_date=None,
        section_code=None,
        section_title=None,
        source_response_id=source_response_id,
        source_fetched_at=fetched_at,
        source_ingestion_run_id=ingestion_run_id,
    )


def build_filing_research_document(
    section: SilverFilingSection,
    *,
    configured_symbols: Collection[str],
) -> ResearchDocument:
    """Build one retrieval document from one validated Silver filing section."""

    if not isinstance(section, SilverFilingSection):
        raise ValueError("section must be a SilverFilingSection.")

    universe = _normalize_configured_universe(configured_symbols)

    if section.source_system != "sec":
        raise ValueError("filing source_system must be sec.")

    project_symbol = _required_string(
        section.project_symbol,
        "project_symbol",
    )
    if project_symbol not in universe:
        raise ValueError(
            f"project_symbol is outside the configured universe: {project_symbol}"
        )

    cik = _required_string(section.cik, "cik")
    accession_number = _required_string(
        section.accession_number,
        "accession_number",
    )
    filing_form = _required_string(section.filing_form, "filing_form")
    section_code = _required_string(section.section_code, "section_code")
    section_title = _required_string(section.section_title, "section_title")
    source_url = _validate_source_url(section.source_url)
    filing_date = _required_date(section.filing_date, "filing_date")
    report_date = _required_date(section.report_date, "report_date")
    fetched_at = _require_utc(section.fetched_at, "fetched_at")

    if report_date > filing_date:
        raise ValueError("report_date must not be after filing_date.")

    source_response_id = _required_string(
        section.source_response_id,
        "source_response_id",
    )
    ingestion_run_id = _required_string(
        section.ingestion_run_id,
        "ingestion_run_id",
    )

    source_section_text = _required_string(
        section.section_text,
        "section_text",
        strip=False,
    )
    source_section_hash = _validate_sha256(
        section.section_text_sha256,
        "section_text_sha256",
    )
    if _sha256_text(source_section_text) != source_section_hash:
        raise ValueError(
            "section_text_sha256 does not match the Silver section_text."
        )

    document_text = _normalize_retrieval_text(source_section_text)
    if not document_text:
        raise ValueError("section_text must remain nonblank after cleaning.")

    document_id = (
        f"sec:filing:{accession_number}:{section_code}"
    )
    document_text_sha256 = _sha256_text(document_text)
    configured_scope = (project_symbol,)
    title = f"{filing_form} - {section_title}"

    version_payload = {
        "accession_number": accession_number,
        "cleaning_strategy_version": CLEANING_STRATEGY_VERSION,
        "configured_symbols": list(configured_scope),
        "document_id": document_id,
        "document_text_sha256": document_text_sha256,
        "filing_date": filing_date.isoformat(),
        "filing_form": filing_form,
        "report_date": report_date.isoformat(),
        "section_code": section_code,
        "section_title": section_title,
        "source_url": source_url,
    }

    return ResearchDocument(
        document_id=document_id,
        document_version_id=_sha256_canonical(version_payload),
        cleaning_strategy_version=CLEANING_STRATEGY_VERSION,
        source_type=SOURCE_TYPE_FILING,
        source_system="sec",
        configured_symbols=configured_scope,
        title=title,
        document_text=document_text,
        document_text_sha256=document_text_sha256,
        text_origin=TEXT_ORIGIN_FILING_SECTION,
        evidence_date=filing_date,
        source_url=source_url,
        article_id=None,
        article_source=None,
        article_created_at=None,
        article_updated_at=None,
        cik=cik,
        accession_number=accession_number,
        filing_form=filing_form,
        filing_date=filing_date,
        report_date=report_date,
        section_code=section_code,
        section_title=section_title,
        source_response_id=source_response_id,
        source_fetched_at=fetched_at,
        source_ingestion_run_id=ingestion_run_id,
    )


def _clean_news_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("news content and summary must be strings or null.")
    if not value.strip():
        return None

    soup = BeautifulSoup(value, "html.parser")

    for tag in list(soup.find_all(True)):
        tag_name = (tag.name or "").lower()
        if tag_name in UNTRUSTED_HTML_TAGS:
            tag.decompose()

    cleaned = _normalize_retrieval_text(
        soup.get_text(" ", strip=True)
    )
    return cleaned or None


def _normalize_retrieval_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value).strip()


def _normalize_configured_universe(
    configured_symbols: Collection[str],
) -> frozenset[str]:
    if isinstance(configured_symbols, (str, bytes)):
        raise ValueError(
            "configured_symbols must be a nonempty collection of symbols."
        )

    normalized: list[str] = []

    for raw_symbol in configured_symbols:
        symbol = _required_string(raw_symbol, "configured symbol")
        if symbol != raw_symbol:
            raise ValueError(
                "configured symbols must not contain surrounding whitespace."
            )
        normalized.append(symbol)

    if not normalized:
        raise ValueError("configured_symbols must be nonempty.")

    if len(normalized) != len(set(normalized)):
        raise ValueError("configured_symbols must be unique.")

    return frozenset(normalized)


def _validate_scoped_symbols(
    symbols: Sequence[str],
    *,
    universe: frozenset[str],
    field: str,
) -> tuple[str, ...]:
    if isinstance(symbols, (str, bytes)) or not symbols:
        raise ValueError(f"{field} must be a nonempty symbol sequence.")

    normalized = tuple(
        _required_string(symbol, field)
        for symbol in symbols
    )

    expected = tuple(sorted(set(normalized)))

    if normalized != expected:
        raise ValueError(
            f"{field} must already be sorted and unique."
        )

    outside = sorted(set(normalized) - universe)
    if outside:
        raise ValueError(
            f"{field} contains symbols outside the configured universe: "
            f"{outside}"
        )

    return normalized


def _validate_document_snapshot(
    documents: Sequence[ResearchDocument],
) -> None:
    document_ids = [document.document_id for document in documents]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError(
            "research_documents document_id values must be unique."
        )

    version_ids = [document.document_version_id for document in documents]
    if len(version_ids) != len(set(version_ids)):
        raise ValueError(
            "research_documents document_version_id values must be unique."
        )

    for document in documents:
        if _sha256_text(document.document_text) != document.document_text_sha256:
            raise ValueError(
                f"{document.document_id}: document_text_sha256 mismatch."
            )
        _validate_sha256(
            document.document_version_id,
            "document_version_id",
        )


def _validate_source_url(value: str) -> str:
    url = _required_string(value, "source_url")
    parsed = urlsplit(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("source_url must use HTTP or HTTPS.")
    if not parsed.hostname:
        raise ValueError("source_url must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("source_url must not contain credentials.")

    return url


def _required_string(
    value: object,
    field: str,
    *,
    strip: bool = True,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")

    normalized = value.strip() if strip else value

    if not normalized.strip():
        raise ValueError(f"{field} must be nonblank.")

    return normalized


def _required_date(value: object, field: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(f"{field} must be a date.")
    return value


def _require_utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware.")

    normalized = value.astimezone(timezone.utc)

    if normalized.utcoffset() != timezone.utc.utcoffset(normalized):
        raise ValueError(f"{field} must normalize to UTC.")

    return normalized


def _validate_sha256(value: object, field: str) -> str:
    normalized = _required_string(value, field).lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"{field} must contain exactly 64 hexadecimal characters."
        )
    return normalized


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_canonical(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_datetime(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")
