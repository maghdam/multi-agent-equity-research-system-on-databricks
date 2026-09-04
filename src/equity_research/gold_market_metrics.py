"""Pure-Python Gold market-metric calculation and validation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, localcontext


EXPECTED_SOURCE_SYSTEM = "alpaca"
EXPECTED_FEED = "sip"
EXPECTED_ADJUSTMENT = "split"
EXPECTED_TIMEFRAME = "1Day"
EXPECTED_CURRENCY = "USD"

MIN_REQUIRED_CLOSES = 61
ANNUALIZATION_SESSIONS = Decimal("252")

RATE_QUANTUM = Decimal("0.0000000001")
SMA_QUANTUM = Decimal("0.0000000001")


@dataclass(frozen=True)
class MarketPriceObservation:
    """One validated Silver daily-price row required by Gold."""

    symbol: str
    bar_timestamp: datetime
    trading_date: date
    close: Decimal
    source_system: str
    feed: str
    adjustment: str
    timeframe: str
    currency: str
    source_response_id: str
    fetched_at: datetime
    ingestion_run_id: str


@dataclass(frozen=True)
class GoldMarketMetric:
    """One current Gold market-metrics row."""

    source_system: str
    symbol: str
    as_of_date: date
    as_of_bar_timestamp: datetime
    close: Decimal
    window_start_date_60d: date
    observations_available: int
    return_1d: Decimal
    return_5d: Decimal
    return_20d: Decimal
    return_60d: Decimal
    annualized_volatility_20d: Decimal
    annualized_volatility_60d: Decimal
    current_drawdown_60d: Decimal
    max_drawdown_60d: Decimal
    sma_20: Decimal
    sma_60: Decimal
    close_vs_sma_20: Decimal
    close_vs_sma_60: Decimal
    sma_20_vs_sma_60: Decimal
    feed: str
    adjustment: str
    timeframe: str
    currency: str
    latest_source_response_id: str
    latest_source_fetched_at: datetime
    latest_source_ingestion_run_id: str


def build_market_metrics_snapshot(
    *,
    observations: Sequence[MarketPriceObservation],
    configured_symbols: Sequence[str],
) -> tuple[GoldMarketMetric, ...]:
    """Build one deterministic current Gold row per configured symbol."""

    symbols = _normalize_symbols(configured_symbols)

    if isinstance(observations, (str, bytes)):
        raise ValueError(
            "observations must be a sequence of MarketPriceObservation values."
        )

    grouped: dict[str, list[MarketPriceObservation]] = {
        symbol: [] for symbol in symbols
    }

    seen_keys: set[tuple[str, date]] = set()

    for observation in observations:
        if not isinstance(observation, MarketPriceObservation):
            raise ValueError(
                "observations must contain MarketPriceObservation values."
            )

        validated = _validate_observation(observation)

        if validated.symbol not in grouped:
            raise ValueError(
                f"unexpected Silver symbol for Gold metrics: "
                f"{validated.symbol!r}."
            )

        key = (
            validated.symbol,
            validated.trading_date,
        )

        if key in seen_keys:
            raise ValueError(
                "duplicate Silver trading date for configured symbol: "
                f"{validated.symbol} {validated.trading_date}."
            )

        seen_keys.add(key)
        grouped[validated.symbol].append(validated)

    for symbol in symbols:
        if not grouped[symbol]:
            raise ValueError(
                f"configured symbol {symbol} has no Silver price history."
            )

        grouped[symbol].sort(
            key=lambda observation: (
                observation.trading_date,
                observation.bar_timestamp,
            )
        )

    latest_dates = {
        symbol: rows[-1].trading_date
        for symbol, rows in grouped.items()
    }

    if len(set(latest_dates.values())) != 1:
        detail = ", ".join(
            f"{symbol}={latest_dates[symbol]}"
            for symbol in symbols
        )
        raise ValueError(
            "configured symbols do not share one latest trading date: "
            f"{detail}."
        )

    as_of_date = next(iter(latest_dates.values()))

    aligned_dates: tuple[date, ...] | None = None

    for symbol in symbols:
        rows = grouped[symbol]

        if len(rows) < MIN_REQUIRED_CLOSES:
            raise ValueError(
                f"configured symbol {symbol} has only {len(rows)} closes; "
                f"{MIN_REQUIRED_CLOSES} are required."
            )

        final_dates = tuple(
            row.trading_date
            for row in rows[-MIN_REQUIRED_CLOSES:]
        )

        if aligned_dates is None:
            aligned_dates = final_dates
        elif final_dates != aligned_dates:
            raise ValueError(
                "configured symbols do not share identical final "
                "61-session trading-date coverage."
            )

    assert aligned_dates is not None

    metrics = tuple(
        _calculate_symbol_metrics(
            rows=grouped[symbol],
            as_of_date=as_of_date,
        )
        for symbol in sorted(symbols)
    )

    if len(metrics) != len(symbols):
        raise ValueError(
            "Gold market-metrics snapshot is incomplete."
        )

    business_keys = {
        (metric.symbol, metric.as_of_date)
        for metric in metrics
    }

    if len(business_keys) != len(metrics):
        raise ValueError(
            "Gold market-metrics business keys are not unique."
        )

    return metrics


def _calculate_symbol_metrics(
    *,
    rows: Sequence[MarketPriceObservation],
    as_of_date: date,
) -> GoldMarketMetric:
    """Calculate one symbol's metrics from its aligned Silver history."""

    window = tuple(rows[-MIN_REQUIRED_CLOSES:])
    closes = tuple(row.close for row in window)
    latest = window[-1]

    if latest.trading_date != as_of_date:
        raise ValueError(
            f"{latest.symbol} does not end on the common as_of_date."
        )

    with localcontext() as context:
        context.prec = 50

        return_1d = _period_return(closes, 1)
        return_5d = _period_return(closes, 5)
        return_20d = _period_return(closes, 20)
        return_60d = _period_return(closes, 60)

        one_session_returns = tuple(
            closes[index] / closes[index - 1] - Decimal("1")
            for index in range(1, len(closes))
        )

        volatility_20d = (
            _sample_standard_deviation(
                one_session_returns[-20:]
            )
            * ANNUALIZATION_SESSIONS.sqrt()
        )

        volatility_60d = (
            _sample_standard_deviation(
                one_session_returns[-60:]
            )
            * ANNUALIZATION_SESSIONS.sqrt()
        )

        peak_close = max(closes)

        current_drawdown = (
            closes[-1] / peak_close
            - Decimal("1")
        )

        running_peak = closes[0]
        max_drawdown = Decimal("0")

        for close in closes:
            if close > running_peak:
                running_peak = close

            drawdown = (
                close / running_peak
                - Decimal("1")
            )

            if drawdown < max_drawdown:
                max_drawdown = drawdown

        sma_20 = (
            sum(closes[-20:], Decimal("0"))
            / Decimal("20")
        )

        sma_60 = (
            sum(closes[-60:], Decimal("0"))
            / Decimal("60")
        )

        close_vs_sma_20 = (
            closes[-1] / sma_20
            - Decimal("1")
        )

        close_vs_sma_60 = (
            closes[-1] / sma_60
            - Decimal("1")
        )

        sma_20_vs_sma_60 = (
            sma_20 / sma_60
            - Decimal("1")
        )

    metric = GoldMarketMetric(
        source_system=EXPECTED_SOURCE_SYSTEM,
        symbol=latest.symbol,
        as_of_date=as_of_date,
        as_of_bar_timestamp=latest.bar_timestamp,
        close=latest.close,
        window_start_date_60d=window[0].trading_date,
        observations_available=len(rows),
        return_1d=_quantize_rate(return_1d),
        return_5d=_quantize_rate(return_5d),
        return_20d=_quantize_rate(return_20d),
        return_60d=_quantize_rate(return_60d),
        annualized_volatility_20d=_quantize_rate(
            volatility_20d
        ),
        annualized_volatility_60d=_quantize_rate(
            volatility_60d
        ),
        current_drawdown_60d=_quantize_rate(
            current_drawdown
        ),
        max_drawdown_60d=_quantize_rate(
            max_drawdown
        ),
        sma_20=_quantize_sma(sma_20),
        sma_60=_quantize_sma(sma_60),
        close_vs_sma_20=_quantize_rate(
            close_vs_sma_20
        ),
        close_vs_sma_60=_quantize_rate(
            close_vs_sma_60
        ),
        sma_20_vs_sma_60=_quantize_rate(
            sma_20_vs_sma_60
        ),
        feed=EXPECTED_FEED,
        adjustment=EXPECTED_ADJUSTMENT,
        timeframe=EXPECTED_TIMEFRAME,
        currency=EXPECTED_CURRENCY,
        latest_source_response_id=(
            latest.source_response_id
        ),
        latest_source_fetched_at=latest.fetched_at,
        latest_source_ingestion_run_id=(
            latest.ingestion_run_id
        ),
    )

    _validate_metric(metric)

    return metric


