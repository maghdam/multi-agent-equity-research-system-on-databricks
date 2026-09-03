"""Verify SEC filing metadata access and production 10-K selection logic.

This is a read-only live diagnostic. It exercises shared project
configuration and reusable filing-selection helpers without persisting data.
"""

from __future__ import annotations

import sys
from pathlib import Path
from time import monotonic, sleep

import requests
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.config import load_equities
from equity_research.sec_filings import (
    build_filing_document_path,
    build_submissions_path,
    parse_recent_10k_filings,
    select_latest_10k,
)
from equity_research.sec_http import (
    build_sec_request_headers,
    calculate_sec_spacing_delay,
)


SEC_DATA_BASE_URL = "https://data.sec.gov"


# Reuse private settings without displaying them.
env_path = PROJECT_ROOT / ".env"
config = dotenv_values(env_path, interpolate=False)

user_agent = (config.get("SEC_USER_AGENT") or "").strip()

if not user_agent:
    raise SystemExit(
        "Missing SEC_USER_AGENT. Check your local .env file."
    )

headers = build_sec_request_headers(user_agent)
equities = load_equities()

previous_request_started_at: float | None = None

for project_symbol, equity in equities.items():
    if previous_request_started_at is not None:
        elapsed_seconds = monotonic() - previous_request_started_at
        spacing_delay = calculate_sec_spacing_delay(elapsed_seconds)

        if spacing_delay > 0:
            sleep(spacing_delay)

    sec_cik = equity.sec_cik
    submissions_path = build_submissions_path(sec_cik)

    previous_request_started_at = monotonic()

    try:
        response = requests.get(
            f"{SEC_DATA_BASE_URL}{submissions_path}",
            headers=headers,
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise SystemExit(
            f"{project_symbol}: SEC submissions request failed."
        ) from None

    print(
        f"\n{project_symbol} HTTP status:",
        response.status_code,
    )

    if response.status_code != 200:
        raise SystemExit(
            f"{project_symbol}: submissions access failed."
        )

    try:
        payload = response.json()
    except ValueError:
        raise SystemExit(
            f"{project_symbol}: SEC response was not valid JSON."
        ) from None

    try:
        filings = parse_recent_10k_filings(
            payload,
            sec_cik,
        )

        selected = select_latest_10k(filings)

        document_path = build_filing_document_path(
            sec_cik,
            selected,
        )
    except ValueError as exc:
        raise SystemExit(
            f"{project_symbol}: {exc}"
        ) from None

    print("CIK:", sec_cik)
    print("Eligible exact 10-K rows:", len(filings))

    print(
        "Selected filing:",
        {
            "accessionNumber": selected.accession_number,
            "filingDate": selected.filing_date.isoformat(),
            "reportDate": selected.report_date.isoformat(),
            "form": selected.form,
            "primaryDocument": selected.primary_document,
        },
    )

    print("Document path:", document_path)