# Data Contracts

The essential rules for the MVP's four datasets.

**Status:** All four Bronze MVP ingestion datasets—prices, news, SEC company facts, and selected SEC filings—are implemented and live-verified in Databricks. Three Silver datasets—`daily_prices`, `news_articles`, and `company_facts`—are also implemented and live-verified with deterministic safe-rerun behavior. Their Silver rules are defined below; `filing_sections` is the remaining Silver MVP dataset and its contract is finalized below immediately before implementation. Progress is tracked in [PLAN.md](PLAN.md).

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

### Bronze response envelope

The managed Delta table `<data catalog>.<deployed Bronze schema>.price_responses` stores one successful API response page per row. Development mode prefixes the schema for user isolation. Raw payloads remain private and credentials are never stored.

| Field | Type / meaning |
|---|---|
| source_response_id | Unique string for this received page |
| source_system, source_endpoint | `alpaca` and the fixed bars endpoint |
| request_parameters_json, request_page_token | Non-secret request settings and page token |
| response_next_page_token, page_number | Pagination provenance |
| http_status | Successful HTTP status retained with the response |
| response_payload_json, response_bytes, response_sha256 | Original UTF-8 JSON plus size and content hash |
| records_received | Number of configured-symbol bars in the page |
| fetched_at, ingestion_run_id | UTC receipt time and shared execution identifier |

The table is append-only retrieval history. Repeated runs produce new response records; later Silver logic applies business-key deduplication and replay rules.

### Silver schema

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
- Silver preserves the selected Bronze provenance: `source_response_id`, original `fetched_at`, and original `ingestion_run_id`. Transformation-run metadata is tracked separately and does not replace source provenance.
- For the MVP, rebuild the current `daily_prices` snapshot deterministically from stored Bronze history and publish it atomically. A malformed response envelope or unresolved same-time conflict fails publication and preserves the previous successful Silver snapshot.
- For candidates with the same business key and original `fetched_at`, identical normalized business fields are duplicates; select the lexicographically smallest `source_response_id` only as a deterministic provenance tiebreaker. Different normalized business fields at the same timestamp are an unresolved conflict and must fail publication.
- Bars for symbols outside the configured universe are out of scope rather than invalid. Invalid in-scope bars are excluded with recorded rule reasons. Track accepted, rejected, out-of-scope, and duplicate counts for each transformation run.

## 2. Company news

**Use:** Dated, cited company context—not proof that news caused a price movement. **Source:** Alpaca News API.

**One record:** One provider article, even when tagged with multiple stocks. **Key:** `(source_system, article_id)`.

### Schema

Shared provenance is required (`source_system = alpaca`). All fields below are required unless marked optional.

| Field | Source / meaning | Type |
|---|---|---|
| article_id | `id`; positive integer, not boolean/string | BIGINT |
| headline | `headline` | String |
| symbols | Full provider `symbols` list | Array of strings |
| article_created_at | `created_at` | UTC timestamp |
| article_updated_at | `updated_at` | UTC timestamp |
| article_source | `source`; publisher, not API provider | String |
| url | `url`; citation link | String |
| summary, content | Corresponding provider fields; content may contain HTML | Optional strings |
| configured_symbols | Selected article tags intersected with the current configured universe; deterministic unique list | Array of strings |
| source_response_id | Bronze response page from which the selected observation came | String |
| fetched_at | Original Bronze retrieval timestamp for the selected observation | UTC timestamp |
| ingestion_run_id | Original Bronze ingestion run for the selected observation | String |

### Acceptance and version selection

- Each symbol tag must be a nonblank string. Empty arrays, repeated tags, and other tickers are valid; the publisher is not restricted to the observed Benzinga sample.
- Require `article_created_at <= article_updated_at <= fetched_at`, with no clock-skew allowance. Citation URLs must be absolute HTTP(S), have a hostname, and contain no username/password; this does not establish safety or reachability.
- Among valid observations in stored Bronze history for the same `(source_system, article_id)`, select the greatest `article_updated_at` before filtering for configured stocks. The MVP rebuilds the current `news_articles` snapshot from Bronze rather than using the previous Silver snapshot as version-selection input. Replace all article fields together; never borrow missing text or tags from an older revision.
- At the selected `(source_system, article_id, article_updated_at)`, observations with identical normalized core source fields are repeats. Compare symbol tags as sets for content equality and exclude retrieval provenance from that comparison. Select the earliest `fetched_at`; break remaining ties by lexicographically smallest `ingestion_run_id`, then lexicographically smallest `source_response_id`.
- If observations at the selected update timestamp contain different normalized core source fields, the article has an unresolved current-version conflict. Fail the whole Silver refresh before publication and preserve the previous successful snapshot. Final business-key uniqueness failures do the same. Conflicting observations that belong only to a strictly older, superseded update timestamp do not override a newer unambiguous selected revision.
- Derive `configured_symbols` only after selecting the current article version by intersecting its complete provider tag set with the current equities configuration. The intersection is deterministic and unique. A selected valid article with no configured-symbol overlap is out of scope rather than invalid and is excluded from the published `news_articles` snapshot. Full provider tags remain preserved and never expand the configured universe.
- Preserve the selected Bronze provenance (`source_response_id`, original `fetched_at`, and `ingestion_run_id`) on each published Silver row. Transformation-run metadata is separate from source provenance.
- Rebuild the MVP `news_articles` snapshot deterministically from stored Bronze history and publish it only after article validation, current-version conflict detection, scope classification, and final key-uniqueness validation succeed. Malformed Bronze response structure or an unresolved selected-version conflict fails publication before replacing the previous successful snapshot.
- Track accepted candidate, rejected, out-of-scope, duplicate, superseded-version, and selected counts for each transformation run. Rejected in-scope observations retain rule reasons and Bronze provenance without copying full article text into operational diagnostics.

