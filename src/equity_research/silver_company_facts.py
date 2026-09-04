"""Pure-Python Silver transformation logic for SEC company facts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal

from equity_research.sec_company_facts import parse_company_facts_response


SOURCE_SYSTEM = "sec"
SOURCE_ENDPOINT = "companyfacts"
TAXONOMY = "us-gaap"
UNIT = "USD"

CIK_PATTERN = re.compile(r"[0-9]{10}")
ACCESSION_PATTERN = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")

DECIMAL_SCALE = Decimal("0.00000001")
MAX_DECIMAL_28_8 = Decimal("99999999999999999999.99999999")


@dataclass(frozen=True)
class CompanyFactConceptSpec:
    """One configured SEC concept and its expected period semantics."""

    concept: str
    period_type: Literal["duration", "instant"]


CONCEPT_SPECS: tuple[CompanyFactConceptSpec, ...] = (
    CompanyFactConceptSpec(
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
        period_type="duration",
    ),
    CompanyFactConceptSpec(
        concept="NetIncomeLoss",
        period_type="duration",
    ),
    CompanyFactConceptSpec(
        concept="Assets",
        period_type="instant",
    ),
)


@dataclass(frozen=True)
class BronzeCompanyFactsResponse:
    """One immutable Bronze SEC company-facts response."""

    source_system: str
    source_endpoint: str
    project_symbol: str
    sec_cik: str
    entity_name: str
    source_response_id: str
    response_payload_json: str
    response_sha256: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class CompanyFactValidationIssue:
    """One validation rule failure for an individual SEC fact."""

    code: str
    field: str | None = None


@dataclass(frozen=True)
class RejectedCompanyFact:
    """Operational diagnostic for an invalid individual fact."""

    project_symbol: str
    concept: str
    observation_index: int
    accession_number: str | None
    issues: tuple[CompanyFactValidationIssue, ...]
    source_response_id: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class SilverCompanyFact:
    """One validated Silver SEC company fact."""

    source_system: str
    cik: str
    project_symbol: str
    taxonomy: str
    concept: str
    unit: str
    accession_number: str
    fact_value: Decimal
    period_start: date | None
    period_end: date
    filing_form: str
    filing_date: date
    entity_name: str | None
    concept_label: str | None
    filing_fiscal_year: int | None
    filing_fiscal_period: str | None
    frame: str | None
    source_response_id: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class CompanyFactsResponseTransformResult:
    """Result of transforming one selected Bronze response."""

    accepted: tuple[SilverCompanyFact, ...]
    rejected: tuple[RejectedCompanyFact, ...]
    unavailable_scopes: tuple[str, ...]
    duplicate_count: int

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    @property
    def unavailable_scope_count(self) -> int:
        return len(self.unavailable_scopes)


@dataclass(frozen=True)
class CompanyResponseSelectionResult:
    """Latest Bronze response selected for each configured company."""

    selected: tuple[BronzeCompanyFactsResponse, ...]
    bronze_response_count: int
    in_scope_response_count: int
    out_of_scope_response_count: int
    superseded_response_count: int
    tie_repeat_count: int

    @property
    def selected_count(self) -> int:
        return len(self.selected)


@dataclass(frozen=True)
class CompanyFactsSnapshotResult:
    """Complete current Silver company-facts snapshot."""

    selected: tuple[SilverCompanyFact, ...]
    rejected: tuple[RejectedCompanyFact, ...]
    selected_responses: tuple[BronzeCompanyFactsResponse, ...]
    bronze_response_count: int
    out_of_scope_response_count: int
    superseded_response_count: int
    tie_repeat_count: int
    duplicate_count: int
    unavailable_scopes: tuple[str, ...]

    @property
    def selected_count(self) -> int:
        return len(self.selected)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    @property
    def unavailable_scope_count(self) -> int:
        return len(self.unavailable_scopes)


def select_latest_company_responses(
    responses: Sequence[BronzeCompanyFactsResponse],
    configured_companies: Mapping[str, str],
) -> CompanyResponseSelectionResult:
    """Select the latest complete Bronze response for each configured company."""

    configuration = _normalize_configured_companies(configured_companies)

    seen_response_ids: set[str] = set()
    grouped: dict[str, list[BronzeCompanyFactsResponse]] = {
        symbol: [] for symbol in configuration
    }
    out_of_scope_count = 0

    for response in responses:
        normalized = _normalize_bronze_response(response)

        if normalized.source_response_id in seen_response_ids:
            raise ValueError(
                "source_response_id must be unique across Bronze company-facts "
                f"history: {normalized.source_response_id}"
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

        grouped[normalized.project_symbol].append(normalized)

    selected: list[BronzeCompanyFactsResponse] = []
    superseded_count = 0
    tie_repeat_count = 0

    for project_symbol in configuration:
        candidates = grouped[project_symbol]

        if not candidates:
            raise ValueError(
                f"{project_symbol}: no Bronze company-facts response is "
                "available for the configured company."
            )

        latest_fetched_at = max(candidate.fetched_at for candidate in candidates)
        latest = [
            candidate
            for candidate in candidates
            if candidate.fetched_at == latest_fetched_at
        ]

        superseded_count += len(candidates) - len(latest)

        if len(latest) > 1:
            raw_versions = {
                (
                    candidate.response_payload_json,
                    candidate.response_sha256,
                )
                for candidate in latest
            }

            if len(raw_versions) != 1:
                raise ValueError(
                    f"{project_symbol}: latest Bronze company-facts responses "
                    "share fetched_at but contain different raw payloads."
                )

            tie_repeat_count += len(latest) - 1

        selected.append(
            min(
                latest,
                key=lambda candidate: candidate.source_response_id,
            )
        )

    return CompanyResponseSelectionResult(
        selected=tuple(selected),
        bronze_response_count=len(responses),
        in_scope_response_count=sum(len(items) for items in grouped.values()),
        out_of_scope_response_count=out_of_scope_count,
        superseded_response_count=superseded_count,
        tie_repeat_count=tie_repeat_count,
    )


def transform_company_facts_response(
    response: BronzeCompanyFactsResponse,
    *,
    expected_cik: str,
) -> CompanyFactsResponseTransformResult:
    """Extract and validate the configured facts from one selected response."""

    normalized = _normalize_bronze_response(response)
    normalized_expected_cik = _normalize_cik(expected_cik, "expected_cik")

    if normalized.sec_cik != normalized_expected_cik:
        raise ValueError(
            f"{normalized.project_symbol}: selected Bronze sec_cik "
            f"{normalized.sec_cik} does not match expected CIK "
            f"{normalized_expected_cik}."
        )

    payload = _parse_payload(normalized.response_payload_json)
    parsed = parse_company_facts_response(payload)

    if parsed.cik != int(normalized_expected_cik):
        raise ValueError(
            f"{normalized.project_symbol}: SEC payload CIK {parsed.cik} "
            f"does not match configured CIK {normalized_expected_cik}."
        )

    if parsed.entity_name != normalized.entity_name:
        raise ValueError(
            f"{normalized.project_symbol}: Bronze entity_name does not "
            "match the selected SEC payload entityName."
        )

    taxonomy_block = parsed.facts.get(TAXONOMY)

    if taxonomy_block is None:
        return CompanyFactsResponseTransformResult(
            accepted=(),
            rejected=(),
            unavailable_scopes=tuple(
                f"{TAXONOMY}/{spec.concept}/{UNIT}"
                for spec in CONCEPT_SPECS
            ),
            duplicate_count=0,
        )

    if not isinstance(taxonomy_block, Mapping):
        raise ValueError(
            f"{normalized.project_symbol}: {TAXONOMY} facts must be "
            "a JSON object."
        )

    candidates: list[SilverCompanyFact] = []
    rejected: list[RejectedCompanyFact] = []
    unavailable: list[str] = []

    for spec in CONCEPT_SPECS:
        scope_name = f"{TAXONOMY}/{spec.concept}/{UNIT}"
        concept_block = taxonomy_block.get(spec.concept)

        if concept_block is None:
            unavailable.append(scope_name)
            continue

        if not isinstance(concept_block, Mapping):
            raise ValueError(
                f"{normalized.project_symbol}: concept {spec.concept} "
                "must be a JSON object."
            )

        concept_label = _optional_string(
            concept_block.get("label"),
            field_name=f"{spec.concept}.label",
        )

        units = concept_block.get("units")

        if units is None:
            unavailable.append(scope_name)
            continue

        if not isinstance(units, Mapping):
            raise ValueError(
                f"{normalized.project_symbol}: concept {spec.concept} "
                "units must be a JSON object."
            )

        observations = units.get(UNIT)

        if observations is None:
            unavailable.append(scope_name)
            continue

        if (
            isinstance(observations, (str, bytes))
            or not isinstance(observations, Sequence)
        ):
            raise ValueError(
                f"{normalized.project_symbol}: {scope_name} observations "
                "must be a JSON array."
            )

        for observation_index, observation in enumerate(observations):
            fact, issues, accession_number = _transform_observation(
                observation=observation,
                spec=spec,
                concept_label=concept_label,
                response=normalized,
            )

            if fact is not None:
                candidates.append(fact)
            else:
                rejected.append(
                    RejectedCompanyFact(
                        project_symbol=normalized.project_symbol,
                        concept=spec.concept,
                        observation_index=observation_index,
                        accession_number=accession_number,
                        issues=issues,
                        source_response_id=normalized.source_response_id,
                        fetched_at=normalized.fetched_at,
                        ingestion_run_id=normalized.ingestion_run_id,
                    )
                )

    deduplicated, duplicate_count = _deduplicate_facts(candidates)

    return CompanyFactsResponseTransformResult(
        accepted=deduplicated,
        rejected=tuple(rejected),
        unavailable_scopes=tuple(unavailable),
        duplicate_count=duplicate_count,
    )


def transform_company_facts_snapshot(
    responses: Sequence[BronzeCompanyFactsResponse],
    configured_companies: Mapping[str, str],
) -> CompanyFactsSnapshotResult:
    """Rebuild the current Silver company-facts snapshot from Bronze history."""

    configuration = _normalize_configured_companies(configured_companies)
    selection = select_latest_company_responses(
        responses,
        configuration,
    )

    accepted: list[SilverCompanyFact] = []
    rejected: list[RejectedCompanyFact] = []
    unavailable: list[str] = []
    duplicate_count = 0

    for response in selection.selected:
        result = transform_company_facts_response(
            response,
            expected_cik=configuration[response.project_symbol],
        )

        accepted.extend(result.accepted)
        rejected.extend(result.rejected)
        duplicate_count += result.duplicate_count
        unavailable.extend(
            f"{response.project_symbol}:{scope}"
            for scope in result.unavailable_scopes
        )

    final_facts, cross_response_duplicates = _deduplicate_facts(accepted)
    duplicate_count += cross_response_duplicates

    return CompanyFactsSnapshotResult(
        selected=final_facts,
        rejected=tuple(rejected),
        selected_responses=selection.selected,
        bronze_response_count=selection.bronze_response_count,
        out_of_scope_response_count=selection.out_of_scope_response_count,
        superseded_response_count=selection.superseded_response_count,
        tie_repeat_count=selection.tie_repeat_count,
        duplicate_count=duplicate_count,
        unavailable_scopes=tuple(unavailable),
    )


def _normalize_configured_companies(
    configured_companies: Mapping[str, str],
) -> dict[str, str]:
    if not isinstance(configured_companies, Mapping) or not configured_companies:
        raise ValueError("configured_companies must be a nonempty mapping.")

    normalized: dict[str, str] = {}
    seen_ciks: set[str] = set()

    for raw_symbol, raw_cik in configured_companies.items():
        if not isinstance(raw_symbol, str) or not raw_symbol.strip():
            raise ValueError(
                "configured company symbols must be nonblank strings."
            )

        symbol = raw_symbol.strip()
        cik = _normalize_cik(raw_cik, f"{symbol}.sec_cik")

        if symbol in normalized:
            raise ValueError(f"duplicate configured symbol: {symbol}")

        if cik in seen_ciks:
            raise ValueError(f"duplicate configured CIK: {cik}")

        normalized[symbol] = cik
        seen_ciks.add(cik)

    return normalized


def _normalize_bronze_response(
    response: BronzeCompanyFactsResponse,
) -> BronzeCompanyFactsResponse:
    if not isinstance(response, BronzeCompanyFactsResponse):
        raise ValueError(
            "responses must contain BronzeCompanyFactsResponse values."
        )

    source_system = _required_string(response.source_system, "source_system")
    source_endpoint = _required_string(
        response.source_endpoint,
        "source_endpoint",
    )
    project_symbol = _required_string(
        response.project_symbol,
        "project_symbol",
    )
    sec_cik = _normalize_cik(response.sec_cik, "sec_cik")
    entity_name = _required_string(response.entity_name, "entity_name")
    source_response_id = _required_string(
        response.source_response_id,
        "source_response_id",
    )
    response_payload_json = _required_string(
        response.response_payload_json,
        "response_payload_json",
        strip=False,
    )
    response_sha256 = _required_string(
        response.response_sha256,
        "response_sha256",
    )
    ingestion_run_id = _required_string(
        response.ingestion_run_id,
        "ingestion_run_id",
    )
    fetched_at = _normalize_utc_datetime(
        response.fetched_at,
        "fetched_at",
    )

    if source_system != SOURCE_SYSTEM:
        raise ValueError(
            f"source_system must be {SOURCE_SYSTEM!r}; got "
            f"{source_system!r}."
        )

    if source_endpoint != SOURCE_ENDPOINT:
        raise ValueError(
            f"source_endpoint must be {SOURCE_ENDPOINT!r}; got "
            f"{source_endpoint!r}."
        )

    return BronzeCompanyFactsResponse(
        source_system=source_system,
        source_endpoint=source_endpoint,
        project_symbol=project_symbol,
        sec_cik=sec_cik,
        entity_name=entity_name,
        source_response_id=source_response_id,
        response_payload_json=response_payload_json,
        response_sha256=response_sha256,
        fetched_at=fetched_at,
        ingestion_run_id=ingestion_run_id,
    )


def _parse_payload(raw_json: str) -> object:
    def reject_constant(value: str) -> object:
        raise ValueError(f"invalid JSON numeric constant: {value}")

    try:
        return json.loads(
            raw_json,
            parse_float=Decimal,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            "response_payload_json must contain valid JSON."
        ) from exc


def _transform_observation(
    *,
    observation: object,
    spec: CompanyFactConceptSpec,
    concept_label: str | None,
    response: BronzeCompanyFactsResponse,
) -> tuple[
    SilverCompanyFact | None,
    tuple[CompanyFactValidationIssue, ...],
    str | None,
]:
    if not isinstance(observation, Mapping):
        return (
            None,
            (
                CompanyFactValidationIssue(
                    code="observation_not_object",
                ),
            ),
            None,
        )

    issues: list[CompanyFactValidationIssue] = []

    accession_number = _observation_required_string(
        observation.get("accn"),
        "accn",
        issues,
    )

    if (
        accession_number is not None
        and not ACCESSION_PATTERN.fullmatch(accession_number)
    ):
        issues.append(
            CompanyFactValidationIssue(
                code="invalid_accession_number",
                field="accn",
            )
        )

    fact_value = _parse_fact_value(
        observation.get("val"),
        issues,
    )

    period_end = _parse_required_date(
        observation.get("end"),
        "end",
        issues,
    )

    raw_start = observation.get("start")

    if spec.period_type == "duration":
        period_start = _parse_required_date(
            raw_start,
            "start",
            issues,
        )

        if (
            period_start is not None
            and period_end is not None
            and period_start > period_end
        ):
            issues.append(
                CompanyFactValidationIssue(
                    code="period_start_after_end",
                    field="start",
                )
            )
    else:
        period_start = None

        if raw_start is not None:
            issues.append(
                CompanyFactValidationIssue(
                    code="unexpected_start_for_instant_fact",
                    field="start",
                )
            )

    filing_form = _observation_required_string(
        observation.get("form"),
        "form",
        issues,
    )
    filing_date = _parse_required_date(
        observation.get("filed"),
        "filed",
        issues,
    )
    filing_fiscal_year = _parse_optional_integer(
        observation.get("fy"),
        "fy",
        issues,
    )
    filing_fiscal_period = _observation_optional_string(
        observation.get("fp"),
        "fp",
        issues,
    )
    frame = _observation_optional_string(
        observation.get("frame"),
        "frame",
        issues,
    )

    if issues:
        return None, tuple(issues), accession_number

    assert accession_number is not None
    assert fact_value is not None
    assert period_end is not None
    assert filing_form is not None
    assert filing_date is not None

    return (
        SilverCompanyFact(
            source_system=SOURCE_SYSTEM,
            cik=response.sec_cik,
            project_symbol=response.project_symbol,
            taxonomy=TAXONOMY,
            concept=spec.concept,
            unit=UNIT,
            accession_number=accession_number,
            fact_value=fact_value,
            period_start=period_start,
            period_end=period_end,
            filing_form=filing_form,
            filing_date=filing_date,
            entity_name=response.entity_name,
            concept_label=concept_label,
            filing_fiscal_year=filing_fiscal_year,
            filing_fiscal_period=filing_fiscal_period,
            frame=frame,
            source_response_id=response.source_response_id,
            fetched_at=response.fetched_at,
            ingestion_run_id=response.ingestion_run_id,
        ),
        (),
        accession_number,
    )


def _deduplicate_facts(
    facts: Sequence[SilverCompanyFact],
) -> tuple[tuple[SilverCompanyFact, ...], int]:
    by_key: dict[tuple[object, ...], SilverCompanyFact] = {}
    duplicate_count = 0

    for fact in facts:
        key = _fact_business_key(fact)
        existing = by_key.get(key)

        if existing is None:
            by_key[key] = fact
            continue

        if _fact_content_signature(existing) != _fact_content_signature(fact):
            raise ValueError(
                "conflicting SEC company facts share Silver business key: "
                f"{key}"
            )

        duplicate_count += 1

    return (
        tuple(sorted(by_key.values(), key=_fact_sort_key)),
        duplicate_count,
    )


def _fact_business_key(fact: SilverCompanyFact) -> tuple[object, ...]:
    return (
        fact.source_system,
        fact.cik,
        fact.taxonomy,
        fact.concept,
        fact.unit,
        fact.period_start,
        fact.period_end,
        fact.accession_number,
    )


def _fact_content_signature(fact: SilverCompanyFact) -> tuple[object, ...]:
    return (
        fact.project_symbol,
        fact.fact_value,
        fact.filing_form,
        fact.filing_date,
        fact.entity_name,
        fact.concept_label,
        fact.filing_fiscal_year,
        fact.filing_fiscal_period,
        fact.frame,
    )


def _fact_sort_key(fact: SilverCompanyFact) -> tuple[object, ...]:
    return (
        fact.project_symbol,
        fact.concept,
        fact.period_end,
        fact.period_start or date.min,
        fact.accession_number,
    )


def _required_string(
    value: object,
    field_name: str,
    *,
    strip: bool = True,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")

    normalized = value.strip() if strip else value

    if not normalized.strip():
        raise ValueError(f"{field_name} must be nonblank.")

    return normalized


def _normalize_cik(value: object, field_name: str) -> str:
    normalized = _required_string(value, field_name)

    if not CIK_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must contain exactly 10 digits."
        )

    return normalized


def _normalize_utc_datetime(
    value: object,
    field_name: str,
) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime.")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")

    return value.astimezone(timezone.utc)


def _optional_string(
    value: object,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string when present.")

    normalized = value.strip()
    return normalized or None


def _observation_required_string(
    value: object,
    field_name: str,
    issues: list[CompanyFactValidationIssue],
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        issues.append(
            CompanyFactValidationIssue(
                code="missing_or_invalid_required_string",
                field=field_name,
            )
        )
        return None

    return value.strip()


def _observation_optional_string(
    value: object,
    field_name: str,
    issues: list[CompanyFactValidationIssue],
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        issues.append(
            CompanyFactValidationIssue(
                code="invalid_optional_string",
                field=field_name,
            )
        )
        return None

    normalized = value.strip()
    return normalized or None


def _parse_required_date(
    value: object,
    field_name: str,
    issues: list[CompanyFactValidationIssue],
) -> date | None:
    if not isinstance(value, str) or not value.strip():
        issues.append(
            CompanyFactValidationIssue(
                code="missing_or_invalid_date",
                field=field_name,
            )
        )
        return None

    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        issues.append(
            CompanyFactValidationIssue(
                code="missing_or_invalid_date",
                field=field_name,
            )
        )
        return None


def _parse_optional_integer(
    value: object,
    field_name: str,
    issues: list[CompanyFactValidationIssue],
) -> int | None:
    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int):
        issues.append(
            CompanyFactValidationIssue(
                code="invalid_optional_integer",
                field=field_name,
            )
        )
        return None

    return value


def _parse_fact_value(
    value: object,
    issues: list[CompanyFactValidationIssue],
) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        issues.append(
            CompanyFactValidationIssue(
                code="invalid_fact_value",
                field="val",
            )
        )
        return None

    decimal_value = Decimal(value) if isinstance(value, int) else value

    if not decimal_value.is_finite():
        issues.append(
            CompanyFactValidationIssue(
                code="invalid_fact_value",
                field="val",
            )
        )
        return None

    try:
        with localcontext() as context:
            context.prec = max(60, len(decimal_value.as_tuple().digits) + 16)
            quantized = decimal_value.quantize(DECIMAL_SCALE)
    except InvalidOperation:
        issues.append(
            CompanyFactValidationIssue(
                code="fact_value_out_of_range",
                field="val",
            )
        )
        return None

    if quantized != decimal_value:
        issues.append(
            CompanyFactValidationIssue(
                code="fact_value_exceeds_scale",
                field="val",
            )
        )
        return None

    if abs(quantized) > MAX_DECIMAL_28_8:
        issues.append(
            CompanyFactValidationIssue(
                code="fact_value_out_of_range",
                field="val",
            )
        )
        return None

    return quantized
