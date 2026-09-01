# Data Contracts

The essential rules for the MVP's four datasets. These are **planned acceptance rules**, not guarantees made by the providers or evidence of implemented validation.

**Status:** Price, news, and company-facts drafts have been reviewed. Filing-text rules are partly defined. Local access checks passed within the limits below; production ingestion, automated contract tests, and complete coverage checks remain pending. Progress is tracked in [PLAN.md](PLAN.md).

## Planned data flow and inventory

The MVP plans three Databricks schemas: Bronze for raw source history, Silver for validated business records, and Gold for application-oriented metrics. AI retrieval assets are built from Silver text; they are not another medallion layer.

| Source dataset | Bronze | Silver | Gold or AI consumption |
|---|---|---|---|
| Alpaca daily bars | `price_responses`: original response pages and retrieval metadata | `daily_prices`: one typed, validated daily bar per stock/session | `market_metrics`: comparable returns, volatility, drawdown, and trend measures |
| Alpaca company news | `news_responses`: original article versions and retrieval metadata | `news_articles`: one selected, validated version per article | Current cited evidence in `research_documents` and its vector index |
| SEC company facts | `company_facts_responses`: original company snapshots and retrieval metadata | `company_facts`: filing-level typed facts with periods and provenance | `fundamental_metrics`: selected comparable financial measures |
| SEC selected filings | `filing_documents`: filing metadata and original HTML | `filing_sections`: cleaned Item 1 and Item 1A sections with provenance | Cited chunks in the shared `research_documents` dataset and vector index |

This initial inventory contains four Bronze datasets, four Silver datasets, two Gold data products, and one shared retrieval-document dataset plus its vector index. It excludes configuration and operational audit/quarantine records. Physical identifiers and storage details will be finalized immediately before implementing each layer.

Columns are expected to evolve by purpose: Bronze keeps the complete source payload plus provenance; Silver selects, renames, derives, types, validates, and deduplicates the fields defined below; Gold changes the grain again to provide reusable comparison measures. Unused source fields remain recoverable from Bronze. Final Gold grains, formulas, and columns remain pending and must be documented and tested before Gold implementation.

## Shared conventions