def _period_return(
    closes: Sequence[Decimal],
    sessions: int,
) -> Decimal:
    """Return close-to-close price return over N observed sessions."""

    return (
        closes[-1]
        / closes[-1 - sessions]
        - Decimal("1")
    )


def _sample_standard_deviation(
    values: Sequence[Decimal],
) -> Decimal:
    """Calculate Decimal sample standard deviation deterministically."""

    if len(values) < 2:
        raise ValueError(
            "sample standard deviation requires at least two values."
        )

    count = Decimal(len(values))
    mean = sum(values, Decimal("0")) / count

    variance = (
        sum(
            (
                (value - mean)
                * (value - mean)
            )
            for value in values
        )
        / Decimal(len(values) - 1)
    )

    return variance.sqrt()


def _validate_observation(
    observation: MarketPriceObservation,
) -> MarketPriceObservation:
    """Validate one Silver observation at the Gold boundary."""

    symbol = _required_string(
        observation.symbol,
        "symbol",
    )

    if observation.source_system != EXPECTED_SOURCE_SYSTEM:
        raise ValueError(
            "Gold market metrics require source_system=alpaca."
        )

    if observation.feed != EXPECTED_FEED:
        raise ValueError(
            "Gold market metrics require feed=sip."
        )

    if observation.adjustment != EXPECTED_ADJUSTMENT:
        raise ValueError(
            "Gold market metrics require adjustment=split."
        )

    if observation.timeframe != EXPECTED_TIMEFRAME:
        raise ValueError(
            "Gold market metrics require timeframe=1Day."
        )

    if observation.currency != EXPECTED_CURRENCY:
        raise ValueError(
            "Gold market metrics require currency=USD."
        )

    if not isinstance(observation.trading_date, date):
        raise ValueError(
            "trading_date must be a date."
        )

    bar_timestamp = _require_aware_datetime(
        observation.bar_timestamp,
        "bar_timestamp",
    )

    fetched_at = _require_aware_datetime(
        observation.fetched_at,
        "fetched_at",
    )

    if (
        not isinstance(observation.close, Decimal)
        or isinstance(observation.close, bool)
        or not observation.close.is_finite()
        or observation.close <= 0
    ):
        raise ValueError(
            "close must be a positive finite Decimal."
        )

    source_response_id = _required_string(
        observation.source_response_id,
        "source_response_id",
    )

    ingestion_run_id = _required_string(
        observation.ingestion_run_id,
        "ingestion_run_id",
    )

    return MarketPriceObservation(
        symbol=symbol,
        bar_timestamp=bar_timestamp.astimezone(
            timezone.utc
        ),
        trading_date=observation.trading_date,
        close=observation.close,
        source_system=EXPECTED_SOURCE_SYSTEM,
        feed=EXPECTED_FEED,
        adjustment=EXPECTED_ADJUSTMENT,
        timeframe=EXPECTED_TIMEFRAME,
        currency=EXPECTED_CURRENCY,
        source_response_id=source_response_id,
        fetched_at=fetched_at.astimezone(
            timezone.utc
        ),
        ingestion_run_id=ingestion_run_id,
    )


