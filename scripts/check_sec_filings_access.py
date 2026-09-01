"""Inspect SEC filing metadata for the configured sample companies.

This is a read-only access diagnostic; it does not persist filing data or
implement the production filing-selection rule.
"""

from pathlib import Path
from time import sleep

import requests
from dotenv import dotenv_values

# Reuse private settings without displaying them.
env_path = Path(__file__).resolve().parents[1] / ".env"
config = dotenv_values(env_path, interpolate=False)
user_agent = (config.get("SEC_USER_AGENT") or "").strip()

if not user_agent:
    raise SystemExit("Missing SEC_USER_AGENT. Check your local .env file.")

# Temporary diagnostic scope; the production job will use shared configuration.
companies = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
}

fields = (
    "accessionNumber",
    "filingDate",
    "reportDate",
    "form",
    "primaryDocument",
)

for index, (symbol, cik) in enumerate(companies.items()):
    # Space requests to remain respectful of the SEC service.
    if index > 0:
        sleep(1)

    try:
        response = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
            },
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise SystemExit(f"{symbol}: SEC request failed.") from None

    print(f"\n{symbol} HTTP status:", response.status_code)

    if response.status_code != 200:
        raise SystemExit("Submissions access failed. Review the status.")

    try:
        payload = response.json()
    except ValueError:
        raise SystemExit("The response was not valid JSON.") from None

    if not isinstance(payload, dict):
        raise SystemExit(f"{symbol}: unexpected response structure.")

    returned_cik = str(payload.get("cik", ""))

    if (
        not returned_cik.isascii()
        or not returned_cik.isdigit()
        or len(returned_cik) > 10
        or returned_cik.zfill(10) != cik
    ):
        raise SystemExit(f"{symbol}: invalid or mismatched CIK.")

    filings = payload.get("filings")

    if not isinstance(filings, dict):
        raise SystemExit(f"{symbol}: missing filings structure.")

    recent = filings.get("recent")

    if not isinstance(recent, dict) or not all(
        isinstance(recent.get(field), list) for field in fields
    ):
        raise SystemExit(f"{symbol}: invalid recent-filing arrays.")

    # Each position across these arrays describes the same filing.
    if len({len(recent[field]) for field in fields}) != 1:
        raise SystemExit(f"{symbol}: filing arrays have different lengths.")

    annual_indices = [
        i
        for i, form in enumerate(recent["form"])
        if form in ("10-K", "10-K/A")
    ]

    print("CIK:", cik)
    print("Recent filing rows:", len(recent["form"]))
    print("10-K / 10-K/A rows in recent history:", len(annual_indices))

    # Bounded samples in response order—not a latest-filing rule.
    for number, row_index in enumerate(annual_indices[:3], start=1):
        sample = {field: recent[field][row_index] for field in fields}
        print(f"Sample {number}:", sample)
