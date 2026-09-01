from decimal import Decimal
from pathlib import Path
from time import sleep

import requests
from dotenv import dotenv_values

# Load private settings without displaying them.
env_path = Path(__file__).resolve().parents[1] / ".env"
config = dotenv_values(env_path, interpolate=False)
user_agent = (config.get("SEC_USER_AGENT") or "").strip()

if not user_agent:
    raise SystemExit("Missing SEC_USER_AGENT. Check your local .env file.")

# Confirmed directory mappings; temporary diagnostic inputs.
# The ingestion pipeline will use shared configuration later.
companies = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
}

headers = {
    "User-Agent": user_agent,
    "Accept": "application/json",
}

for index, (symbol, cik) in enumerate(companies.items()):
    # Keep requests sequential, with a pause between companies.
    if index > 0:
        sleep(1)

    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise SystemExit(f"{symbol}: SEC request failed.") from None

    print(f"\n{symbol} HTTP status:", response.status_code)

    if response.status_code != 200:
        raise SystemExit("Company-facts access failed. Review the status.")

    try:
        payload = response.json(parse_float=Decimal)
    except ValueError:
        raise SystemExit("The response was not valid JSON.") from None

    if not isinstance(payload, dict):
        raise SystemExit("Unexpected company-facts response structure.")

    returned_cik = payload.get("cik")
    entity_name = payload.get("entityName")
    facts = payload.get("facts")

    if type(returned_cik) is not int or returned_cik != int(cik):
        raise SystemExit(f"{symbol}: returned CIK does not match.")

    if not isinstance(entity_name, str) or not entity_name.strip():
        raise SystemExit(f"{symbol}: missing entity name.")

    if not isinstance(facts, dict) or not facts:
        raise SystemExit(f"{symbol}: missing financial-facts structure.")

    us_gaap = facts.get("us-gaap")

    if not isinstance(us_gaap, dict) or not us_gaap:
        raise SystemExit(f"{symbol}: no US-GAAP concepts available.")

    # Display metadata only, not the full financial-facts payload.
    print("CIK:", f"{returned_cik:010d}")
    print("Entity name:", entity_name.strip())
    print("Taxonomies:", sorted(facts))
    print("US-GAAP concepts:", len(us_gaap))

    # Inspection candidates only—not final metric mappings.
    candidates = {
        "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "net_income": "NetIncomeLoss",
        "total_assets": "Assets",
    }

    for metric, concept_name in candidates.items():
        print(f"\nCandidate {metric}: {concept_name}")

        if concept_name not in us_gaap:
            print("Status: not present")
            continue

        concept = us_gaap[concept_name]

        if not isinstance(concept, dict):
            raise SystemExit(f"{symbol}: invalid concept structure.")

        label = concept.get("label")
        units = concept.get("units")

        if not isinstance(label, str) or not label.strip():
            raise SystemExit(f"{symbol}: invalid concept label.")

        if not isinstance(units, dict) or not units:
            raise SystemExit(f"{symbol}: invalid concept units.")

        print("Label:", label)

        for unit, observations in sorted(units.items()):
            if not isinstance(observations, list):
                raise SystemExit(f"{symbol}: invalid observation list.")

            print(f"Unit: {unit}; observations: {len(observations)}")

            # Structure samples—not a latest-value selection rule.
            fields = (
                "start", "end", "val", "accn", "fy",
                "fp", "form", "filed", "frame",
            )

            for number, observation in enumerate(observations[:2], start=1):
                if not isinstance(observation, dict):
                    raise SystemExit(f"{symbol}: invalid observation structure.")

                sample = {
                    field: observation.get(field, "<absent>")
                    for field in fields
                }
                print(f"Sample {number} (response order):", sample)