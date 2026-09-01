from pathlib import Path

import requests
from dotenv import dotenv_values

# Read credentials from the project-root .env file.
env_path = Path(__file__).resolve().parents[1] / ".env"
config = dotenv_values(env_path, interpolate=False)

api_key = (config.get("ALPACA_API_KEY") or "").strip()
api_secret = (config.get("ALPACA_SECRET_KEY") or "").strip()

if not api_key or not api_secret:
    raise SystemExit("Missing credentials. Check your local .env file.")

# Request one completed historical day, using our data contract.
params = {
    "symbols": "AAPL,MSFT",
    "timeframe": "1Day",
    "start": "2026-08-27T00:00:00-04:00",
    "end": "2026-08-27T23:59:59-04:00",
    "feed": "sip",
    "adjustment": "split",
    "currency": "USD",
    "limit": 10,
}

headers = {
    "APCA-API-KEY-ID": api_key,
    "APCA-API-SECRET-KEY": api_secret,
}

# Send credentials only to the market-data endpoint; do not print them.
try:
    response = requests.get(
        "https://data.alpaca.markets/v2/stocks/bars",
        params=params,
        headers=headers,
        timeout=30,
        allow_redirects=False,
    )
except requests.RequestException:
    raise SystemExit("Request failed. Check network access.") from None

print("HTTP status:", response.status_code)

if response.status_code != 200:
    raise SystemExit("Access check failed. Keep the feed unchanged for review.")

# Display the original market-data JSON for inspection.
print(response.text)