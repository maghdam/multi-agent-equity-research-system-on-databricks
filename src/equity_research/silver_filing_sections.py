"""Pure-Python Silver transformation logic for SEC filing sections."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from equity_research.sec_filings import FilingMetadata, build_filing_document_path

SOURCE_SYSTEM = "sec"
SOURCE_ENDPOINT = "filing_document"
FILING_FORM = "10-K"
SEC_ARCHIVES_HOST = "www.sec.gov"

CIK_PATTERN = re.compile(r"[0-9]{10}")
ACCESSION_PATTERN = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")

MIN_SECTION_CHARS = 500

TERMINAL_PAGE_MARKER_PATTERN = re.compile(
    r"(?:^|\s)"
    r"[0-9]{1,4}\s+"
    r"PART\s+[IVXLC]+\s+"
    r"ITEM\s+[0-9]{1,2}[A-Z]?"
    r"(?:\s*,\s*[0-9]{1,2}[A-Z]?)*"
    r"\s*$",
    re.IGNORECASE,
)

TERMINAL_FILING_FOOTER_PATTERN = re.compile(
    r"(?P<prefix>[.!?])\s+"
    r"[A-Z][A-Za-z0-9&.,'?\- ]{1,80}"
    r"\s*\|\s*"
    r"[0-9]{4}\s+FORM\s+10-K"
    r"\s*\|\s*"
    r"[0-9]{1,4}"
    r"\s*$",
    re.IGNORECASE,
)

DEI_ENTITY_CIK = "dei:EntityCentralIndexKey"
DEI_DOCUMENT_TYPE = "dei:DocumentType"
DEI_PERIOD_END = "dei:DocumentPeriodEndDate"

SEC_CIK_SCHEMES = {
    "http://www.sec.gov/CIK",
    "https://www.sec.gov/CIK",
}


@dataclass(frozen=True)
class BronzeFilingDocument:
    source_response_id: str
    source_system: str
    source_endpoint: str
    project_symbol: str
    sec_cik: str
    accession_number: str
    filing_form: str
    filing_date: date
    report_date: date
    primary_document: str
    source_url: str
    http_status: int
    response_payload_html: str
    response_bytes: int
    response_sha256: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class FilingDocumentSelectionResult:
    selected: tuple[BronzeFilingDocument, ...]
    bronze_response_count: int
    in_scope_response_count: int
    out_of_scope_response_count: int
    superseded_response_count: int
    tie_repeat_count: int

    @property
    def selected_count(self) -> int:
        return len(self.selected)


@dataclass(frozen=True)
class SilverFilingSection:
    source_system: str
    cik: str
    project_symbol: str
    accession_number: str
    filing_form: str
    filing_date: date
    report_date: date
    primary_document: str
    source_url: str
    section_code: str
    section_title: str
    section_text: str
    section_text_sha256: str
    source_response_id: str
    response_sha256: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class FilingSectionsSnapshotResult:
    selected: tuple[SilverFilingSection, ...]
    selected_responses: tuple[BronzeFilingDocument, ...]
    bronze_response_count: int
    out_of_scope_response_count: int
    superseded_response_count: int
    tie_repeat_count: int

    @property
    def selected_count(self) -> int:
        return len(self.selected)


def select_latest_filing_documents(
    responses: Sequence[BronzeFilingDocument],
    configured_companies: Mapping[str, str],
) -> FilingDocumentSelectionResult:
    """Select the latest exact 10-K retrieval for every configured company."""

    configuration = _normalize_configured_companies(configured_companies)
    seen_response_ids: set[str] = set()
    grouped: dict[str, list[BronzeFilingDocument]] = {
        symbol: [] for symbol in configuration
    }
    out_of_scope_count = 0

    for response in responses:
        normalized = _normalize_bronze_response(response)

        if normalized.source_response_id in seen_response_ids:
            raise ValueError(
                "source_response_id must be unique across Bronze filing history: "
                f"{normalized.source_response_id}"
            )
        seen_response_ids.add(normalized.source_response_id)

        expected_cik = configuration.get(normalized.project_symbol)

        if expected_cik is None:
            out_of_scope_count += 1
            continue

        if normalized.sec_cik != expected_cik:
            raise ValueError(
                f"{normalized.project_symbol}: Bronze sec_cik "
                f"{normalized.sec_cik} does not match configured CIK "
                f"{expected_cik}."
            )

        if normalized.filing_form != FILING_FORM:
            out_of_scope_count += 1
            continue

        grouped[normalized.project_symbol].append(normalized)

    selected: list[BronzeFilingDocument] = []
    superseded_count = 0
    tie_repeat_count = 0

    for project_symbol, expected_cik in configuration.items():
        candidates = grouped[project_symbol]

        if not candidates:
            raise ValueError(
                f"{project_symbol}: no eligible exact 10-K Bronze filing "
                "document is available."
            )

        latest_filing_date = max(x.filing_date for x in candidates)
        latest_filing_rows = [
            x for x in candidates if x.filing_date == latest_filing_date
        ]
        latest_accessions = {x.accession_number for x in latest_filing_rows}

        if len(latest_accessions) != 1:
            raise ValueError(
                f"{project_symbol}: latest exact 10-K filing selection is "
                "ambiguous across distinct accessions."
            )

        selected_accession = next(iter(latest_accessions))
        accession_rows = [
            x for x in latest_filing_rows
            if x.accession_number == selected_accession
        ]

        _validate_retrieval_metadata_consistency(
            accession_rows,
            project_symbol=project_symbol,
            expected_cik=expected_cik,
        )

        latest_fetched_at = max(x.fetched_at for x in accession_rows)
        latest_retrievals = [
            x for x in accession_rows if x.fetched_at == latest_fetched_at
        ]

        if len(latest_retrievals) > 1:
            raw_html_versions = {
                x.response_payload_html for x in latest_retrievals
            }
            if len(raw_html_versions) != 1:
                raise ValueError(
                    f"{project_symbol}: latest retrievals share fetched_at "
                    "but contain different raw HTML."
                )
            tie_repeat_count += len(latest_retrievals) - 1

        selected.append(
            min(
                latest_retrievals,
                key=lambda x: x.source_response_id,
            )
        )
        superseded_count += len(candidates) - 1

    return FilingDocumentSelectionResult(
        selected=tuple(selected),
        bronze_response_count=len(responses),
        in_scope_response_count=sum(len(v) for v in grouped.values()),
        out_of_scope_response_count=out_of_scope_count,
        superseded_response_count=superseded_count,
        tie_repeat_count=tie_repeat_count,
    )


def transform_filing_document(
    response: BronzeFilingDocument,
    *,
    expected_cik: str,
) -> tuple[SilverFilingSection, SilverFilingSection]:
    """Validate one selected filing and extract Item 1 and Item 1A."""

    normalized = _normalize_bronze_response(response)
    expected_cik = _normalize_cik(expected_cik, "expected_cik")

    if normalized.sec_cik != expected_cik:
        raise ValueError(
            f"{normalized.project_symbol}: selected Bronze sec_cik "
            f"{normalized.sec_cik} does not match configured CIK "
            f"{expected_cik}."
        )

    if normalized.filing_form != FILING_FORM:
        raise ValueError(
            f"{normalized.project_symbol}: selected filing form must be "
            f"exactly {FILING_FORM}."
        )

    soup = BeautifulSoup(normalized.response_payload_html, "html.parser")

    _validate_document_identity(
        soup,
        response=normalized,
        expected_cik=expected_cik,
    )

    plain_text = _extract_normalized_plain_text(soup)
    item_1_text, item_1a_text = _extract_required_sections(
        plain_text,
        project_symbol=normalized.project_symbol,
    )

    return (
        _build_silver_section(
            response=normalized,
            expected_cik=expected_cik,
            section_code="item_1",
            section_title="Business",
            section_text=item_1_text,
        ),
        _build_silver_section(
            response=normalized,
            expected_cik=expected_cik,
            section_code="item_1a",
            section_title="Risk Factors",
            section_text=item_1a_text,
        ),
    )


def transform_filing_sections_snapshot(
    responses: Sequence[BronzeFilingDocument],
    configured_companies: Mapping[str, str],
) -> FilingSectionsSnapshotResult:
    """Rebuild the complete current Silver filing-sections snapshot."""

    configuration = _normalize_configured_companies(configured_companies)
    selection = select_latest_filing_documents(
        responses,
        configuration,
    )

    selected_sections: list[SilverFilingSection] = []

    for response in selection.selected:
        selected_sections.extend(
            transform_filing_document(
                response,
                expected_cik=configuration[response.project_symbol],
            )
        )

    expected_count = len(configuration) * 2

    if len(selected_sections) != expected_count:
        raise ValueError(
            "Silver filing-sections snapshot did not produce exactly "
            "Item 1 and Item 1A for every configured company."
        )

    keys = [
        (
            section.source_system,
            section.cik,
            section.accession_number,
            section.section_code,
        )
        for section in selected_sections
    ]

    if len(keys) != len(set(keys)):
        raise ValueError(
            "Silver filing-sections business keys are not unique."
        )

    return FilingSectionsSnapshotResult(
        selected=tuple(selected_sections),
        selected_responses=selection.selected,
        bronze_response_count=selection.bronze_response_count,
        out_of_scope_response_count=selection.out_of_scope_response_count,
        superseded_response_count=selection.superseded_response_count,
        tie_repeat_count=selection.tie_repeat_count,
    )


def _normalize_configured_companies(
    configured_companies: Mapping[str, str],
) -> dict[str, str]:
    if not isinstance(configured_companies, Mapping) or not configured_companies:
        raise ValueError(
            "configured_companies must be a nonempty mapping."
        )

    normalized: dict[str, str] = {}
    seen_ciks: set[str] = set()

    for raw_symbol, raw_cik in configured_companies.items():
        symbol = _required_string(
            raw_symbol,
            "configured company symbol",
        )
        cik = _normalize_cik(raw_cik, f"{symbol}.sec_cik")

        if symbol in normalized:
            raise ValueError(f"duplicate configured symbol: {symbol}")

        if cik in seen_ciks:
            raise ValueError(f"duplicate configured CIK: {cik}")

        normalized[symbol] = cik
        seen_ciks.add(cik)

    return normalized


def _normalize_bronze_response(
    response: BronzeFilingDocument,
) -> BronzeFilingDocument:
    if not isinstance(response, BronzeFilingDocument):
        raise ValueError(
            "responses must contain BronzeFilingDocument values."
        )

    source_response_id = _required_string(
        response.source_response_id,
        "source_response_id",
    )
    source_system = _required_string(
        response.source_system,
        "source_system",
    )
    source_endpoint = _required_string(
        response.source_endpoint,
        "source_endpoint",
    )
    project_symbol = _required_string(
        response.project_symbol,
        "project_symbol",
    )
    sec_cik = _normalize_cik(response.sec_cik, "sec_cik")
    accession_number = _normalize_accession(response.accession_number)
    filing_form = _required_string(response.filing_form, "filing_form")
    filing_date = _required_date(response.filing_date, "filing_date")
    report_date = _required_date(response.report_date, "report_date")

    if report_date > filing_date:
        raise ValueError("report_date must not be after filing_date.")

    primary_document = _normalize_primary_document(
        response.primary_document
    )
    source_url = _normalize_source_url(
        response.source_url,
        cik=sec_cik,
        accession_number=accession_number,
        filing_date=filing_date,
        report_date=report_date,
        filing_form=filing_form,
        primary_document=primary_document,
    )

    if (
        isinstance(response.http_status, bool)
        or not isinstance(response.http_status, int)
        or response.http_status != 200
    ):
        raise ValueError("http_status must be integer 200.")

    response_payload_html = _required_string(
        response.response_payload_html,
        "response_payload_html",
        strip=False,
    )
    actual_bytes = response_payload_html.encode("utf-8")

    if (
        isinstance(response.response_bytes, bool)
        or not isinstance(response.response_bytes, int)
        or response.response_bytes < 1
    ):
        raise ValueError(
            "response_bytes must be a positive integer."
        )

    if len(actual_bytes) != response.response_bytes:
        raise ValueError(
            "response_bytes does not match the UTF-8 filing payload."
        )

    response_sha256 = _required_string(
        response.response_sha256,
        "response_sha256",
    ).lower()

    if not SHA256_PATTERN.fullmatch(response_sha256):
        raise ValueError(
            "response_sha256 must contain exactly 64 hexadecimal characters."
        )

    if hashlib.sha256(actual_bytes).hexdigest() != response_sha256:
        raise ValueError(
            "response_sha256 does not match the filing payload."
        )

    fetched_at = _normalize_utc_datetime(
        response.fetched_at,
        "fetched_at",
    )
    ingestion_run_id = _required_string(
        response.ingestion_run_id,
        "ingestion_run_id",
    )

    if source_system != SOURCE_SYSTEM:
        raise ValueError(f"source_system must be {SOURCE_SYSTEM}.")

    if source_endpoint != SOURCE_ENDPOINT:
        raise ValueError(f"source_endpoint must be {SOURCE_ENDPOINT}.")

    return BronzeFilingDocument(
        source_response_id=source_response_id,
        source_system=source_system,
        source_endpoint=source_endpoint,
        project_symbol=project_symbol,
        sec_cik=sec_cik,
        accession_number=accession_number,
        filing_form=filing_form,
        filing_date=filing_date,
        report_date=report_date,
        primary_document=primary_document,
        source_url=source_url,
        http_status=200,
        response_payload_html=response_payload_html,
        response_bytes=response.response_bytes,
        response_sha256=response_sha256,
        fetched_at=fetched_at,
        ingestion_run_id=ingestion_run_id,
    )


def _validate_retrieval_metadata_consistency(
    responses: Sequence[BronzeFilingDocument],
    *,
    project_symbol: str,
    expected_cik: str,
) -> None:
    signatures = {
        (
            response.sec_cik,
            response.accession_number,
            response.filing_form,
            response.filing_date,
            response.report_date,
            response.primary_document,
            response.source_url,
        )
        for response in responses
    }

    if len(signatures) != 1:
        raise ValueError(
            f"{project_symbol}: retrievals of the selected accession "
            "contain conflicting filing metadata."
        )

    if next(iter(signatures))[0] != expected_cik:
        raise ValueError(
            f"{project_symbol}: selected filing metadata does not match "
            "the configured CIK."
        )


def _validate_document_identity(
    soup: BeautifulSoup,
    *,
    response: BronzeFilingDocument,
    expected_cik: str,
) -> None:
    cik_value, cik_contexts = _read_dei_fact(
        soup,
        DEI_ENTITY_CIK,
        normalizer=_normalize_document_cik,
    )
    document_type, type_contexts = _read_dei_fact(
        soup,
        DEI_DOCUMENT_TYPE,
        normalizer=lambda value: _required_string(
            value,
            DEI_DOCUMENT_TYPE,
        ),
    )
    period_end, period_contexts = _read_dei_fact(
        soup,
        DEI_PERIOD_END,
        normalizer=_parse_supported_document_date,
    )

    if cik_value != expected_cik:
        raise ValueError(
            f"{response.project_symbol}: filing DEI CIK does not match "
            "the configured CIK."
        )

    if document_type != response.filing_form:
        raise ValueError(
            f"{response.project_symbol}: filing DEI DocumentType does not "
            "match Bronze filing_form."
        )

    if period_end != response.report_date:
        raise ValueError(
            f"{response.project_symbol}: filing DEI DocumentPeriodEndDate "
            "does not match Bronze report_date."
        )

    for contextref in sorted(
        set(cik_contexts + type_contexts + period_contexts)
    ):
        _validate_identity_context(
            soup,
            contextref=contextref,
            expected_cik=expected_cik,
            expected_report_date=response.report_date,
            project_symbol=response.project_symbol,
        )


def _read_dei_fact(
    soup: BeautifulSoup,
    fact_name: str,
    *,
    normalizer,
):
    matches: list[Tag] = []

    for tag in soup.find_all(True):
        raw_name = tag.attrs.get("name")
        if isinstance(raw_name, str) and raw_name.lower() == fact_name.lower():
            matches.append(tag)

    if not matches:
        raise ValueError(
            f"required inline-XBRL fact {fact_name} was not found."
        )

    normalized_values = {
        normalizer(
            _normalize_whitespace(tag.get_text(" ", strip=True))
        )
        for tag in matches
    }

    if len(normalized_values) != 1:
        raise ValueError(
            f"inline-XBRL fact {fact_name} has conflicting values."
        )

    contextrefs: list[str] = []

    for tag in matches:
        raw_contextref = tag.attrs.get("contextref")
        contextref = _required_string(
            raw_contextref,
            f"{fact_name}.contextref",
        )
        contextrefs.append(contextref)

    return next(iter(normalized_values)), contextrefs


def _validate_identity_context(
    soup: BeautifulSoup,
    *,
    contextref: str,
    expected_cik: str,
    expected_report_date: date,
    project_symbol: str,
) -> None:
    contexts = [
        tag
        for tag in soup.find_all(True)
        if tag.attrs.get("id") == contextref
    ]

    if len(contexts) != 1:
        raise ValueError(
            f"{project_symbol}: inline-XBRL context {contextref!r} "
            "must resolve uniquely."
        )

    context = contexts[0]
    identifiers = _descendants_by_local_name(context, "identifier")

    if len(identifiers) != 1:
        raise ValueError(
            f"{project_symbol}: context {contextref!r} must contain "
            "one entity identifier."
        )

    identifier = identifiers[0]
    scheme = _required_string(
        identifier.attrs.get("scheme"),
        f"{contextref}.identifier.scheme",
    )

    if scheme not in SEC_CIK_SCHEMES:
        raise ValueError(
            f"{project_symbol}: context {contextref!r} uses an "
            "unsupported SEC identifier scheme."
        )

    context_cik = _normalize_document_cik(
        _normalize_whitespace(
            identifier.get_text(" ", strip=True)
        )
    )

    if context_cik != expected_cik:
        raise ValueError(
            f"{project_symbol}: context {contextref!r} CIK does not "
            "match the configured CIK."
        )

    period_values = (
        _descendants_by_local_name(context, "instant")
        + _descendants_by_local_name(context, "enddate")
    )

    if len(period_values) != 1:
        raise ValueError(
            f"{project_symbol}: context {contextref!r} must resolve "
            "to one reporting-period end."
        )

    context_period_end = _parse_iso_context_date(
        _normalize_whitespace(
            period_values[0].get_text(" ", strip=True)
        )
    )

    if context_period_end != expected_report_date:
        raise ValueError(
            f"{project_symbol}: context {contextref!r} period end does "
            "not match Bronze report_date."
        )


def _extract_normalized_plain_text(
    soup: BeautifulSoup,
) -> str:
    for tag in list(soup.find_all(True)):
        tag_name = (tag.name or "").lower()

        if (
            tag_name in {"script", "style", "noscript", "head"}
            or tag_name in {"ix:header", "ix:hidden"}
        ):
            tag.decompose()

    return _normalize_whitespace(
        soup.get_text(" ", strip=True)
    )


def _extract_required_sections(
    plain_text: str,
    *,
    project_symbol: str,
) -> tuple[str, str]:
    item_1_candidates = list(
        _heading_pattern("1", "business").finditer(plain_text)
    )
    item_1a_candidates = list(
        _heading_pattern("1a", "risk factors").finditer(plain_text)
    )

    if not item_1_candidates:
        raise ValueError(
            f"{project_symbol}: Item 1 Business body heading was not found."
        )

    if not item_1a_candidates:
        raise ValueError(
            f"{project_symbol}: Item 1A Risk Factors body heading was not found."
        )

    valid_pairs: list[tuple[re.Match[str], re.Match[str], str]] = []

    for item_1 in item_1_candidates:
        next_item_1a = next(
            (
                candidate
                for candidate in item_1a_candidates
                if candidate.start() >= item_1.end()
            ),
            None,
        )

        if next_item_1a is None:
            continue

        candidate_text = _clean_extracted_section_text(
            plain_text[item_1.end():next_item_1a.start()]
        )

        if len(candidate_text) >= MIN_SECTION_CHARS:
            valid_pairs.append(
                (item_1, next_item_1a, candidate_text)
            )

    if not valid_pairs:
        raise ValueError(
            f"{project_symbol}: no substantive Item 1 to Item 1A "
            "body boundary was found."
        )

    unique_pairs = {
        (pair[0].start(), pair[1].start())
        for pair in valid_pairs
    }

    if len(unique_pairs) != 1:
        raise ValueError(
            f"{project_symbol}: Item 1 / Item 1A body boundaries "
            "are ambiguous."
        )

    _, item_1a_match, item_1_text = valid_pairs[0]

    later_boundaries = []

    for item_code, title in (
        ("1b", "unresolved staff comments"),
        ("1c", "cybersecurity"),
        ("2", "properties"),
    ):
        for boundary in _heading_pattern(
            item_code,
            title,
        ).finditer(plain_text):
            if boundary.start() >= item_1a_match.end():
                later_boundaries.append(boundary)

    if not later_boundaries:
        raise ValueError(
            f"{project_symbol}: no supported end boundary after Item 1A "
            "was found."
        )

    item_1a_end = min(
        later_boundaries,
        key=lambda match: match.start(),
    )

    item_1a_text = _clean_extracted_section_text(
        plain_text[item_1a_match.end():item_1a_end.start()]
    )

    if len(item_1a_text) < MIN_SECTION_CHARS:
        raise ValueError(
            f"{project_symbol}: extracted Item 1A text is shorter than "
            f"{MIN_SECTION_CHARS} characters."
        )

    return item_1_text, item_1a_text


def _clean_extracted_section_text(
    section_text: str,
) -> str:
    """Normalize section text and remove a terminal SEC page marker."""

    normalized = _normalize_whitespace(section_text)

    cleaned = TERMINAL_PAGE_MARKER_PATTERN.sub(
        "",
        normalized,
    )

    cleaned = TERMINAL_FILING_FOOTER_PATTERN.sub(
        r"\g<prefix>",
        cleaned,
    )

    return _normalize_whitespace(cleaned)


def _heading_pattern(
    item_code: str,
    title: str,
) -> re.Pattern[str]:
    code = re.escape(item_code[0])

    if len(item_code) > 1:
        code += r"\s*" + re.escape(item_code[1:])

    return re.compile(
        rf"(?<![A-Za-z0-9])"
        rf"item\s*{code}"
        rf"(?![A-Za-z0-9])"
        rf"[\s.\-:–—|]{{0,20}}"
        rf"{_spaced_word_phrase(title)}"
        rf"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def _spaced_word_phrase(
    phrase: str,
) -> str:
    encoded_words = []

    for word in phrase.split():
        encoded_words.append(
            r"\s*".join(
                re.escape(character)
                for character in word
            )
        )

    return r"\s+".join(encoded_words)


def _build_silver_section(
    *,
    response: BronzeFilingDocument,
    expected_cik: str,
    section_code: str,
    section_title: str,
    section_text: str,
) -> SilverFilingSection:
    normalized_text = _normalize_whitespace(section_text)

    if len(normalized_text) < MIN_SECTION_CHARS:
        raise ValueError(
            f"{response.project_symbol}: {section_code} does not meet "
            "the minimum substantive-text threshold."
        )

    section_hash = hashlib.sha256(
        normalized_text.encode("utf-8")
    ).hexdigest()

    return SilverFilingSection(
        source_system=SOURCE_SYSTEM,
        cik=expected_cik,
        project_symbol=response.project_symbol,
        accession_number=response.accession_number,
        filing_form=response.filing_form,
        filing_date=response.filing_date,
        report_date=response.report_date,
        primary_document=response.primary_document,
        source_url=response.source_url,
        section_code=section_code,
        section_title=section_title,
        section_text=normalized_text,
        section_text_sha256=section_hash,
        source_response_id=response.source_response_id,
        response_sha256=response.response_sha256,
        fetched_at=response.fetched_at,
        ingestion_run_id=response.ingestion_run_id,
    )


def _normalize_source_url(
    value: object,
    *,
    cik: str,
    accession_number: str,
    filing_date: date,
    report_date: date,
    filing_form: str,
    primary_document: str,
) -> str:
    source_url = _required_string(value, "source_url")
    parsed = urlparse(source_url)

    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != SEC_ARCHIVES_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "source_url must be the canonical HTTPS SEC Archives URL."
        )

    expected_path = build_filing_document_path(
        cik,
        FilingMetadata(
            accession_number=accession_number,
            filing_date=filing_date,
            report_date=report_date,
            form=filing_form,
            primary_document=primary_document,
        ),
    )

    if parsed.path != expected_path:
        raise ValueError(
            "source_url path does not match the selected filing metadata."
        )

    return source_url


def _normalize_primary_document(value: object) -> str:
    primary_document = _required_string(
        value,
        "primary_document",
    )

    if (
        "/" in primary_document
        or "\\" in primary_document
        or primary_document in {".", ".."}
    ):
        raise ValueError(
            "primary_document must be a filename, not a path."
        )

    return primary_document


def _normalize_cik(value: object, field_name: str) -> str:
    normalized = _required_string(value, field_name)

    if not CIK_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must contain exactly 10 ASCII digits."
        )

    if int(normalized) < 1:
        raise ValueError(
            f"{field_name} must identify a positive SEC CIK."
        )

    return normalized


def _normalize_document_cik(value: object) -> str:
    normalized = _required_string(
        value,
        DEI_ENTITY_CIK,
    )

    if (
        not normalized.isascii()
        or not normalized.isdigit()
        or len(normalized) > 10
        or int(normalized) < 1
    ):
        raise ValueError(
            f"{DEI_ENTITY_CIK} must contain at most 10 ASCII digits."
        )

    return normalized.zfill(10)


def _normalize_accession(value: object) -> str:
    normalized = _required_string(
        value,
        "accession_number",
    )

    if not ACCESSION_PATTERN.fullmatch(normalized):
        raise ValueError(
            "accession_number must match ##########-##-###### "
            "using ASCII digits."
        )

    return normalized


def _required_string(
    value: object,
    field_name: str,
    *,
    strip: bool = True,
) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"{field_name} must be a nonblank string."
        )

    normalized = value.strip() if strip else value

    if not normalized.strip():
        raise ValueError(
            f"{field_name} must be a nonblank string."
        )

    return normalized


def _required_date(value: object, field_name: str) -> date:
    if (
        not isinstance(value, date)
        or isinstance(value, datetime)
    ):
        raise ValueError(
            f"{field_name} must be a date."
        )

    return value


def _normalize_utc_datetime(
    value: object,
    field_name: str,
) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{field_name} must be a timezone-aware datetime."
        )

    return value.astimezone(timezone.utc)


def _parse_supported_document_date(value: object) -> date:
    normalized = _normalize_whitespace(
        _required_string(
            value,
            DEI_PERIOD_END,
        )
    )

    # Inline-XBRL can split a rendered date across nested facts/tags.
    # BeautifulSoup then inserts separator whitespace around punctuation,
    # e.g. "September 27 , 2025". Normalize only that presentation artifact.
    normalized = re.sub(r"\s+,\s*", ", ", normalized)

    try:
        return date.fromisoformat(normalized)
    except ValueError:
        pass

    for format_string in (
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
    ):
        try:
            return datetime.strptime(
                normalized,
                format_string,
            ).date()
        except ValueError:
            continue

    raise ValueError(
        f"{DEI_PERIOD_END} uses an unsupported date representation."
    )


def _parse_iso_context_date(value: object) -> date:
    normalized = _required_string(
        value,
        "context period date",
    )

    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            "context period date must use YYYY-MM-DD."
        ) from exc

    if parsed.isoformat() != normalized:
        raise ValueError(
            "context period date must use YYYY-MM-DD."
        )

    return parsed


def _descendants_by_local_name(
    tag: Tag,
    local_name: str,
) -> list[Tag]:
    target = local_name.lower()

    return [
        descendant
        for descendant in tag.find_all(True)
        if (
            (descendant.name or "")
            .split(":")[-1]
            .lower()
            == target
        )
    ]


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
