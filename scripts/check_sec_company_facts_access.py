from decimal import Decimal
from pathlib import Path
from time import monotonic, sleep
import sys

import requests
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.config import load_equities  # noqa: E402
from equity_research.sec_company_facts import (  # noqa: E402
    SEC_DATA_HOST,
    build_company_facts_path,
    parse_company_facts_response,
)
from equity_research.sec_http import (  # noqa: E402
    build_sec_request_headers,
    calculate_sec_spacing_delay,
)

# Load private settings without displaying them.
env_path = PROJECT_ROOT / ".env"
config = dotenv_values(env_path, interpolate=False)
user_agent = (config.get("SEC_USER_AGENT") or "").strip()

if not user_agent:
    raise SystemExit("Missing SEC_USER_AGENT. Check your local .env file.")

companies = load_equities()
headers = build_sec_request_headers(user_agent)

previous_request_started_at: float | None = None

for symbol, equity in companies.items():
    cik = equity.sec_cik

    if previous_request_started_at is not None:
        elapsed_seconds = monotonic() - previous_request_started_at
        spacing_delay = calculate_sec_spacing_delay(elapsed_seconds)

        if spacing_delay > 0:
            sleep(spacing_delay)

    path = build_company_facts_path(cik)
    url = f"https://{SEC_DATA_HOST}{path}"

    previous_request_started_at = monotonic()

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

    try:
        parsed = parse_company_facts_response(payload)
    except ValueError as exc:
        raise SystemExit(
            f"{symbol}: invalid company-facts response: {exc}"
        ) from None

    if parsed.cik != int(cik):
        raise SystemExit(f"{symbol}: returned CIK does not match.")

    returned_cik = parsed.cik
    entity_name = parsed.entity_name
    facts = parsed.facts

    us_gaap = facts.get("us-gaap")

    if not isinstance(us_gaap, dict) or not us_gaap:
        raise SystemExit(f"{symbol}: no US-GAAP concepts available.")

    # Display metadata only, not the full financial-facts payload.
    print("CIK:", f"{returned_cik:010d}")
    print("Entity name:", entity_name)
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