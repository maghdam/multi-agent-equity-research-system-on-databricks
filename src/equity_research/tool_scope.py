"""Shared request-scope validation for controlled AI tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from equity_research.config import Equity, load_equities


MAX_REQUESTED_SYMBOLS = 2


class ControlledToolRequestError(ValueError):
    """Raised when a controlled-tool request is outside the supported scope."""


def resolve_requested_equities(
    requested_symbols: Sequence[str],
    *,
    equities: Mapping[str, Equity] | None = None,
) -> tuple[Equity, ...]:
    """Resolve one or two requested symbols against shared configuration."""

    if isinstance(requested_symbols, (str, bytes)):
        raise ControlledToolRequestError(
            "requested_symbols must be a sequence of project symbols."
        )

    configured = (
        dict(load_equities())
        if equities is None
        else dict(equities)
    )

    if not configured:
        raise ControlledToolRequestError(
            "No configured equities are available."
        )

    normalized: list[str] = []

    for value in requested_symbols:
        if not isinstance(value, str):
            raise ControlledToolRequestError(
                "Each requested symbol must be a string."
            )

        symbol = value.strip().upper()

        if not symbol:
            raise ControlledToolRequestError(
                "Requested symbols must be nonblank."
            )

        normalized.append(symbol)

    if not normalized:
        raise ControlledToolRequestError(
            "At least one requested symbol is required."
        )

    if len(normalized) > MAX_REQUESTED_SYMBOLS:
        raise ControlledToolRequestError(
            "The MVP supports at most two requested equities per request."
        )

    if len(set(normalized)) != len(normalized):
        raise ControlledToolRequestError(
            "Requested symbols must be unique."
        )

    unsupported = [
        symbol
        for symbol in normalized
        if symbol not in configured
    ]

    if unsupported:
        supported = ", ".join(sorted(configured))
        rejected = ", ".join(unsupported)

        raise ControlledToolRequestError(
            f"Unsupported symbol(s): {rejected}. "
            f"Supported symbols: {supported}."
        )

    return tuple(
        configured[symbol]
        for symbol in normalized
    )