### Research text

Use cleaned content, or a cleaned summary explicitly labelled summary-only. If neither is usable, retain metadata but exclude the article from text retrieval; a headline is not a full article. Do not fetch citation URLs automatically to fill missing text.

Carry article identity, publisher, URL, article timestamps, retrieval provenance, and content/summary origin into retrieval documents. Invalidate outdated index entries when revisions or eligibility change. Factual claims require supporting citations. Real article bodies, payloads, and derived indexes must not be committed publicly; synthetic demo data remains the fallback while permissions are unresolved.

## 3. SEC company facts

**Use:** Reported business performance and financial position. **Source:** SEC EDGAR Company Facts; `source_system = sec`.

**One record:** One concept/unit/period reported in one filing. Different filings remain separate even when amounts match.

**Key:** `(source_system, cik, taxonomy, concept, unit, period_start, period_end, accession_number)`. Compare null period_start values as equal for instant facts.

### Transformation summary

`company_facts_responses`
→ select the latest complete Bronze response for each configured company by original `fetched_at`
→ validate response identity and configured CIK
→ extract only the configured `us-gaap` concepts in USD
→ validate individual observations
→ collapse exact duplicate business keys and fail conflicting duplicates
→ atomically publish the current `company_facts` snapshot.

Selection happens before individual fact validation. Silver never fills missing or invalid facts from an older Bronze response.

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
| project_symbol | Configured project symbol for convenient downstream joins; descriptive mapping, not the authoritative company identifier | String |
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
| source_response_id | Selected Bronze company-facts response | String |
| fetched_at | Original retrieval time of the selected Bronze response | UTC timestamp |
| ingestion_run_id | Original Bronze ingestion run | String |

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

## 4. SEC selected filing text

**Use:** Company-reported Business (Item 1) and Risk Factors (Item 1A) evidence from annual Form 10-K filings. Quarterly/current-event reports and comprehensive filing coverage are outside the initial scope.

### MVP filing selection

For each configured company, consider only SEC filing metadata whose form is exactly `10-K` and select the candidate with the greatest `filingDate`. The selected candidate must have nonblank accessionNumber, filingDate, reportDate, and primaryDocument metadata. If multiple distinct eligible filings share the greatest filingDate, treat the selection as ambiguous and fail that company's retrieval rather than choosing by response order.

- `10-K/A` amendments are outside the initial MVP selection rule.
- Selection is based on SEC filing metadata, not document ordering or filenames.
- The selected filing must match the configured 10-digit CIK.
- Missing or ambiguous eligible filings fail that company's retrieval rather than silently selecting another form.
- Adding historical filings or amendment-aware version selection is a later extension.

### Bronze filing-document envelope

The managed Delta table `<data catalog>.<deployed Bronze schema>.filing_documents` stores one successfully retrieved selected SEC primary filing document per row.

| Field | Type / meaning |
|---|---|
| source_response_id | Unique string for this retrieved filing document |
| source_system | `sec` |
| source_endpoint | Fixed SEC filing-document source |
| project_symbol | Configured project symbol |
| sec_cik | Configured 10-digit SEC CIK |
| accession_number | Selected filing accession number |
| filing_form | Selected form; initially exactly `10-K` |
| filing_date | SEC filing date |
| report_date | SEC reporting-period end |
| primary_document | SEC primary-document filename |
| source_url | SEC URL used to retrieve the primary document |
| filing_metadata_json | Selected non-secret SEC filing metadata preserved as JSON |
| request_parameters_json | Non-secret retrieval/selection settings |
| http_status | Successful HTTP status retained with the document |
| response_payload_html | Original retrieved HTML document |
| response_bytes | Size of the original response body |
| response_sha256 | SHA-256 hash of the original response body |
| fetched_at | UTC timestamp of successful receipt |
| ingestion_run_id | Shared execution identifier |

The table is append-only retrieval history. Repeated successful runs create new response records and never overwrite earlier filing snapshots.

