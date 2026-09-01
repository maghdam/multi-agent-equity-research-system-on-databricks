"""Load and validate the supported-equities configuration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "equities.json"
)

REQUIRED_FIELDS = {
    "symbol",
    "display_name",
    "alpaca_symbol",
    "sec_cik",
}

SYMBOL_PATTERN = re.compile(r"[A-Z][A-Z0-9.-]*")
CIK_PATTERN = re.compile(r"[0-9]{10}")


class ConfigurationError(ValueError):
    """Raised when the equities configuration is invalid."""


@dataclass(frozen=True)
class Equity:
    """Validated identifiers for one supported equity."""

    symbol: str
    display_name: str
    alpaca_symbol: str
    sec_cik: str


def _required_text(
    record: dict[str, Any],
    field: str,
    position: int,
) -> str:
    """Return a required string after trimming surrounding whitespace."""

    value = record.get(field)

    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(
            f"Equity {position}: {field} must be a nonblank string."
        )

    return value.strip()


def load_equities(
    path: str | Path | None = None,
) -> dict[str, Equity]:
    """Load validated equities, indexed by project symbol."""

    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(
            f"Equities configuration not found: {config_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Equities configuration is not valid JSON: {exc.msg}"
        ) from exc

    if not isinstance(payload, dict):
        raise ConfigurationError("Configuration root must be an object.")

    records = payload.get("equities")
    if not isinstance(records, list) or not records:
        raise ConfigurationError(
            "Configuration must contain a nonempty equities list."
        )

    equities: dict[str, Equity] = {}

    for position, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ConfigurationError(
                f"Equity {position} must be an object."
            )

        missing = sorted(REQUIRED_FIELDS - record.keys())
        unknown = sorted(record.keys() - REQUIRED_FIELDS)

        # Fail on unknown keys so configuration typos are never ignored.
        if missing:
            raise ConfigurationError(
                f"Equity {position} is missing fields: {missing}"
            )

        if unknown:
            raise ConfigurationError(
                f"Equity {position} has unknown fields: {unknown}"
            )

        symbol = _required_text(record, "symbol", position)
        display_name = _required_text(record, "display_name", position)
        alpaca_symbol = _required_text(
            record, "alpaca_symbol", position
        )
        sec_cik = _required_text(record, "sec_cik", position)

        if not SYMBOL_PATTERN.fullmatch(symbol):
            raise ConfigurationError(
                f"Equity {position}: invalid project symbol {symbol!r}."
            )

        if not SYMBOL_PATTERN.fullmatch(alpaca_symbol):
            raise ConfigurationError(
                f"Equity {position}: invalid Alpaca symbol "
                f"{alpaca_symbol!r}."
            )

        if not CIK_PATTERN.fullmatch(sec_cik):
            raise ConfigurationError(
                f"Equity {position}: SEC CIK must contain "
                "exactly 10 ASCII digits."
            )

        if symbol in equities:
            raise ConfigurationError(
                f"Duplicate project symbol: {symbol}."
            )

        equities[symbol] = Equity(
            symbol=symbol,
            display_name=display_name,
            alpaca_symbol=alpaca_symbol,
            sec_cik=sec_cik,
        )

    return equities
