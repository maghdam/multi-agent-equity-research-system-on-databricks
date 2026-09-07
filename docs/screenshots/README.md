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

Why it matters:

Shows multi-turn behavior that remains attached to the signed active research
context instead of becoming an unrestricted chatbot.

### 6. Databricks Catalog / medallion assets

Suggested filename:

`06-databricks-catalog.png`

Capture the Catalog Explorer with enough of the schema/table tree visible to show the
implemented data architecture:

- Bronze:
  - `price_responses`;
  - `news_responses`;
  - `company_facts_responses`;
  - `filing_documents`;
- Silver:
  - `daily_prices`;
  - `news_articles`;
  - `company_facts`;
  - `filing_sections`;
- Gold:
  - `market_metrics`;
  - `fundamental_metrics`;
- AI/RAG:
  - `research_documents`;
  - `research_chunks`;
  - `research_chunks_index`;
  - `supervisor_evaluation_dataset`.

Why it matters:

Shows that Bronze/Silver/Gold/RAG are real Unity Catalog assets behind the app rather
than architecture-diagram labels.

Crop or resize the Catalog Explorer so schema/table names are legible. The owner email
column is not needed for the portfolio and should be excluded from the crop when
possible.

### 7. Final MLflow evaluation metrics

Suggested filenames:

```text
07-mlflow-evaluation-1.png
07-mlflow-evaluation-2.png
07-mlflow-evaluation-3.png
07-mlflow-evaluation-4.png
```

Use the four images as one ordered evidence set for the final managed E1/E2 evaluation
run `spiffy-rat-765`. Splitting the Databricks metrics table across several readable
screenshots is preferred to shrinking the whole table into one unreadable image.

The first image should ideally establish the run identity/status and begin the metrics
table; the remaining images should continue the metric list with as little overlap as
practical.

Key values worth keeping visible:

- report section grounding contract = `1`;
- safety = `1`;
- retrieval trace sufficiency = `1`;
- relevance to query = `1`;
- narrative trace groundedness = `1`;
- required report sections = `1`;
- expected request mode/symbol scope = `1`;
- all configured project guideline means = `1`;
- retrieval empty-route count = `0`;
- overall retrieval relevance = `0.8611`;
- AAPL recent-development retrieval relevance = `0.775`;
- MSFT recent-development retrieval relevance = `0.3333`;
- evidence count mean = `11`.

Why it matters:

Shows measured grounding/safety/relevance quality and also preserves the honest
retrieval-precision tradeoff instead of presenting only perfect scores.

Prefer crops centered on the run name/status and metrics. The `Created by` email,
workspace navigation, and other account details add little portfolio value and may be
cropped out. Keep the four screenshots at a consistent zoom/width so they read like a
single paginated metric table.

### 8. Optional scope-refusal evidence

Suggested filename:

`08-followup-scope-refusal.png`

Capture the verified out-of-active-context NVDA recommendation refusal.

### 9. Optional application observability

Suggested filename:

`09-app-observability.png`

Capture bounded `APP_EVENT` output showing research/follow-up/feedback lifecycle.

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
