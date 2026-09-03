"""Reusable SEC filing-metadata selection and document-path logic."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date


SEC_SUBMISSIONS_PATH_PREFIX = "/submissions"
SEC_ARCHIVES_PATH_PREFIX = "/Archives/edgar/data"

ACCESSION_PATTERN = re.compile(r"\d{10}-\d{2}-\d{6}")
CIK_PATTERN = re.compile(r"\d{10}")

REQUIRED_RECENT_FIELDS = (
    "accessionNumber",
    "filingDate",
    "reportDate",
    "form",
    "primaryDocument",
)


@dataclass(frozen=True)
class FilingMetadata:
    """Validated SEC metadata for one eligible filing."""

    accession_number: str
    filing_date: date
    report_date: date
    form: str
    primary_document: str


def build_submissions_path(cik: str) -> str:
    """Build the SEC submissions path for one normalized CIK."""

    normalized_cik = cik.strip()

    if not CIK_PATTERN.fullmatch(normalized_cik):
        raise ValueError(
            "cik must contain exactly 10 digits, including leading zeros."
        )

    return f"{SEC_SUBMISSIONS_PATH_PREFIX}/CIK{normalized_cik}.json"


def parse_recent_10k_filings(
    payload: object,
    expected_cik: str,
) -> tuple[FilingMetadata, ...]:
    """Validate SEC submissions metadata and return exact 10-K records."""

    normalized_cik = expected_cik.strip()

    if not CIK_PATTERN.fullmatch(normalized_cik):
        raise ValueError(
            "expected_cik must contain exactly 10 digits."
        )

    if not isinstance(payload, Mapping):
        raise ValueError(
            "response payload must be a JSON object."
        )

    raw_cik = payload.get("cik")

    if isinstance(raw_cik, bool):
        raise ValueError(
            "response payload cik does not match expected_cik."
        )

    if isinstance(raw_cik, int):
        if raw_cik < 1:
            raise ValueError(
                "response payload cik does not match expected_cik."
            )

        response_cik = str(raw_cik)

    elif isinstance(raw_cik, str):
        response_cik = raw_cik.strip()

    else:
        raise ValueError(
            "response payload cik does not match expected_cik."
        )

    if (
        not response_cik
        or not response_cik.isascii()
        or not response_cik.isdigit()
        or len(response_cik) > 10
        or response_cik.zfill(10) != normalized_cik
    ):
        raise ValueError(
            "response payload cik does not match expected_cik."
        )

    filings = payload.get("filings")

    if not isinstance(filings, Mapping):
        raise ValueError(
            "response payload must contain a filings JSON object."
        )

    recent = filings.get("recent")

    if not isinstance(recent, Mapping):
        raise ValueError(
            "response payload must contain a filings.recent JSON object."
        )

    field_values: dict[str, list[object]] = {}

    for field in REQUIRED_RECENT_FIELDS:
        values = recent.get(field)

        if not isinstance(values, list):
            raise ValueError(
                f"filings.recent.{field} must be a JSON array."
            )

        field_values[field] = values

    field_lengths = {
        len(values)
        for values in field_values.values()
    }

    if len(field_lengths) != 1:
        raise ValueError(
            "recent filing metadata arrays must have equal lengths."
        )

    row_count = next(iter(field_lengths), 0)

    eligible_filings: list[FilingMetadata] = []

    for row_index in range(row_count):
        raw_form = field_values["form"][row_index]

        if (
            not isinstance(raw_form, str)
            or not raw_form.strip()
        ):
            raise ValueError(
                "filings.recent.form values must be nonblank strings."
            )

        form = raw_form.strip()

        # The Bronze MVP uses only exact Form 10-K filings.
        # Other filing types may legitimately contain metadata that
        # is incomplete for fields required by the 10-K contract.
        if form != "10-K":
            continue

        accession_number = _required_string(
            field_values["accessionNumber"][row_index],
            "accessionNumber",
        )

        filing_date_text = _required_string(
            field_values["filingDate"][row_index],
            "filingDate",
        )

        report_date_text = _required_string(
            field_values["reportDate"][row_index],
            "reportDate",
        )

        primary_document = _required_string(
            field_values["primaryDocument"][row_index],
            "primaryDocument",
        )

        if not ACCESSION_PATTERN.fullmatch(accession_number):
            raise ValueError(
                "accessionNumber must match ##########-##-######."
            )

        if (
            "/" in primary_document
            or "\\" in primary_document
            or primary_document in {".", ".."}
        ):
            raise ValueError(
                "primaryDocument must be a filename, not a path."
            )

        eligible_filings.append(
            FilingMetadata(
                accession_number=accession_number,
                filing_date=_parse_iso_date(
                    filing_date_text,
                    "filingDate",
                ),
                report_date=_parse_iso_date(
                    report_date_text,
                    "reportDate",
                ),
                form=form,
                primary_document=primary_document,
            )
        )

    return tuple(eligible_filings)


def select_latest_10k(
    filings: tuple[FilingMetadata, ...],
) -> FilingMetadata:
    """Select the unique exact 10-K with the greatest filing date."""

    if not filings:
        raise ValueError(
            "no eligible exact 10-K filing was found."
        )

    if any(filing.form != "10-K" for filing in filings):
        raise ValueError(
            "filings must contain only exact 10-K records."
        )

    latest_filing_date = max(
        filing.filing_date
        for filing in filings
    )

    latest_candidates = tuple(
        filing
        for filing in filings
        if filing.filing_date == latest_filing_date
    )

    if len(latest_candidates) != 1:
        raise ValueError(
            "latest exact 10-K filing selection is ambiguous."
        )

    return latest_candidates[0]


def build_filing_document_path(
    cik: str,
    filing: FilingMetadata,
) -> str:
    """Build the SEC Archives path for one selected filing document."""

    normalized_cik = cik.strip()

    if not CIK_PATTERN.fullmatch(normalized_cik):
        raise ValueError(
            "cik must contain exactly 10 digits, including leading zeros."
        )

    if not ACCESSION_PATTERN.fullmatch(filing.accession_number):
        raise ValueError(
            "filing accession number is invalid."
        )

    if (
        not filing.primary_document
        or "/" in filing.primary_document
        or "\\" in filing.primary_document
        or filing.primary_document in {".", ".."}
    ):
        raise ValueError(
            "filing primary document is invalid."
        )

    cik_without_leading_zeros = str(int(normalized_cik))

    accession_without_hyphens = (
        filing.accession_number.replace("-", "")
    )

    return (
        f"{SEC_ARCHIVES_PATH_PREFIX}/"
        f"{cik_without_leading_zeros}/"
        f"{accession_without_hyphens}/"
        f"{filing.primary_document}"
    )


def _required_string(
    value: object,
    field_name: str,
) -> str:
    """Return one required nonblank string."""

    if (
        not isinstance(value, str)
        or not value.strip()
    ):
        raise ValueError(
            f"{field_name} must be a nonblank string."
        )

    return value.strip()


def _parse_iso_date(
    value: str,
    field_name: str,
) -> date:
    """Parse one strict ISO calendar date."""

    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a valid YYYY-MM-DD date."
        ) from exc

    if parsed.isoformat() != value:
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format."
        )

    return parsed