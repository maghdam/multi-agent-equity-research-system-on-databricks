# Portfolio Screenshot Checklist

This directory contains only deliberately reviewed, publication-safe images for the
public portfolio.

The private Databricks application itself is not the public artifact. These images
should demonstrate the product and engineering controls without redistributing
provider source content or exposing workspace credentials.

## Required final screenshots

### 1. Comparison overview

Suggested filename:

`01-comparison-overview.png`

Capture:

- AAPL as primary;
- MSFT as comparison;
- 60 trading sessions;
- ready research status;
- both structured research snapshots;
- compact research summary.

Why it matters:

Shows the product shape immediately: bounded comparison research backed by structured
Gold data plus multi-agent synthesis.

### 2. Normalized market comparison

Suggested filename:

`02-market-comparison.png`

Capture:

- Market tab;
- AAPL/MSFT normalized 60-session price-history chart;
- enough controlled metric cards to show return/volatility context.

Why it matters:

Shows that the application has a real analytical surface rather than being only a
chat interface.

### 3. Validated research report

Suggested filename:

`03-research-report.png`

Capture:

- ready report status;
- market/fundamental/recent-development/risk sections;
- comparative assessment if the page height permits;
- source-finding IDs visible where useful.

Do not capture a page area that reproduces raw retrieved article/chunk bodies. The
application is designed not to render those bodies.

### 4. Evidence provenance

Suggested filename:

`04-evidence-provenance.png`

Capture:

- Evidence tab;
- publication-safe provenance cards;
- company/date/domain;
- retrieval rank/chunk position;
- source record;
- supported finding IDs;
- original-source links.

Avoid opening the provider article itself for the screenshot. The app card is the
portfolio artifact.

### 5. Grounded follow-up

Suggested filename:

`05-grounded-followup.png`

Capture at least:

- one structured factual follow-up;
- one source/provenance follow-up with a safe clickable citation.

A second optional image may show an out-of-scope refusal, for example the verified
NVDA recommendation request:

`06-followup-scope-refusal.png`

Why it matters:

Shows multi-turn behavior that remains attached to the signed active research
context instead of becoming an unrestricted chatbot.

### 6. Evaluation / observability evidence

Optional but valuable:

`07-mlflow-evaluation.png`

or

`07-app-observability.png`

Use a screenshot of:

- privacy-safe MLflow evaluation metrics/spans; or
- bounded `APP_EVENT` output showing research/follow-up/feedback lifecycle.

Make sure no raw prompts, provider text, credentials, or unrestricted trace payloads
are visible.

## Manual review before commit

For every image, confirm:

- no API keys, PATs, OAuth secrets, cookies, or private tokens;
- no raw Alpaca API payload;
- no substantial Benzinga/Alpaca article body or retrieved news chunk;
- no local filesystem path that reveals unnecessary personal information;
- no browser tab/account detail that is irrelevant to the project;
- no private email/address/contact data beyond what is intentionally public;
- the image adds distinct portfolio value instead of duplicating another screenshot.

The public-repository audit requires committed images to remain under
`docs/screenshots/` or `docs/images/`, but the automated audit cannot judge the
amount of copyrighted text in pixels. Human review is mandatory.

## Capture quality

Prefer:

- browser zoom around 80–100% so the app remains legible;
- one clear feature per image;
- no giant empty areas;
- dark or light theme consistently across the main sequence;
- crop browser chrome when it adds no useful context;
- PNG for UI screenshots.

Do not add decorative annotations that obscure the application's actual behavior.

## Final Markdown usage

The main README should use only the strongest two or three images to keep the landing
page concise. The remaining reviewed screenshots can be linked from a portfolio/demo
section or this directory.
