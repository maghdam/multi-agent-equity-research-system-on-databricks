from pathlib import Path

import requests
from dotenv import dotenv_values

# Load private settings without printing them.
env_path = Path(__file__).resolve().parents[1] / ".env"
config = dotenv_values(env_path, interpolate=False)
user_agent = (config.get("SEC_USER_AGENT") or "").strip()

if not user_agent:
    raise SystemExit("Missing SEC_USER_AGENT. Check your local .env file.")

# One request for the official company directory.
# No Alpaca credentials are sent.
try:
    response = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
        timeout=30,
        allow_redirects=False,
    )
except requests.RequestException:
    raise SystemExit("SEC request failed. Check network access.") from None

print("HTTP status:", response.status_code)

if response.status_code != 200:
    raise SystemExit("SEC access check failed. Review the HTTP status.")

try:
    payload = response.json()
except ValueError:
    raise SystemExit("The response was not valid JSON.") from None

if not isinstance(payload, dict) or not all(
    isinstance(row, dict) for row in payload.values()
):
    raise SystemExit("Unexpected SEC directory structure.")

# Temporary diagnostic scope; shared configuration comes later.
symbols = ("AAPL", "MSFT")

for symbol in symbols:
    matches = [
        row for row in payload.values()
        if row.get("ticker") == symbol
    ]

    if len(matches) != 1:
        raise SystemExit(f"Missing or ambiguous SEC mapping for {symbol}.")

    company = matches[0]
    cik = company.get("cik_str")
    name = company.get("title")

    if type(cik) is not int or not 0 < cik < 10**10:
        raise SystemExit(f"Invalid CIK for {symbol}.")

    if not isinstance(name, str) or not name.strip():
        raise SystemExit(f"Missing company name for {symbol}.")

    print(f"{symbol}: CIK={cik:010d}, company={name.strip()}")