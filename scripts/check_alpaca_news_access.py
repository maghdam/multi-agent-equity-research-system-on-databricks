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

# Request one small page of historical news.
params = {
    "symbols": "AAPL,MSFT",
    "start": "2026-08-24T00:00:00Z",
    "end": "2026-08-28T23:59:59Z",
    "sort": "desc",
    "limit": 3,
    "include_content": "true",
    "exclude_contentless": "false",
}

headers = {
    "APCA-API-KEY-ID": api_key,
    "APCA-API-SECRET-KEY": api_secret,
}

# Send credentials only to the market-data endpoint; do not print them.
try:
    response = requests.get(
        "https://data.alpaca.markets/v1beta1/news",
        params=params,
        headers=headers,
        timeout=30,
        allow_redirects=False,
    )
except requests.RequestException:
    raise SystemExit("Request failed. Check network access.") from None

print("HTTP status:", response.status_code)

if response.status_code != 200:
    raise SystemExit("News access check failed. Review the HTTP status.")

try:
    payload = response.json()
except ValueError:
    raise SystemExit("The response was not valid JSON.") from None

if not isinstance(payload, dict) or not isinstance(payload.get("news"), list):
    raise SystemExit("Unexpected news response structure.")

articles = payload["news"]

print("Articles returned:", len(articles))
print("More pages available:", bool(payload.get("next_page_token")))

if not articles:
    raise SystemExit("No articles returned; we need another sample window.")

# Inspect structure without printing headlines, summaries, or article bodies.
for article in articles:
    if not isinstance(article, dict):
        raise SystemExit("Unexpected article structure.")

    print("\nArticle fields:", sorted(article))

    for field in ("id", "symbols", "created_at", "updated_at", "source", "url"):
        print(f"{field}: {article.get(field)}")

    for field in ("headline", "summary", "content"):
        value = article.get(field)
        length = len(value) if isinstance(value, str) else None
        print(f"{field}: type={type(value).__name__}, characters={length}")