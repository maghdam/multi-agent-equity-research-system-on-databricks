"""Pure-Python Gold fundamental-metric calculation and validation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN, localcontext


EXPECTED_SOURCE_SYSTEM = "sec"
EXPECTED_TAXONOMY = "us-gaap"
EXPECTED_UNIT = "USD"

REVENUE_CONCEPT = "RevenueFromContractWithCustomerExcludingAssessedTax"
NET_INCOME_CONCEPT = "NetIncomeLoss"
ASSETS_CONCEPT = "Assets"
EXPECTED_CONCEPTS = frozenset(
    (REVENUE_CONCEPT, NET_INCOME_CONCEPT, ASSETS_CONCEPT)
)
ELIGIBLE_CURRENT_FORMS = frozenset(("10-K", "10-Q"))

CIK_PATTERN = re.compile(r"[0-9]{10}")
ACCESSION_PATTERN = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")

ANNUAL_MIN_DAYS = 330
ANNUAL_MAX_DAYS = 380
COMPARABLE_MIN_GAP_DAYS = 350
COMPARABLE_MAX_GAP_DAYS = 380
YTD_DURATION_TOLERANCE_DAYS = 2

MONEY_QUANTUM = Decimal("0.00000001")
RATE_QUANTUM = Decimal("0.0000000001")


@dataclass(frozen=True)
class FundamentalFactObservation:
    """One validated Silver company-fact row required by Gold."""

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
    source_response_id: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class GoldFundamentalMetric:
    """One current Gold fundamental-metrics row."""

    source_system: str
    symbol: str
    cik: str
    as_of_date: date
    fundamental_period_end: date
    latest_filing_form: str
    latest_accession_number: str
    revenue_ttm: Decimal
    net_income_ttm: Decimal
    net_margin_ttm: Decimal
    assets_latest: Decimal
    revenue_growth_latest_fy: Decimal
    net_income_change_latest_fy: Decimal
    latest_fy_end: date
    prior_fy_end: date
    ttm_derivation_method: str
    latest_source_response_id: str
    latest_source_fetched_at: datetime
    latest_source_ingestion_run_id: str


@dataclass(frozen=True)
class _AnnualPair:
    period_start: date
    period_end: date
    revenue: Decimal
    net_income: Decimal


def build_fundamental_metrics_snapshot(
    *,
    observations: Sequence[FundamentalFactObservation],
    configured_companies: Mapping[str, str],
) -> tuple[GoldFundamentalMetric, ...]:
    """Build one deterministic current Gold row per configured company."""

    configuration = _normalize_configured_companies(configured_companies)
    if isinstance(observations, (str, bytes)):
        raise ValueError(
            "observations must be a sequence of FundamentalFactObservation values."
        )

    grouped: dict[str, list[FundamentalFactObservation]] = {
        symbol: [] for symbol in configuration
    }

    for observation in observations:
        if not isinstance(observation, FundamentalFactObservation):
            raise ValueError(
                "observations must contain FundamentalFactObservation values."
            )

        fact = _validate_observation(observation)
        expected_cik = configuration.get(fact.project_symbol)

        if expected_cik is None:
            raise ValueError(
                "unexpected Silver company for Gold fundamental metrics: "
                f"{fact.project_symbol!r}."
            )
        if fact.cik != expected_cik:
            raise ValueError(
                f"{fact.project_symbol}: Silver CIK {fact.cik} does not match "
                f"configured CIK {expected_cik}."
            )

        grouped[fact.project_symbol].append(fact)

    if any(not grouped[symbol] for symbol in configuration):
        missing = next(symbol for symbol in configuration if not grouped[symbol])
        raise ValueError(
            f"configured company {missing} has no Silver company facts."
        )

    metrics = tuple(
        _calculate_company_metric(
            symbol=symbol,
            cik=configuration[symbol],
            rows=grouped[symbol],
        )
        for symbol in sorted(configuration)
    )

    if len(metrics) != len(configuration):
        raise ValueError("Gold fundamental-metrics snapshot is incomplete.")

    keys = {(metric.symbol, metric.as_of_date) for metric in metrics}
    if len(keys) != len(metrics):
        raise ValueError("Gold fundamental-metrics business keys are not unique.")

    return metrics


def _calculate_company_metric(
    *,
    symbol: str,
    cik: str,
    rows: Sequence[FundamentalFactObservation],
) -> GoldFundamentalMetric:
    provenance = {
        (row.source_response_id, row.fetched_at, row.ingestion_run_id)
        for row in rows
    }
    if len(provenance) != 1:
        raise ValueError(
            f"{symbol}: Silver company facts do not share one source snapshot."
        )

    source_response_id, source_fetched_at, source_ingestion_run_id = next(
        iter(provenance)
    )
    latest_form, latest_filing_date, latest_accession, selected_rows = (
        _select_latest_filing(rows, symbol)
    )
    fundamental_period_end = max(row.period_end for row in selected_rows)
    assets = _select_current_assets(
        selected_rows, fundamental_period_end, symbol
    )
    annual_pairs = _build_annual_pairs(rows, symbol)

    if latest_form == "10-K":
        current_revenue = _select_current_duration_fact(
            selected_rows,
            REVENUE_CONCEPT,
            fundamental_period_end,
            symbol,
            require_annual=True,
        )
        current_net_income = _select_current_duration_fact(
            selected_rows,
            NET_INCOME_CONCEPT,
            fundamental_period_end,
            symbol,
            require_annual=True,
        )
        _require_same_period(
            current_revenue,
            current_net_income,
            f"{symbol}: current 10-K revenue/net-income periods",
        )

        latest_annual = _annual_pair_ending(
            annual_pairs, fundamental_period_end, symbol
        )
        if (
            latest_annual.period_start != current_revenue.period_start
            or latest_annual.revenue != current_revenue.fact_value
            or latest_annual.net_income != current_net_income.fact_value
        ):
            raise ValueError(
                f"{symbol}: selected 10-K annual facts disagree with the "
                "latest-version annual basis."
            )

        revenue_ttm = current_revenue.fact_value
        net_income_ttm = current_net_income.fact_value
        ttm_method = "annual"

    elif latest_form == "10-Q":
        current_revenue = _select_longest_current_duration(
            selected_rows, REVENUE_CONCEPT, fundamental_period_end, symbol
        )
        current_net_income = _select_longest_current_duration(
            selected_rows, NET_INCOME_CONCEPT, fundamental_period_end, symbol
        )
        _require_same_period(
            current_revenue,
            current_net_income,
            f"{symbol}: current YTD revenue/net-income periods",
        )

        prior_revenue = _select_prior_comparable_ytd(
            selected_rows, REVENUE_CONCEPT, current_revenue, symbol
        )
        prior_net_income = _select_prior_comparable_ytd(
            selected_rows, NET_INCOME_CONCEPT, current_net_income, symbol
        )
        _require_same_period(
            prior_revenue,
            prior_net_income,
            f"{symbol}: prior-year YTD revenue/net-income periods",
        )

        bridge_end = current_revenue.period_start - timedelta(days=1)
        latest_annual = _annual_pair_ending(annual_pairs, bridge_end, symbol)
        revenue_ttm = (
            latest_annual.revenue
            + current_revenue.fact_value
            - prior_revenue.fact_value
        )
        net_income_ttm = (
            latest_annual.net_income
            + current_net_income.fact_value
            - prior_net_income.fact_value
        )
        ttm_method = "annual_plus_ytd_minus_prior_ytd"

    else:  # pragma: no cover - guarded by latest filing selection
        raise AssertionError("latest filing form should already be eligible")

    prior_annual = _prior_annual_pair(annual_pairs, latest_annual, symbol)

    with localcontext() as context:
        context.prec = 50
        if revenue_ttm <= 0:
            raise ValueError(f"{symbol}: TTM revenue must be positive.")
        if prior_annual.revenue <= 0:
            raise ValueError(
                f"{symbol}: prior full-year revenue must be positive."
            )

        net_margin = net_income_ttm / revenue_ttm
        revenue_growth = (
            latest_annual.revenue / prior_annual.revenue - Decimal("1")
        )
        net_income_change = (
            latest_annual.net_income - prior_annual.net_income
        )

    metric = GoldFundamentalMetric(
        source_system=EXPECTED_SOURCE_SYSTEM,
        symbol=symbol,
        cik=cik,
        as_of_date=latest_filing_date,
        fundamental_period_end=fundamental_period_end,
        latest_filing_form=latest_form,
        latest_accession_number=latest_accession,
        revenue_ttm=_quantize_money(revenue_ttm),
        net_income_ttm=_quantize_money(net_income_ttm),
        net_margin_ttm=_quantize_rate(net_margin),
        assets_latest=_quantize_money(assets.fact_value),
        revenue_growth_latest_fy=_quantize_rate(revenue_growth),
        net_income_change_latest_fy=_quantize_money(net_income_change),
        latest_fy_end=latest_annual.period_end,
        prior_fy_end=prior_annual.period_end,
        ttm_derivation_method=ttm_method,
        latest_source_response_id=source_response_id,
        latest_source_fetched_at=source_fetched_at,
        latest_source_ingestion_run_id=source_ingestion_run_id,
    )
    _validate_metric(metric)
    return metric


def _select_latest_filing(
    rows: Sequence[FundamentalFactObservation],
    symbol: str,
) -> tuple[str, date, str, tuple[FundamentalFactObservation, ...]]:
    eligible = tuple(
        row for row in rows if row.filing_form in ELIGIBLE_CURRENT_FORMS
    )
    if not eligible:
        raise ValueError(f"{symbol}: no eligible 10-K or 10-Q facts are available.")

    latest_date = max(row.filing_date for row in eligible)
    latest = tuple(row for row in eligible if row.filing_date == latest_date)
    accessions = {row.accession_number for row in latest}
    if len(accessions) != 1:
        raise ValueError(
            f"{symbol}: latest eligible filing date is ambiguous across "
            "multiple accessions."
        )

    accession = next(iter(accessions))
    selected = tuple(row for row in latest if row.accession_number == accession)
    forms = {row.filing_form for row in selected}
    if len(forms) != 1:
        raise ValueError(
            f"{symbol}: selected accession has inconsistent filing forms."
        )

    return next(iter(forms)), latest_date, accession, selected


def _select_current_assets(
    rows: Sequence[FundamentalFactObservation],
    period_end: date,
    symbol: str,
) -> FundamentalFactObservation:
    candidates = tuple(
        row
        for row in rows
        if row.concept == ASSETS_CONCEPT
        and row.period_start is None
        and row.period_end == period_end
    )
    fact = _require_one_equivalent_fact(candidates, f"{symbol}: current assets")
    if fact.fact_value < 0:
        raise ValueError(f"{symbol}: current assets must be nonnegative.")
    return fact


def _select_current_duration_fact(
    rows: Sequence[FundamentalFactObservation],
    concept: str,
    period_end: date,
    symbol: str,
    *,
    require_annual: bool,
) -> FundamentalFactObservation:
    candidates = tuple(
        row
        for row in rows
        if row.concept == concept
        and row.period_start is not None
        and row.period_end == period_end
        and (not require_annual or _is_annual_duration(row))
    )
    return _require_one_equivalent_fact(
        candidates, f"{symbol}: current {concept}"
    )


def _select_longest_current_duration(
    rows: Sequence[FundamentalFactObservation],
    concept: str,
    period_end: date,
    symbol: str,
) -> FundamentalFactObservation:
    candidates = tuple(
        row
        for row in rows
        if row.concept == concept
        and row.period_start is not None
        and row.period_end == period_end
    )
    if not candidates:
        raise ValueError(f"{symbol}: selected 10-Q is missing current {concept}.")

    longest = max(_duration_days(row) for row in candidates)
    return _require_one_equivalent_fact(
        tuple(row for row in candidates if _duration_days(row) == longest),
        f"{symbol}: longest current {concept}",
    )


def _select_prior_comparable_ytd(
    rows: Sequence[FundamentalFactObservation],
    concept: str,
    current: FundamentalFactObservation,
    symbol: str,
) -> FundamentalFactObservation:
    current_days = _duration_days(current)
    candidates = tuple(
        row
        for row in rows
        if row.concept == concept
        and row.period_start is not None
        and row.period_end < current.period_end
        and COMPARABLE_MIN_GAP_DAYS
        <= (current.period_end - row.period_end).days
        <= COMPARABLE_MAX_GAP_DAYS
        and abs(_duration_days(row) - current_days)
        <= YTD_DURATION_TOLERANCE_DAYS
    )
    return _require_one_equivalent_fact(
        candidates, f"{symbol}: prior-year comparable YTD {concept}"
    )


def _build_annual_pairs(
    rows: Sequence[FundamentalFactObservation],
    symbol: str,
) -> tuple[_AnnualPair, ...]:
    selected: dict[
        str, dict[tuple[date, date], FundamentalFactObservation]
    ] = {}

    for concept in (REVENUE_CONCEPT, NET_INCOME_CONCEPT):
        groups: dict[
            tuple[date, date], list[FundamentalFactObservation]
        ] = {}

        for row in rows:
            if (
                row.concept == concept
                and row.filing_form == "10-K"
                and row.period_start is not None
                and _is_annual_duration(row)
            ):
                key = (row.period_start, row.period_end)
                groups.setdefault(key, []).append(row)

        concept_periods: dict[
            tuple[date, date], FundamentalFactObservation
        ] = {}
        for key, candidates in groups.items():
            latest_date = max(row.filing_date for row in candidates)
            latest = tuple(
                row for row in candidates if row.filing_date == latest_date
            )
            if len({row.fact_value for row in latest}) != 1:
                raise ValueError(
                    f"{symbol}: conflicting latest-version annual {concept} "
                    f"facts for period {key[0]} to {key[1]}."
                )
            concept_periods[key] = min(
                latest, key=lambda row: row.accession_number
            )

        selected[concept] = concept_periods

    revenue_periods = selected[REVENUE_CONCEPT]
    income_periods = selected[NET_INCOME_CONCEPT]
    common = sorted(
        set(revenue_periods).intersection(income_periods),
        key=lambda key: (key[1], key[0]),
        reverse=True,
    )

    pairs = tuple(
        _AnnualPair(
            period_start=start,
            period_end=end,
            revenue=revenue_periods[(start, end)].fact_value,
            net_income=income_periods[(start, end)].fact_value,
        )
        for start, end in common
    )
    if not pairs:
        raise ValueError(
            f"{symbol}: no matched full-year revenue/net-income periods exist."
        )
    return pairs


def _annual_pair_ending(
    pairs: Sequence[_AnnualPair],
    period_end: date,
    symbol: str,
) -> _AnnualPair:
    candidates = tuple(pair for pair in pairs if pair.period_end == period_end)
    if len(candidates) != 1:
        raise ValueError(
            f"{symbol}: expected exactly one matched full-year revenue/"
            f"net-income period ending {period_end}."
        )
    return candidates[0]


def _prior_annual_pair(
    pairs: Sequence[_AnnualPair],
    latest: _AnnualPair,
    symbol: str,
) -> _AnnualPair:
    older = sorted(
        (pair for pair in pairs if pair.period_end < latest.period_end),
        key=lambda pair: pair.period_end,
        reverse=True,
    )
    if not older:
        raise ValueError(
            f"{symbol}: two comparable full-year periods are required."
        )

    prior = older[0]
    gap = (latest.period_end - prior.period_end).days
    if not COMPARABLE_MIN_GAP_DAYS <= gap <= COMPARABLE_MAX_GAP_DAYS:
        raise ValueError(
            f"{symbol}: immediately preceding full-year period is not "
            "year-over-year comparable."
        )
    return prior


def _require_same_period(
    left: FundamentalFactObservation,
    right: FundamentalFactObservation,
    context: str,
) -> None:
    if (
        left.period_start != right.period_start
        or left.period_end != right.period_end
    ):
        raise ValueError(f"{context} must be identical.")


def _require_one_equivalent_fact(
    candidates: Sequence[FundamentalFactObservation],
    context: str,
) -> FundamentalFactObservation:
    if not candidates:
        raise ValueError(f"{context} is unavailable.")

    identities = {
        (row.period_start, row.period_end, row.fact_value)
        for row in candidates
    }
    if len(identities) != 1:
        raise ValueError(f"{context} is ambiguous.")

    return min(
        candidates,
        key=lambda row: (row.filing_date, row.accession_number),
    )


def _duration_days(observation: FundamentalFactObservation) -> int:
    if observation.period_start is None:
        raise ValueError("duration fact requires period_start.")
    return (observation.period_end - observation.period_start).days + 1


def _is_annual_duration(observation: FundamentalFactObservation) -> bool:
    return ANNUAL_MIN_DAYS <= _duration_days(observation) <= ANNUAL_MAX_DAYS


def _validate_observation(
    observation: FundamentalFactObservation,
) -> FundamentalFactObservation:
    if observation.source_system != EXPECTED_SOURCE_SYSTEM:
        raise ValueError("Gold fundamental metrics require source_system=sec.")
    if observation.taxonomy != EXPECTED_TAXONOMY:
        raise ValueError("Gold fundamental metrics require taxonomy=us-gaap.")
    if observation.unit != EXPECTED_UNIT:
        raise ValueError("Gold fundamental metrics require unit=USD.")

    symbol = _required_string(observation.project_symbol, "project_symbol")
    cik = _required_string(observation.cik, "cik")
    if not CIK_PATTERN.fullmatch(cik):
        raise ValueError("cik must contain exactly 10 ASCII digits.")

    concept = _required_string(observation.concept, "concept")
    if concept not in EXPECTED_CONCEPTS:
        raise ValueError(f"unsupported Gold fundamental concept: {concept!r}.")

    accession = _required_string(
        observation.accession_number, "accession_number"
    )
    if not ACCESSION_PATTERN.fullmatch(accession):
        raise ValueError(
            "accession_number must match the SEC accession format."
        )

    filing_form = _required_string(observation.filing_form, "filing_form")
    period_start = (
        None
        if observation.period_start is None
        else _require_date(observation.period_start, "period_start")
    )
    period_end = _require_date(observation.period_end, "period_end")
    filing_date = _require_date(observation.filing_date, "filing_date")

    if period_start is not None and period_start > period_end:
        raise ValueError("period_start must not be after period_end.")
    if concept == ASSETS_CONCEPT and period_start is not None:
        raise ValueError("Assets must be an instant fact without period_start.")
    if concept != ASSETS_CONCEPT and period_start is None:
        raise ValueError(f"{concept} must be a duration fact with period_start.")

    if (
        not isinstance(observation.fact_value, Decimal)
        or not observation.fact_value.is_finite()
    ):
        raise ValueError("fact_value must be a finite Decimal.")

    source_response_id = _required_string(
        observation.source_response_id, "source_response_id"
    )
    ingestion_run_id = _required_string(
        observation.ingestion_run_id, "ingestion_run_id"
    )
    fetched_at = _require_aware_datetime(observation.fetched_at, "fetched_at")

    return FundamentalFactObservation(
        source_system=EXPECTED_SOURCE_SYSTEM,
        cik=cik,
        project_symbol=symbol,
        taxonomy=EXPECTED_TAXONOMY,
        concept=concept,
        unit=EXPECTED_UNIT,
        accession_number=accession,
        fact_value=observation.fact_value,
        period_start=period_start,
        period_end=period_end,
        filing_form=filing_form,
        filing_date=filing_date,
        source_response_id=source_response_id,
        fetched_at=fetched_at.astimezone(timezone.utc),
        ingestion_run_id=ingestion_run_id,
    )


def _normalize_configured_companies(
    values: Mapping[str, str],
) -> dict[str, str]:
    if not isinstance(values, Mapping):
        raise ValueError(
            "configured_companies must be a mapping of symbol to CIK."
        )

    normalized: dict[str, str] = {}
    for symbol_value, cik_value in values.items():
        symbol = _required_string(symbol_value, "configured symbol")
        cik = _required_string(cik_value, "configured CIK")
        if not CIK_PATTERN.fullmatch(cik):
            raise ValueError(
                "configured CIK must contain exactly 10 ASCII digits."
            )
        normalized[symbol] = cik

    if not normalized:
        raise ValueError("configured_companies must not be empty.")
    if len(set(normalized.values())) != len(normalized):
        raise ValueError("configured company CIKs must be unique.")
    return normalized


def _validate_metric(metric: GoldFundamentalMetric) -> None:
    money_values = (
        metric.revenue_ttm,
        metric.net_income_ttm,
        metric.assets_latest,
        metric.net_income_change_latest_fy,
    )
    if any(not value.is_finite() for value in money_values):
        raise ValueError("Gold fundamental monetary metrics must be finite.")
    if metric.revenue_ttm <= 0:
        raise ValueError("Gold TTM revenue must be positive.")
    if metric.assets_latest < 0:
        raise ValueError("Gold latest assets must be nonnegative.")

    rate_values = (
        metric.net_margin_ttm,
        metric.revenue_growth_latest_fy,
    )
    if any(not value.is_finite() for value in rate_values):
        raise ValueError("Gold fundamental rate metrics must be finite.")
    if metric.ttm_derivation_method not in {
        "annual",
        "annual_plus_ytd_minus_prior_ytd",
    }:
        raise ValueError("unsupported TTM derivation method.")


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must be nonblank.")
    return normalized


def _require_date(value: object, field: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(f"{field} must be a date.")
    return value


def _require_aware_datetime(value: object, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field} must be a timezone-aware datetime.")
    return value


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def _quantize_rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_QUANTUM, rounding=ROUND_HALF_EVEN)