- **Universe:** AAPL and MSFT initially, defined in `config/equities.json` and loaded through the validated shared loader. Four offline tests cover the real configuration, duplicate/CIK rejection, and configuration-only expansion. New live stocks still require identifier, source-coverage, backfill, and downstream readiness checks.
- **Layers:** Bronze preserves original responses and retrieval history; Silver holds validated records; Gold defines comparable analytics. Existing `scripts/check_*.py` files are optional local diagnostics, not pipeline jobs.
- **Provenance:** Store `source_system` (string), `fetched_at` (UTC timestamp of successful receipt), and `ingestion_run_id` (string). A response shares its retrieval timestamp; requests/pages in one execution share the run ID. Preserve original metadata on replay; track transformation runs separately.
- **Fields:** Required means present, non-null, correctly typed, and nonblank for strings. Optional strings normalize missing/null/blank to null. Parse real calendar dates and timezone-aware timestamps without guessing.
- **Numbers:** Parse exact integers/decimals without binary floating-point conversion. Reject booleans, numeric strings, nonfinite values, overflow, or any cast requiring rounding/truncation. Numerically equivalent trailing zeros are allowed. Missing values are never zero.
- **Failures:** Retain raw rejected data in Bronze and record failed rules and provenance without credentials or full article text. Track accepted/rejected/out-of-scope/duplicate counts. Published business keys must be unique. Failed refreshes must not appear successful or fresh; completeness and freshness need separate checks.
- **Safe use:** Keep credentials out of Git/data/logs and use synthetic public test fixtures. Confirm storage, retention, processing, indexing/model-provider use, and [public redistribution permissions](https://alpaca.markets/support/redistribute-alpaca-api) at the relevant stage; API access alone is insufficient. Permissions remain unverified. Treat retrieved text as untrusted evidence, never agent instructions; extract plain text without executing HTML or loading remote resources.

## 1. Daily stock prices

**Use:** Historical market comparisons. **Source:** Alpaca bars, `sip` feed, `split` adjustment, `1Day`, `USD`. Returns exclude dividend income; do not silently switch feeds.

**One record:** One stock's daily bar. **Key:** `(symbol, bar_timestamp, feed, adjustment)` within this USD dataset.

### Schema

All fields are required, together with shared provenance (`source_system = alpaca`).

| Field | Source / meaning | Silver type |
|---|---|---|
| symbol | Symbol key in response; configured ticker | String |
| bar_timestamp | `t`; start of daily interval | UTC timestamp |
| trading_date | Date of bar_timestamp in America/New_York | Date |
| open, high, low, close | `o`, `h`, `l`, `c` respectively | DECIMAL(20,8) |
| volume | `v`; traded share quantity | DECIMAL(20,8) |
| feed, adjustment, timeframe, currency | Request settings: sip, split, 1Day, USD | Strings |

### Acceptance and updates

- All prices **and volume** must be positive; `low <= open <= high` and `low <= close <= high`.
- Accept only completed days: trading_date must precede the date of original fetched_at in America/New_York. Exclude the current partial day.
- Validate exact DECIMAL(20,8) storage, including decimal volume; allow at most 12 integer and 8 fractional digits.
- Keep one valid record per key. Identical repeats do not add rows; changed values use the latest valid original fetched_at. Older replays cannot overwrite newer observations.
- Flag conflicting versions that cannot be ordered reliably rather than choosing arbitrarily. Exclude invalid records with reasons; fail final uniqueness validation.

## 2. Company news

**Use:** Dated, cited company context—not proof that news caused a price movement. **Source:** Alpaca News API.

**One record:** One provider article, even when tagged with multiple stocks. **Key:** `(source_system, article_id)`.

### Schema

Shared provenance is required (`source_system = alpaca`). All fields below are required unless marked optional.

| Field | Source / meaning | Type |
|---|---|---|
| article_id | `id`; positive integer, not boolean/string | Integer |
| headline | `headline` | String |
| symbols | Full provider `symbols` list | Array of strings |
| article_created_at | `created_at` | UTC timestamp |
| article_updated_at | `updated_at` | UTC timestamp |
| article_source | `source`; publisher, not API provider | String |
| url | `url`; citation link | String |
| summary, content | Corresponding provider fields; content may contain HTML | Optional strings |

### Acceptance and version selection

- Each symbol tag must be a nonblank string. Empty arrays, repeated tags, and other tickers are valid; the publisher is not restricted to the observed Benzinga sample.
- Require `article_created_at <= article_updated_at <= fetched_at`, with no clock-skew allowance. Citation URLs must be absolute HTTP(S), have a hostname, and contain no username/password; this does not establish safety or reachability.
- Among valid observations and existing Silver records, select the greatest article_updated_at **before filtering for configured stocks**. Replace all article fields together; never borrow missing text from an older revision.
- Identical core source fields at the same key/update time are repeats. Compare symbol lists as sets and exclude ingestion metadata from content equality. Keep the earliest fetched_at, breaking ties by the lexicographically smallest ingestion_run_id.
- Different core fields at the selected update time are a conflict; later retrieval is not a tiebreaker. Fail the whole news Silver refresh before publication and preserve the previous successful snapshot. Final uniqueness failures do the same.
- Derive stock relationships from the selected version's tags intersected with configuration. Remove outdated relationships; no overlap means ineligible for research, not invalid metadata. Full provider tags remain preserved and never expand the universe.

### Research text

Use cleaned content, or a cleaned summary explicitly labelled summary-only. If neither is usable, retain metadata but exclude the article from text retrieval; a headline is not a full article. Do not fetch citation URLs automatically to fill missing text.

Carry article identity, publisher, URL, article timestamps, retrieval provenance, and content/summary origin into retrieval documents. Invalidate outdated index entries when revisions or eligibility change. Factual claims require supporting citations. Real article bodies, payloads, and derived indexes must not be committed publicly; synthetic demo data remains the fallback while permissions are unresolved.

## 3. SEC company facts

**Use:** Reported business performance and financial position. **Source:** SEC EDGAR Company Facts; `source_system = sec_edgar`.

**One record:** One concept/unit/period reported in one filing. Different filings remain separate even when amounts match.

**Key:** `(source_system, cik, taxonomy, concept, unit, period_start, period_end, accession_number)`. Compare null period_start values as equal for instant facts.

### Scope and schema

Initial Silver scope is the following `us-gaap` concepts in USD. Presence was observed for both companies; recent coverage and Gold comparability are not yet established.

| Metric | SEC concept | Period type |
|---|---|---|
| Revenue | RevenueFromContractWithCustomerExcludingAssessedTax | Duration |
| Net income | NetIncomeLoss | Duration |
| Total assets | Assets | Instant |

All fields are required unless marked optional or conditional.

| Field | Source / meaning | Type |
|---|---|---|
| cik | Top-level `cik`; validated company identifier | 10-digit string |
| taxonomy, concept, unit | Keys in `facts` and its `units` mapping | Strings |
| accession_number | Observation `accn`; preserve hyphens | String |
| fact_value | `val`; original USD amount/sign | DECIMAL(28,8) |
| period_start | `start`; required for duration, null for instant | Date |
| period_end | `end` | Date |
| filing_form | `form`; preserve amendment suffixes | String |
| filing_date | `filed` | Date |
| entity_name, concept_label | Top-level `entityName`, concept `label` | Optional strings |
| filing_fiscal_year | `fy`; filing label, not necessarily fact year | Optional integer |
| filing_fiscal_period, frame | `fp`, `frame`; source labels | Optional strings |

Shared provenance is required, plus a unique string `source_response_id` linking all extracted facts to their original Bronze response. New retrievals receive new IDs; replay preserves them.

### Acceptance

- Response structure, provenance, and CIK must match the configured request; failure stops the SEC refresh. Validate CIK before zero-padding, never truncate it. Company names are descriptive, not identifiers.
- Accession format is 10 ASCII digits, hyphen, 2 digits, hyphen, 6 digits. Its prefix need not equal the reporting CIK.
- Preserve original USD units and signs; negative net income is valid. DECIMAL(28,8) allows 20 integer and 8 fractional digits, without loss. Optional fiscal year must be an integer, not a boolean/string.
- Duration facts require start/end with start <= end. Instant facts require end and an absent/null start; flag unexpected starts rather than erase them.
- Actual fact dates govern the period—not filing form, fiscal labels, or frame. Silver does not annualize, derive quarters, or sum repeated disclosures.
- Other taxonomy/concept/unit combinations stay in Bronze as out of scope. Invalid individual facts are excluded with reasons. Missing selected concepts/units are reported unavailable, not substituted.

### Duplicates, snapshots, and replay

- Within one response, identical normalized fields at the same key collapse to one fact. Conflicting fields fail the whole SEC Silver refresh before publication.
- For each company, select the complete response with the greatest original fetched_at **before fact validation**. For tied latest timestamps, use the lexicographically smallest response ID only if raw payloads are identical; otherwise fail the refresh.
- Validate and publish atomically. Replace the company's current facts from that response only: no fallback to an older response and no filling gaps with older facts. Preserve the previous successful output on refresh failure and report it as not refreshed.
- Older replays cannot overwrite newer current snapshots. A historical retrieval cutoff `T` uses only stored responses with fetched_at <= T; none means unavailable. Historical reconstruction must not overwrite current Silver.
- Today's response filtered by an old filing_date is not evidence of what the pipeline knew then. Filing dates are not exact public-availability timestamps. Gold period, filing-version, and coverage rules remain to be defined.

## 4. SEC selected filing text - partial draft

**Use:** Company-reported Business (Item 1) and Risk Factors (Item 1A) evidence from annual Form 10-K filings. Quarterly/current-event reports and comprehensive filing coverage are outside the initial scope.

**One record:** One complete selected section of one filing. **Key:** `(source_system, cik, accession_number, section_code)`, with source_system `sec_edgar` and project section codes `item_1` / `item_1a` (not HTML anchor IDs).

Bronze preserves the document and provenance; Silver contains cleaned section text. Retrieval/extraction history is separate from business identity. Later RAG chunks link back to sections, not the other way around. Preserve filing identity, filing date, source URL, and section name for citations.

### Agreed identity checks

- Use expected CIK, form, and reportDate from configuration and selected SEC metadata, not a fixed sample.
- Required identity values must be nonblank, non-nil, and unambiguous; context references must resolve uniquely. Document/context CIKs and the SEC identifier scheme must match expectations.
- Document form must match metadata. Decode dates only with supported format rules; document/context period ends must match reportDate, not filingDate. Duration start must not exceed end.
- Company name is descriptive. Record amendment status without treating it as proof of version eligibility. Exclude missing, conflicting, or unsupported identity data from research with a recorded reason.

**Still to define and test:** Filing-version selection, amendment handling, final field mappings/provenance, section-boundary and extraction-quality checks, and content-use boundaries. Automated identity validation and extraction are not implemented; these details do not block the first price pipeline.

## Crucial test coverage - planned, not yet automated

Use synthetic fixtures; the checklist below replaces the long walkthrough examples.

| Area | Essential expected outcomes |
|---|---|
| Configuration | AAPL/MSFT load correctly; malformed/ambiguous identifiers fail clearly; a third compatible fixture stock uses unchanged pipeline logic. |
| Prices | Valid OHLC passes; close above high, zero volume, or same-day partial bar fails; duplicates/replay leave one current row. |
| Numeric precision | Exact trailing-zero values pass; rounding, overflow, booleans, numeric strings, and nonfinite values fail. |
| News | Missing optional text keeps metadata; older revisions cannot replace newer ones; removed tags/text do not survive from prior versions. |
| News conflicts | Same selected timestamp with differing content fails publication; identical repeats retain deterministic provenance. |
| Company facts | Negative income and instant assets pass; missing duration start fails; distinct filings stay separate; same-response conflicts fail publication. |
| SEC snapshots | Newest complete response wins; no gap-filling or older-replay overwrite; ambiguous ties fail; unavailable historical snapshots are explicit. |
| Filing text | Wrong/ambiguous identity is rejected; representative section extraction must match actual section bodies, not table-of-contents entries. |
| Pipeline | Check completeness/freshness separately; refresh-level failures preserve prior output without labelling it fresh. |

## Source checks already completed

Run the local diagnostics from the repository root with the dependencies/private settings in [README.md](README.md), using `python scripts/<script-name>`. These are bounded access/inspection checks, not automated contract tests or Databricks ingestion.

| Diagnostic script | Verified result and boundary |
|---|---|
| `check_alpaca_access.py` | HTTP 200; one SIP/split/USD daily bar each for AAPL/MSFT on 2026-08-27, no further page. Not real-time or Databricks access. |
| `check_alpaca_news_access.py` | HTTP 200; three articles with text and more pages available. First page only; no complete coverage or reuse permission established. |
| `check_sec_access.py` | HTTP 200; AAPL CIK `0000320193`, MSFT CIK `0000789019`. Directory lookup only. |
| `check_sec_company_facts_access.py` | HTTP 200 and matching CIKs for both; three selected USD concepts and 12 response-order observations inspected, not latest/comparable metric selection. |
| `check_sec_filings_access.py` | HTTP 200 and matching CIKs for both; recent annual-filing metadata inspected, not full history. |
| `check_sec_filing_document_access.py` | One AAPL 2025 10-K retrieved as nonempty HTML; identity/context values manually reviewed. No automated identity validation or extraction. |

Sample dates, counts, and response order are observations, not production schedules, fixed thresholds, or latest-version rules. SEC diagnostics use an identifying private User-Agent and sequential requests; ingestion must respect [SEC access requirements](https://www.sec.gov/about/developer-resources) and provider rate limits. Credentials and raw responses were not persisted by these checks.
