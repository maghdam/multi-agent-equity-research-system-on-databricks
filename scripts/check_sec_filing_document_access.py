"""Inspect one SEC 10-K document and its identity metadata.

This is a read-only access diagnostic; it does not persist the document or
implement production filing selection and section extraction.
"""

from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import dotenv_values

# Reuse private settings without displaying them.
env_path = Path(__file__).resolve().parents[1] / ".env"
config = dotenv_values(env_path, interpolate=False)
user_agent = (config.get("SEC_USER_AGENT") or "").strip()

if not user_agent:
    raise SystemExit("Missing SEC_USER_AGENT. Check your local .env file.")

# Fixed inspection example—not a production latest-filing rule.
document_url = (
    "https://www.sec.gov/Archives/edgar/data/"
    "320193/000032019325000079/aapl-20250927.htm"
)

try:
    response = requests.get(
        document_url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html, application/xhtml+xml",
        },
        timeout=30,
        allow_redirects=False,
    )
except requests.RequestException:
    raise SystemExit("Filing-document request failed.") from None

print("HTTP status:", response.status_code)

if response.status_code != 200:
    raise SystemExit("Document access failed. Review the status.")

content_type = (
    response.headers.get("Content-Type", "")
    .split(";", 1)[0]
    .strip()
    .lower()
)

print("Content type:", content_type)

if content_type not in ("text/html", "application/xhtml+xml"):
    raise SystemExit("Expected an HTML document.")

if not response.content.strip():
    raise SystemExit("The response body is empty.")

print("Response bytes:", len(response.content))

# Inspect identity fields without claiming validation yet.
soup = BeautifulSoup(response.content, "html.parser")

identity_concepts = (
    "dei:EntityCentralIndexKey",
    "dei:EntityRegistrantName",
    "dei:DocumentType",
    "dei:DocumentPeriodEndDate",
    "dei:AmendmentFlag",
)

for concept in identity_concepts:
    matches = soup.find_all(
        "ix:nonnumeric",
        attrs={"name": concept},
    )

    print(f"\n{concept}: matches={len(matches)}")

    if not matches:
        print("Status: not found")
        continue

    # Bounded inspection, not a first-match selection rule.
    for number, tag in enumerate(matches[:3], start=1):
        element_text = tag.get_text(" ", strip=True)

        sample = {
            "element_text": element_text[:200],
            "characters": len(element_text),
            "context_ref": tag.get("contextref"),
            "format": tag.get("format"),
            "continued_at": tag.get("continuedat"),
            "nil": tag.get("xsi:nil"),
        }

        print(f"Sample {number}:", sample)

# Follow the references found in the identity fields.
context_refs = set()

for concept in identity_concepts:
    tags = soup.find_all("ix:nonnumeric", attrs={"name": concept})

    for tag in tags:
        context_ref = tag.get("contextref")
        if context_ref:
            context_refs.add(context_ref)

print("\nReferenced contexts:", len(context_refs))

# Bounded inspection—not full context validation.
for context_ref in sorted(context_refs)[:5]:
    contexts = soup.find_all(
        "xbrli:context",
        attrs={"id": context_ref},
    )

    print(f"\nContext {context_ref}: matches={len(contexts)}")

    if len(contexts) != 1:
        print("Status: missing or ambiguous context")
        continue

    context_markup = contexts[0].prettify()

    print("Parsed context markup characters:", len(context_markup))
    print(context_markup[:2000])

    if len(context_markup) > 2000:
        print("[Context preview truncated]")

print("\nInspection only; identity validation and section extraction are pending.")