Bronze validates retrieval success, configured CIK and selected filing metadata, and basic response integrity. It does not extract Item 1 or Item 1A, clean filing text, chunk content, interpret amendments, or decide research relevance. Those operations belong to Silver and the later retrieval layer.

### Silver `filing_sections`

**One Silver record:** One complete cleaned section of one selected filing.

**Key:** `(source_system, cik, accession_number, section_code)`, where `source_system = sec` and the initial project section codes are `item_1` and `item_1a`.

#### Current filing and retrieval selection

For each configured company:

1. Consider only Bronze rows whose configured CIK matches and whose filing form is exactly `10-K`.
2. Select the greatest `filing_date`.
3. If multiple distinct accessions occur at that greatest filing date, fail the Silver refresh as ambiguous.
4. For the selected accession, select the retrieval with the greatest original `fetched_at`.
5. If multiple retrievals share that greatest timestamp, choose the lexicographically smallest `source_response_id` only when their raw HTML is identical; otherwise fail the refresh.

`response_sha256` describes one exact retrieval and is provenance, not filing identity. The same filing accession may therefore have different response hashes across retrievals.

Selection happens before section extraction and validation. Silver never falls back to an older filing or older retrieval because extraction from the selected response fails.

The current Bronze MVP ingests exact `10-K` filings only. `10-K/A` amendments are therefore outside the current Silver version policy; amendment-aware interpretation requires a later Bronze expansion and contract revision.

#### Schema

All fields are required unless marked optional.

| Field | Source / meaning | Type |
|---|---|---|
| source_system | `sec` | String |
| cik | Validated configured SEC CIK | 10-digit string |
| project_symbol | Configured project symbol | String |
| accession_number | Selected filing accession | String |
| filing_form | Selected filing form; initially exactly `10-K` | String |
| filing_date | SEC filing date | Date |
| report_date | Filing reporting-period end | Date |
| primary_document | SEC primary-document filename | String |
| source_url | SEC filing-document citation URL | String |
| section_code | Project section identity: `item_1` or `item_1a` | String |
| section_title | `Business` or `Risk Factors` | String |
| section_text | Cleaned complete section body | String |
| section_text_sha256 | SHA-256 of normalized `section_text` | String |
| source_response_id | Selected Bronze filing retrieval | String |
| response_sha256 | SHA-256 of the selected raw Bronze HTML retrieval | String |
| fetched_at | Original Bronze retrieval timestamp | UTC timestamp |
| ingestion_run_id | Original Bronze ingestion run | String |

#### Identity and extraction

- Validate the configured CIK, exact `10-K` form, accession format, filing/report dates, primary document, source URL, and selected Bronze provenance before extraction.
- Validate the filing's inline-XBRL DEI identity against the selected Bronze metadata: `EntityCentralIndexKey` must match the configured CIK, `DocumentType` must match the selected filing form, and `DocumentPeriodEndDate` must match `report_date`. Repeated identity facts are allowed only when their normalized values agree; conflicting values fail the refresh.
- Referenced XBRL contexts used for document identity must resolve consistently to the expected SEC CIK identifier scheme and reporting-period end. Unsupported or ambiguous identity/date representations fail validation rather than being guessed.
- Treat filing HTML as untrusted evidence. Parse text only; do not execute scripts or load linked resources.
- Remove non-content elements such as script/style content, decode HTML entities, and normalize whitespace without rewriting the filing's substantive wording.
- Heading recognition must tolerate inline-XBRL formatting and whitespace splits such as `b usiness` or `ris k factors`.
- A heading candidate must contain the expected item code and section title as a heading relationship, not merely mention another section in narrative text.
- Reject table-of-contents entries and narrative cross-references as section boundaries.
- `item_1` starts at the validated `Item 1 — Business` body heading and ends immediately before the validated `Item 1A — Risk Factors` body heading.
- `item_1a` starts at the validated `Item 1A — Risk Factors` body heading and ends immediately before the earliest valid subsequent body heading among Item 1B, Item 1C, and Item 2.
- Heading boundaries must be uniquely determined and correctly ordered. Missing or ambiguous boundaries fail the Silver refresh rather than guessing.
- After heading removal and whitespace normalization, each selected section must contain at least 500 characters of substantive text. Shorter extraction is treated as an extraction-quality failure, not published as a section.
- Store only Item 1 and Item 1A in the MVP `filing_sections` table. Other filing sections remain recoverable from Bronze.

#### Publication and replay

- Both required sections must be successfully extracted for every configured company before publication.
- Publish the complete current `filing_sections` snapshot atomically; a selection, identity, extraction, quality, or final uniqueness failure preserves the previous successful Silver table.
- Never combine Item 1 from one retrieval with Item 1A from another retrieval.
- Identical Bronze history must rebuild the same section text and section hashes without accumulating duplicate business keys.
- Preserve the selected Bronze retrieval provenance on every Silver section. Transformation-run metadata remains separate from source provenance.

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
