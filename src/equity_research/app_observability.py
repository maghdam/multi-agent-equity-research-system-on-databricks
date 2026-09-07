"""Privacy-safe application telemetry for the Databricks research workspace."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from logging import Logger
from typing import Any


APP_EVENT_SCHEMA_VERSION = 1

_ALLOWED_EVENT_TYPES = {
    "research_completed",
    "research_failed",
    "followup_completed",
    "followup_failed",
    "feedback_submitted",
}

_ALLOWED_FEEDBACK = {
    "helpful",
    "needs_work",
}


@dataclass(frozen=True)
class AppEvent:
    """One bounded application event safe for Databricks App logs."""

    event_type: str
    mode: str | None = None
    symbols: tuple[str, ...] = ()
    market_window_sessions: int | None = None
    report_status: str | None = None
    synthesis_mode: str | None = None
    evidence_count: int | None = None
    duration_ms: int | None = None
    error_type: str | None = None
    question_length: int | None = None
    turn_count: int | None = None
    source_count: int | None = None
    limitation_present: bool | None = None
    feedback: str | None = None

    def __post_init__(self) -> None:
        if self.event_type not in _ALLOWED_EVENT_TYPES:
            raise ValueError(
                "event_type is not supported."
            )

        if self.mode is not None and self.mode not in {
            "single_company",
            "comparison",
        }:
            raise ValueError(
                "mode must be single_company, comparison, or None."
            )

        normalized_symbols = tuple(
            _normalized_symbol(symbol)
            for symbol in self.symbols
        )
        object.__setattr__(
            self,
            "symbols",
            normalized_symbols,
        )

        if len(normalized_symbols) > 2:
            raise ValueError(
                "symbols must contain at most two values."
            )

        _validate_optional_positive_int(
            self.market_window_sessions,
            "market_window_sessions",
            allow_zero=False,
        )
        _validate_optional_positive_int(
            self.evidence_count,
            "evidence_count",
            allow_zero=True,
        )
        _validate_optional_positive_int(
            self.duration_ms,
            "duration_ms",
            allow_zero=True,
        )
        _validate_optional_positive_int(
            self.question_length,
            "question_length",
            allow_zero=True,
        )
        _validate_optional_positive_int(
            self.turn_count,
            "turn_count",
            allow_zero=True,
        )
        _validate_optional_positive_int(
            self.source_count,
            "source_count",
            allow_zero=True,
        )

        for name in (
            "report_status",
            "synthesis_mode",
            "error_type",
        ):
            value = getattr(
                self,
                name,
            )

            if value is not None:
                _bounded_label(
                    value,
                    name,
                )

        if (
            self.limitation_present is not None
            and not isinstance(
                self.limitation_present,
                bool,
            )
        ):
            raise TypeError(
                "limitation_present must be bool or None."
            )

        if (
            self.feedback is not None
            and self.feedback not in _ALLOWED_FEEDBACK
        ):
            raise ValueError(
                "feedback must be helpful, needs_work, or None."
            )

        if (
            self.event_type == "feedback_submitted"
            and self.feedback is None
        ):
            raise ValueError(
                "feedback_submitted requires feedback."
            )

    def to_dict(self) -> dict[str, Any]:
        """Return only explicitly approved scalar telemetry fields."""

        values: dict[str, Any] = {
            "schema_version": APP_EVENT_SCHEMA_VERSION,
            "event_type": self.event_type,
        }

        optional = {
            "mode": self.mode,
            "symbols": (
                list(self.symbols)
                if self.symbols
                else None
            ),
            "market_window_sessions": self.market_window_sessions,
            "report_status": self.report_status,
            "synthesis_mode": self.synthesis_mode,
            "evidence_count": self.evidence_count,
            "duration_ms": self.duration_ms,
            "error_type": self.error_type,
            "question_length": self.question_length,
            "turn_count": self.turn_count,
            "source_count": self.source_count,
            "limitation_present": self.limitation_present,
            "feedback": self.feedback,
        }

        for key, value in optional.items():
            if value is not None:
                values[key] = value

        return values


def log_app_event(
    logger: Logger,
    event: AppEvent,
) -> None:
    """Emit one deterministic JSON line without arbitrary user/source text."""

    if not isinstance(
        event,
        AppEvent,
    ):
        raise TypeError(
            "event must be AppEvent."
        )

    if not isinstance(
        logger,
        Logger,
    ):
        raise TypeError(
            "logger must be logging.Logger."
        )

    logger.info(
        "APP_EVENT %s",
        json.dumps(
            event.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def research_event(
    *,
    event_type: str,
    mode: str,
    symbols: Sequence[str],
    market_window_sessions: int,
    duration_ms: int,
    report_status: str | None = None,
    synthesis_mode: str | None = None,
    evidence_count: int | None = None,
    error_type: str | None = None,
) -> AppEvent:
    """Build one bounded research lifecycle event."""

    return AppEvent(
        event_type=event_type,
        mode=mode,
        symbols=tuple(symbols),
        market_window_sessions=market_window_sessions,
        report_status=report_status,
        synthesis_mode=synthesis_mode,
        evidence_count=evidence_count,
        duration_ms=duration_ms,
        error_type=error_type,
    )


def followup_event(
    *,
    event_type: str,
    research: Mapping[str, Any] | None,
    duration_ms: int,
    question_length: int,
    turn_count: int | None = None,
    source_count: int | None = None,
    limitation_present: bool | None = None,
    error_type: str | None = None,
) -> AppEvent:
    """Build one bounded follow-up lifecycle event from verified metadata."""

    mode = None
    symbols: tuple[str, ...] = ()
    window = None

    if isinstance(
        research,
        Mapping,
    ):
        raw_mode = research.get(
            "mode"
        )
        raw_symbols = research.get(
            "symbols"
        )
        raw_window = research.get(
            "market_window_sessions"
        )

        if isinstance(
            raw_mode,
            str,
        ):
            mode = raw_mode

        if isinstance(
            raw_symbols,
            list,
        ):
            symbols = tuple(
                str(symbol)
                for symbol in raw_symbols
            )

        if (
            isinstance(raw_window, int)
            and not isinstance(raw_window, bool)
        ):
            window = raw_window

    return AppEvent(
        event_type=event_type,
        mode=mode,
        symbols=symbols,
        market_window_sessions=window,
        duration_ms=duration_ms,
        error_type=error_type,
        question_length=question_length,
        turn_count=turn_count,
        source_count=source_count,
        limitation_present=limitation_present,
    )


def feedback_event(
    *,
    research: Mapping[str, Any],
    feedback: str,
) -> AppEvent:
    """Build session-level feedback without collecting user free text."""

    if not isinstance(
        research,
        Mapping,
    ):
        raise TypeError(
            "research must be a mapping."
        )

    symbols = research.get(
        "symbols"
    )

    if not isinstance(
        symbols,
        list,
    ):
        raise ValueError(
            "research.symbols must be a list."
        )

    return AppEvent(
        event_type="feedback_submitted",
        mode=str(
            research.get("mode")
        ),
        symbols=tuple(
            str(symbol)
            for symbol in symbols
        ),
        market_window_sessions=research.get(
            "market_window_sessions"
        ),
        report_status=_optional_string(
            research.get("report_status")
        ),
        synthesis_mode=_optional_string(
            research.get("synthesis_mode")
        ),
        feedback=feedback,
    )


def _normalized_symbol(
    value: object,
) -> str:
    if not isinstance(
        value,
        str,
    ) or not value.strip():
        raise ValueError(
            "symbols must contain nonblank strings."
        )

    normalized = value.strip().upper()

    if len(normalized) > 16:
        raise ValueError(
            "symbol exceeds the maximum length."
        )

    return normalized


def _bounded_label(
    value: object,
    name: str,
) -> str:
    if not isinstance(
        value,
        str,
    ) or not value.strip():
        raise ValueError(
            f"{name} must be a nonblank string."
        )

    normalized = value.strip()

    if len(normalized) > 100:
        raise ValueError(
            f"{name} exceeds the maximum length."
        )

    return normalized


def _optional_string(
    value: object,
) -> str | None:
    return (
        value
        if isinstance(value, str) and value.strip()
        else None
    )


def _validate_optional_positive_int(
    value: object,
    name: str,
    *,
    allow_zero: bool,
) -> None:
    if value is None:
        return

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < (0 if allow_zero else 1)
    ):
        qualifier = "nonnegative" if allow_zero else "positive"
        raise ValueError(
            f"{name} must be a {qualifier} integer or None."
        )
