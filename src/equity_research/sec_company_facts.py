"""Reusable SEC company-facts request and response logic."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass


SEC_DATA_HOST = "data.sec.gov"
SEC_COMPANY_FACTS_PATH_PREFIX = "/api/xbrl/companyfacts"

CIK_PATTERN = re.compile(r"\d{10}")


@dataclass(frozen=True)
class CompanyFactsResponse:
    """Validated top-level metadata from one SEC company-facts response."""

    cik: int
    entity_name: str
    facts: dict[str, object]


def build_company_facts_path(cik: str) -> str:
    """Build the SEC company-facts path for one normalized CIK."""

    normalized_cik = cik.strip()

    if not CIK_PATTERN.fullmatch(normalized_cik):
        raise ValueError(
            "cik must contain exactly 10 digits, including leading zeros."
        )

    return (
        f"{SEC_COMPANY_FACTS_PATH_PREFIX}/"
        f"CIK{normalized_cik}.json"
    )


def parse_company_facts_response(
    payload: object,
) -> CompanyFactsResponse:
    """Validate the top-level SEC company-facts response structure."""

    if not isinstance(payload, Mapping):
        raise ValueError("response payload must be a JSON object.")

    raw_cik = payload.get("cik")
    raw_entity_name = payload.get("entityName")
    raw_facts = payload.get("facts")

    if (
        isinstance(raw_cik, bool)
        or not isinstance(raw_cik, int)
        or raw_cik < 1
    ):
        raise ValueError(
            "response payload must contain a positive integer cik."
        )

    if (
        not isinstance(raw_entity_name, str)
        or not raw_entity_name.strip()
    ):
        raise ValueError(
            "response payload must contain a nonblank entityName."
        )

    if not isinstance(raw_facts, Mapping):
        raise ValueError(
            "response payload must contain a facts JSON object."
        )

    return CompanyFactsResponse(
        cik=raw_cik,
        entity_name=raw_entity_name.strip(),
        facts=dict(raw_facts),
    )