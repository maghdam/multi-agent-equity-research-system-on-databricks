"""Pure validation and transformation logic for Silver daily prices."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from equity_research.alpaca_prices import parse_price_response_page


NEW_YORK = ZoneInfo("America/New_York")

EXPECTED_FEED = "sip"
EXPECTED_ADJUSTMENT = "split"
EXPECTED_TIMEFRAME = "1Day"
EXPECTED_CURRENCY = "USD"


@dataclass(frozen=True)
class PriceRequestMetadata:
    """Request metadata required to interpret one Bronze response."""

    requested_symbols: tuple[str, ...]
    feed: str
    adjustment: str
    timeframe: str
    currency: str


@dataclass(frozen=True)
class PriceValidationIssue:
    """One rule failure for an individual in-scope price bar."""

    code: str
    field: str | None = None


@dataclass(frozen=True)
class SilverPriceCandidate:
    """One accepted, typed Silver daily-price candidate."""

    symbol: str
    bar_timestamp: datetime
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    feed: str
    adjustment: str
    timeframe: str
    currency: str
    source_system: str
    source_response_id: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class RejectedPriceBar:
    """One invalid in-scope bar without retaining its raw payload."""

    symbol: str
    bar_index: int
    bar_timestamp: datetime | None
    issues: tuple[PriceValidationIssue, ...]


@dataclass(frozen=True)
class PriceResponseTransformResult:
    """Classification result for one Bronze price-response row."""

    accepted: tuple[SilverPriceCandidate, ...]
    rejected: tuple[RejectedPriceBar, ...]
    out_of_scope_count: int

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

@dataclass(frozen=True)
class PriceSnapshotSelectionResult:
    """Deterministic current Silver selection across Bronze responses."""

    selected: tuple[SilverPriceCandidate, ...]
    duplicate_count: int
    superseded_count: int

    @property
    def selected_count(self) -> int:
        return len(self.selected)

@dataclass(frozen=True)
class BronzePriceResponse:
    """Minimal Bronze row required for Silver price transformation."""

    source_system: str
    source_response_id: str
    request_parameters_json: str
    response_payload_json: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class PriceSnapshotTransformResult:
    """Complete deterministic Silver-price transformation result."""

    selected: tuple[SilverPriceCandidate, ...]
    rejected: tuple[RejectedPriceBar, ...]
    bronze_response_count: int
    accepted_candidate_count: int
    rejected_count: int
    out_of_scope_count: int
    duplicate_count: int
    superseded_count: int

    @property
    def selected_count(self) -> int:
        return len(self.selected)

def parse_price_request_metadata(
    request_parameters_json: str,
) -> PriceRequestMetadata:
    """Parse the non-secret request settings preserved in Bronze."""

    if (
        not isinstance(request_parameters_json, str)
        or not request_parameters_json.strip()
    ):
        raise ValueError(
            "request_parameters_json must be a nonblank string."
        )

    try:
        payload = json.loads(request_parameters_json)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "request_parameters_json must contain valid JSON."
        ) from exc

    if not isinstance(payload, Mapping):
        raise ValueError(
            "request_parameters_json must contain a JSON object."
        )

    raw_symbols = _required_string(payload, "symbols")
    requested_symbols = tuple(
        symbol.strip()
        for symbol in raw_symbols.split(",")
    )

    if (
        not requested_symbols
        or any(not symbol for symbol in requested_symbols)
    ):
        raise ValueError(
            "request symbols must contain nonblank symbols."
        )

    if len(set(requested_symbols)) != len(requested_symbols):
        raise ValueError(
            "request symbols must be unique."
        )

    return PriceRequestMetadata(
        requested_symbols=requested_symbols,
        feed=_required_string(payload, "feed"),
        adjustment=_required_string(payload, "adjustment"),
        timeframe=_required_string(payload, "timeframe"),
        currency=_required_string(payload, "currency"),
    )


def transform_price_response(
    *,
    response_payload_json: str,
    request_parameters_json: str,
    source_system: str,
    source_response_id: str,
    fetched_at: datetime,
    ingestion_run_id: str,
    configured_symbols: Sequence[str],
) -> PriceResponseTransformResult:
    """Transform and classify one Bronze Alpaca price-response row."""

    if source_system != "alpaca":
        raise ValueError(
            "source_system must be alpaca for Silver daily prices."
        )

    normalized_response_id = _required_identifier(
        source_response_id,
        "source_response_id",
    )
    normalized_run_id = _required_identifier(
        ingestion_run_id,
        "ingestion_run_id",
    )
    normalized_fetched_at = _require_aware_datetime(
        fetched_at,
        "fetched_at",
    ).astimezone(timezone.utc)

    current_symbols = _normalize_symbols(
        configured_symbols,
        "configured_symbols",
    )

    request_metadata = parse_price_request_metadata(
        request_parameters_json
    )

    if (
        not isinstance(response_payload_json, str)
        or not response_payload_json.strip()
    ):
        raise ValueError(
            "response_payload_json must be a nonblank string."
        )

    try:
        payload = json.loads(
            response_payload_json,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=Decimal,
        )
    except (json.JSONDecodeError, ArithmeticError) as exc:
        raise ValueError(
            "response_payload_json must contain valid JSON."
        ) from exc

    try:
        response_page = parse_price_response_page(payload)
    except ValueError as exc:
        raise ValueError(
            "response_payload_json contains an invalid "
            "Alpaca price-response page."
        ) from exc

    requested_symbol_set = set(
        request_metadata.requested_symbols
    )
    unexpected_symbols = (
        set(response_page.bars) - requested_symbol_set
    )

    if unexpected_symbols:
        raise ValueError(
            "response contains symbols absent from the "
            "original request metadata."
        )

    if not _is_supported_request(request_metadata):
        return PriceResponseTransformResult(
            accepted=(),
            rejected=(),
            out_of_scope_count=response_page.record_count,
        )

    current_symbol_set = set(current_symbols)
    accepted: list[SilverPriceCandidate] = []
    rejected: list[RejectedPriceBar] = []
    out_of_scope_count = 0

    for symbol, records in response_page.bars.items():
        if symbol not in current_symbol_set:
            out_of_scope_count += len(records)
            continue

        for bar_index, record in enumerate(records):
            transformed = _transform_bar(
                symbol=symbol,
                bar_index=bar_index,
                record=record,
                request_metadata=request_metadata,
                source_response_id=normalized_response_id,
                fetched_at=normalized_fetched_at,
                ingestion_run_id=normalized_run_id,
            )

            if isinstance(transformed, SilverPriceCandidate):
                accepted.append(transformed)
            else:
                rejected.append(transformed)

    return PriceResponseTransformResult(
        accepted=tuple(accepted),
        rejected=tuple(rejected),
        out_of_scope_count=out_of_scope_count,
    )

def select_current_price_snapshot(
    candidates: Sequence[SilverPriceCandidate],
) -> PriceSnapshotSelectionResult:
    """Select one current valid observation per Silver business key."""

    grouped: dict[
        tuple[str, datetime, str, str],
        list[SilverPriceCandidate],
    ] = {}

    for candidate in candidates:
        if not isinstance(candidate, SilverPriceCandidate):
            raise ValueError(
                "candidates must contain SilverPriceCandidate values."
            )

        key = _price_business_key(candidate)
        grouped.setdefault(key, []).append(candidate)

    selected: list[SilverPriceCandidate] = []
    duplicate_count = 0
    superseded_count = 0

    for key in sorted(grouped):
        observations = grouped[key]

        by_fetched_at: dict[
            datetime,
            list[SilverPriceCandidate],
        ] = {}

        for observation in observations:
            by_fetched_at.setdefault(
                observation.fetched_at,
                [],
            ).append(observation)

        normalized_by_time: dict[
            datetime,
            tuple[SilverPriceCandidate, int],
        ] = {}

        for fetched_at, same_time_observations in (
            by_fetched_at.items()
        ):
            content_signatures = {
                _price_business_content(observation)
                for observation in same_time_observations
            }

            if len(content_signatures) != 1:
                raise ValueError(
                    "conflicting Silver price candidates share "
                    "the same business key and fetched_at."
                )

            chosen = min(
                same_time_observations,
                key=lambda observation: (
                    observation.source_response_id
                ),
            )

            duplicates_here = (
                len(same_time_observations) - 1
            )

            duplicate_count += duplicates_here

            normalized_by_time[fetched_at] = (
                chosen,
                duplicates_here,
            )

        latest_fetched_at = max(normalized_by_time)
        latest_candidate = normalized_by_time[
            latest_fetched_at
        ][0]

        for fetched_at, (
            observation,
            _,
        ) in normalized_by_time.items():
            if fetched_at == latest_fetched_at:
                continue

            if (
                _price_business_content(observation)
                == _price_business_content(latest_candidate)
            ):
                duplicate_count += 1
            else:
                superseded_count += 1

        selected.append(latest_candidate)

    return PriceSnapshotSelectionResult(
        selected=tuple(selected),
        duplicate_count=duplicate_count,
        superseded_count=superseded_count,
    )

def transform_price_snapshot(
    *,
    bronze_responses: Sequence[BronzePriceResponse],
    configured_symbols: Sequence[str],
) -> PriceSnapshotTransformResult:
    """Rebuild the current Silver daily-price snapshot from Bronze history."""

    current_symbols = _normalize_symbols(
        configured_symbols,
        "configured_symbols",
    )

    if isinstance(bronze_responses, (str, bytes)):
        raise ValueError(
            "bronze_responses must be a sequence of BronzePriceResponse values."
        )

    accepted_candidates: list[SilverPriceCandidate] = []
    rejected: list[RejectedPriceBar] = []
    out_of_scope_count = 0
    response_count = 0

    for bronze_response in bronze_responses:
        if not isinstance(
            bronze_response,
            BronzePriceResponse,
        ):
            raise ValueError(
                "bronze_responses must contain BronzePriceResponse values."
            )

        response_count += 1

        transformed = transform_price_response(
            response_payload_json=(
                bronze_response.response_payload_json
            ),
            request_parameters_json=(
                bronze_response.request_parameters_json
            ),
            source_system=bronze_response.source_system,
            source_response_id=(
                bronze_response.source_response_id
            ),
            fetched_at=bronze_response.fetched_at,
            ingestion_run_id=(
                bronze_response.ingestion_run_id
            ),
            configured_symbols=current_symbols,
        )

        accepted_candidates.extend(
            transformed.accepted
        )
        rejected.extend(
            transformed.rejected
        )
        out_of_scope_count += (
            transformed.out_of_scope_count
        )

    selection = select_current_price_snapshot(
        accepted_candidates
    )

    return PriceSnapshotTransformResult(
        selected=selection.selected,
        rejected=tuple(rejected),
        bronze_response_count=response_count,
        accepted_candidate_count=len(
            accepted_candidates
        ),
        rejected_count=len(rejected),
        out_of_scope_count=out_of_scope_count,
        duplicate_count=selection.duplicate_count,
        superseded_count=selection.superseded_count,
    )

def _transform_bar(
    *,
    symbol: str,
    bar_index: int,
    record: Mapping[str, object],
    request_metadata: PriceRequestMetadata,
    source_response_id: str,
    fetched_at: datetime,
    ingestion_run_id: str,
) -> SilverPriceCandidate | RejectedPriceBar:
    """Validate and type one individual in-scope price bar."""

    issues: list[PriceValidationIssue] = []

    bar_timestamp = _parse_bar_timestamp(
        record,
        issues,
    )

    open_value = _parse_decimal_field(
        record,
        "o",
        "open",
        issues,
    )
    high_value = _parse_decimal_field(
        record,
        "h",
        "high",
        issues,
    )
    low_value = _parse_decimal_field(
        record,
        "l",
        "low",
        issues,
    )
    close_value = _parse_decimal_field(
        record,
        "c",
        "close",
        issues,
    )
    volume_value = _parse_decimal_field(
        record,
        "v",
        "volume",
        issues,
    )

    if (
        low_value is not None
        and open_value is not None
        and high_value is not None
        and not low_value <= open_value <= high_value
    ):
        issues.append(
            PriceValidationIssue(
                code="outside_low_high",
                field="open",
            )
        )

    if (
        low_value is not None
        and close_value is not None
        and high_value is not None
        and not low_value <= close_value <= high_value
    ):
        issues.append(
            PriceValidationIssue(
                code="outside_low_high",
                field="close",
            )
        )

    trading_date: date | None = None

    if bar_timestamp is not None:
        trading_date = bar_timestamp.astimezone(
            NEW_YORK
        ).date()

        fetched_date = fetched_at.astimezone(
            NEW_YORK
        ).date()

        if trading_date >= fetched_date:
            issues.append(
                PriceValidationIssue(
                    code="incomplete_trading_day",
                    field="trading_date",
                )
            )

    if issues:
        return RejectedPriceBar(
            symbol=symbol,
            bar_index=bar_index,
            bar_timestamp=bar_timestamp,
            issues=tuple(issues),
        )

    assert bar_timestamp is not None
    assert trading_date is not None
    assert open_value is not None
    assert high_value is not None
    assert low_value is not None
    assert close_value is not None
    assert volume_value is not None

    return SilverPriceCandidate(
        symbol=symbol,
        bar_timestamp=bar_timestamp,
        trading_date=trading_date,
        open=open_value,
        high=high_value,
        low=low_value,
        close=close_value,
        volume=volume_value,
        feed=request_metadata.feed,
        adjustment=request_metadata.adjustment,
        timeframe=request_metadata.timeframe,
        currency=request_metadata.currency,
        source_system="alpaca",
        source_response_id=source_response_id,
        fetched_at=fetched_at,
        ingestion_run_id=ingestion_run_id,
    )


def _parse_bar_timestamp(
    record: Mapping[str, object],
    issues: list[PriceValidationIssue],
) -> datetime | None:
    """Parse one required timezone-aware bar timestamp."""

    if "t" not in record or record["t"] is None:
        issues.append(
            PriceValidationIssue(
                code="required_field",
                field="bar_timestamp",
            )
        )
        return None

    value = record["t"]

    if not isinstance(value, str) or not value.strip():
        issues.append(
            PriceValidationIssue(
                code="invalid_timestamp",
                field="bar_timestamp",
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
            PriceValidationIssue(
                code="invalid_timestamp",
                field="bar_timestamp",
            )
        )
        return None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        issues.append(
            PriceValidationIssue(
                code="invalid_timestamp",
                field="bar_timestamp",
            )
        )
        return None

    return parsed.astimezone(timezone.utc)


def _parse_decimal_field(
    record: Mapping[str, object],
    source_field: str,
    silver_field: str,
    issues: list[PriceValidationIssue],
) -> Decimal | None:
    """Validate one required positive DECIMAL(20,8) value."""

    if source_field not in record or record[source_field] is None:
        issues.append(
            PriceValidationIssue(
                code="required_field",
                field=silver_field,
            )
        )
        return None

    value = record[source_field]

    if isinstance(value, bool) or not isinstance(value, Decimal):
        issues.append(
            PriceValidationIssue(
                code="numeric_type",
                field=silver_field,
            )
        )
        return None

    if not value.is_finite():
        issues.append(
            PriceValidationIssue(
                code="nonfinite",
                field=silver_field,
            )
        )
        return None

    if not _fits_decimal_20_8(value):
        issues.append(
            PriceValidationIssue(
                code="decimal_20_8",
                field=silver_field,
            )
        )
        return None

    if value <= 0:
        issues.append(
            PriceValidationIssue(
                code="not_positive",
                field=silver_field,
            )
        )

    return value


def _fits_decimal_20_8(value: Decimal) -> bool:
    """Return whether value fits exactly without rounding."""

    normalized = value.copy_abs().normalize()
    _, digits, exponent = normalized.as_tuple()

    if exponent >= 0:
        integer_digits = len(digits) + exponent
        fractional_digits = 0
    else:
        fractional_digits = -exponent
        integer_digits = max(
            len(digits) - fractional_digits,
            0,
        )

    return (
        integer_digits <= 12
        and fractional_digits <= 8
    )


def _is_supported_request(
    metadata: PriceRequestMetadata,
) -> bool:
    """Return whether one Bronze request belongs to this Silver product."""

    return (
        metadata.feed == EXPECTED_FEED
        and metadata.adjustment == EXPECTED_ADJUSTMENT
        and metadata.timeframe == EXPECTED_TIMEFRAME
        and metadata.currency == EXPECTED_CURRENCY
    )


def _normalize_symbols(
    symbols: Sequence[str],
    field_name: str,
) -> tuple[str, ...]:
    """Normalize and validate a nonempty unique symbol sequence."""

    if isinstance(symbols, str):
        raise ValueError(
            f"{field_name} must be a sequence, not one string."
        )

    normalized: list[str] = []

    for symbol in symbols:
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError(
                f"{field_name} must contain nonblank strings."
            )

        normalized.append(symbol.strip())

    if not normalized:
        raise ValueError(
            f"{field_name} must not be empty."
        )

    if len(set(normalized)) != len(normalized):
        raise ValueError(
            f"{field_name} must not contain duplicates."
        )

    return tuple(normalized)


def _required_string(
    payload: Mapping[str, object],
    field_name: str,
) -> str:
    """Return one required nonblank JSON string."""

    value = payload.get(field_name)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field_name} must be a nonblank string."
        )

    return value.strip()


def _required_identifier(
    value: object,
    field_name: str,
) -> str:
    """Validate one required nonblank provenance identifier."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field_name} must be a nonblank string."
        )

    return value.strip()


def _require_aware_datetime(
    value: object,
    field_name: str,
) -> datetime:
    """Require one timezone-aware Python datetime."""

    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{field_name} must be a timezone-aware datetime."
        )

    return value

def _price_business_key(
    candidate: SilverPriceCandidate,
) -> tuple[str, datetime, str, str]:
    """Return the published Silver business key."""

    return (
        candidate.symbol,
        candidate.bar_timestamp,
        candidate.feed,
        candidate.adjustment,
    )


def _price_business_content(
    candidate: SilverPriceCandidate,
) -> tuple[object, ...]:
    """Return normalized business fields excluding source provenance."""

    return (
        candidate.symbol,
        candidate.bar_timestamp,
        candidate.trading_date,
        candidate.open,
        candidate.high,
        candidate.low,
        candidate.close,
        candidate.volume,
        candidate.feed,
        candidate.adjustment,
        candidate.timeframe,
        candidate.currency,
        candidate.source_system,
    )