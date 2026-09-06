"""Deterministic helpers for numerical-fidelity validation in model prose."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal


NumericClaimKind = Literal[
    "date",
    "year",
    "percent",
    "scaled",
    "number",
]

_SCALE_FACTORS = {
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "trillion": Decimal("1000000000000"),
}

_DATE_PATTERN = re.compile(
    r"(?<!\d)(?P<date>\d{4}-\d{2}-\d{2})(?!\d)"
)

_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<currency>[$€£])?"
    r"\s*"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*"
    r"(?P<scale>thousand|million|billion|trillion)?"
    r"\s*"
    r"(?P<percent>%|percent\b)?",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class NumericClaim:
    """One numerical surface claim extracted from prose."""

    kind: NumericClaimKind
    raw: str
    value: Decimal | str
    precision: int | None
    scale: str | None = None


def extract_numeric_claims(
    text: str,
) -> tuple[NumericClaim, ...]:
    """Extract finance-relevant numerical claims from prose.

    Plain small integers are intentionally ignored because window labels such as
    20-day and 60-day are structural descriptors rather than metric values.
    Decimal numbers, percentages, scaled values, ISO dates, and four-digit years are
    retained.
    """

    if not isinstance(text, str):
        raise TypeError(
            "text must be a string."
        )

    normalized = _normalize_text(
        text
    )
    claims: list[NumericClaim] = []

    masked = list(
        normalized
    )

    for match in _DATE_PATTERN.finditer(
        normalized
    ):
        date_text = match.group(
            "date"
        )
        try:
            parsed = date.fromisoformat(
                date_text
            )
        except ValueError:
            continue

        claims.append(
            NumericClaim(
                kind="date",
                raw=match.group(0),
                value=parsed.isoformat(),
                precision=None,
            )
        )

        for index in range(
            match.start(),
            match.end(),
        ):
            masked[index] = " "

    remaining = "".join(
        masked
    )

    for match in _NUMBER_PATTERN.finditer(
        remaining
    ):
        raw_number = match.group(
            "number"
        )
        scale = match.group(
            "scale"
        )
        percent = match.group(
            "percent"
        )
        currency = match.group(
            "currency"
        )

        try:
            value = Decimal(
                raw_number.replace(
                    ",",
                    "",
                )
            )
        except InvalidOperation:
            continue

        precision = _decimal_precision(
            raw_number
        )

        if percent is not None:
            kind: NumericClaimKind = "percent"
            normalized_scale = None
        elif scale is not None:
            kind = "scaled"
            normalized_scale = scale.lower()
        elif (
            "." in raw_number
            or currency is not None
        ):
            kind = "number"
            normalized_scale = None
        elif (
            value == value.to_integral_value()
            and Decimal("1900")
            <= value
            <= Decimal("2100")
        ):
            kind = "year"
            normalized_scale = None
        else:
            continue

        claims.append(
            NumericClaim(
                kind=kind,
                raw=match.group(0).strip(),
                value=value,
                precision=precision,
                scale=normalized_scale,
            )
        )

    return tuple(
        claims
    )


def unsupported_numeric_claims_from_sources(
    *,
    candidate_text: str,
    source_texts: tuple[str, ...],
) -> tuple[NumericClaim, ...]:
    """Return final-prose claims not already present in cited source statements."""

    candidate = extract_numeric_claims(
        candidate_text
    )
    sources = tuple(
        claim
        for source_text in source_texts
        for claim in extract_numeric_claims(
            source_text
        )
    )

    return tuple(
        claim
        for claim in candidate
        if not any(
            _claims_exactly_equivalent(
                claim,
                source,
            )
            for source in sources
        )
    )


def numeric_claim_matches_expected(
    claim: NumericClaim,
    *,
    expected_percent_values: tuple[Decimal, ...] = (),
    expected_scaled_money_values: tuple[Decimal, ...] = (),
    expected_number_values: tuple[Decimal, ...] = (),
    expected_dates: tuple[date, ...] = (),
) -> bool:
    """Return whether one worker-prose claim is supported by controlled values."""

    if claim.kind == "date":
        return claim.value in {
            value.isoformat()
            for value in expected_dates
        }

    if claim.kind == "year":
        return claim.value in {
            Decimal(value.year)
            for value in expected_dates
        }

    if not isinstance(
        claim.value,
        Decimal,
    ):
        return False

    if claim.kind == "percent":
        return any(
            _matches_rounded_value(
                claim,
                expected * Decimal("100"),
            )
            for expected in expected_percent_values
        )

    if claim.kind == "scaled":
        if claim.scale is None:
            return False

        factor = _SCALE_FACTORS[
            claim.scale
        ]
        return any(
            _matches_rounded_value(
                claim,
                expected / factor,
            )
            for expected in expected_scaled_money_values
        )

    if claim.kind == "number":
        return any(
            _matches_rounded_value(
                claim,
                expected,
            )
            for expected in expected_number_values
        )

    return False


def _claims_exactly_equivalent(
    left: NumericClaim,
    right: NumericClaim,
) -> bool:
    if left.kind != right.kind:
        return False

    if left.scale != right.scale:
        return False

    return left.value == right.value


def _matches_rounded_value(
    claim: NumericClaim,
    expected: Decimal,
) -> bool:
    assert isinstance(
        claim.value,
        Decimal,
    )
    assert claim.precision is not None

    half_unit = (
        Decimal("0.5")
        * (
            Decimal("10")
            ** Decimal(-claim.precision)
        )
    )

    return abs(
        claim.value
        - expected
    ) <= half_unit


def _decimal_precision(
    raw_number: str,
) -> int:
    value = raw_number.replace(
        ",",
        "",
    )

    if "." not in value:
        return 0

    return len(
        value.rsplit(
            ".",
            1,
        )[1]
    )


def _normalize_text(
    text: str,
) -> str:
    value = unicodedata.normalize(
        "NFKC",
        text,
    )

    return value.translate(
        str.maketrans(
            {
                "−": "-",
                "‐": "-",
                "–": "-",
                "—": "-",
                "‑": "-",
                "\u00a0": " ",
                "\u202f": " ",
            }
        )
    )