def _validate_metric(
    metric: GoldMarketMetric,
) -> None:
    """Apply final Gold metric-range checks."""

    rate_values = (
        metric.return_1d,
        metric.return_5d,
        metric.return_20d,
        metric.return_60d,
        metric.close_vs_sma_20,
        metric.close_vs_sma_60,
        metric.sma_20_vs_sma_60,
    )

    if any(not value.is_finite() for value in rate_values):
        raise ValueError(
            "Gold return/trend metrics must be finite."
        )

    volatility_values = (
        metric.annualized_volatility_20d,
        metric.annualized_volatility_60d,
    )

    if any(
        not value.is_finite()
        or value < 0
        for value in volatility_values
    ):
        raise ValueError(
            "Gold volatility metrics must be finite and nonnegative."
        )

    drawdown_values = (
        metric.current_drawdown_60d,
        metric.max_drawdown_60d,
    )

    if any(
        not value.is_finite()
        or value < Decimal("-1")
        or value > Decimal("0")
        for value in drawdown_values
    ):
        raise ValueError(
            "Gold drawdown metrics must lie in [-1, 0]."
        )

    if (
        metric.sma_20 <= 0
        or metric.sma_60 <= 0
    ):
        raise ValueError(
            "Gold moving averages must be positive."
        )


def _normalize_symbols(
    values: Sequence[str],
) -> tuple[str, ...]:
    """Validate configured symbols without stock-specific logic."""

    if isinstance(values, (str, bytes)):
        raise ValueError(
            "configured_symbols must be a sequence of strings."
        )

    normalized = tuple(
        _required_string(value, "configured symbol")
        for value in values
    )

    if not normalized:
        raise ValueError(
            "configured_symbols must not be empty."
        )

    if len(set(normalized)) != len(normalized):
        raise ValueError(
            "configured_symbols must be unique."
        )

    return normalized


def _required_string(
    value: object,
    field: str,
) -> str:
    """Return one required nonblank string."""

    if not isinstance(value, str):
        raise ValueError(
            f"{field} must be a string."
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field} must be nonblank."
        )

    return normalized


def _require_aware_datetime(
    value: object,
    field: str,
) -> datetime:
    """Require a timezone-aware datetime."""

    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{field} must be a timezone-aware datetime."
        )

    return value


def _quantize_rate(
    value: Decimal,
) -> Decimal:
    """Publish one rate at scale 10 using round-half-even."""

    return value.quantize(
        RATE_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )


def _quantize_sma(
    value: Decimal,
) -> Decimal:
    """Publish one moving average at scale 10 using round-half-even."""

    return value.quantize(
        SMA_QUANTUM,
        rounding=ROUND_HALF_EVEN,
    )
