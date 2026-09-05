# Data Contracts

The essential data and AI retrieval contracts for the MVP.

**Status:** All four Bronze datasets, all four Silver datasets, and both Gold data products (`market_metrics` and `fundamental_metrics`) are implemented and live-verified in Databricks with deterministic safe-rerun behavior. The next data contract covers the Milestone 2 RAG retrieval assets. Progress is tracked in [PLAN.md](PLAN.md).

## Planned data flow and inventory

The MVP plans three Databricks schemas: Bronze for raw source history, Silver for validated business records, and Gold for application-oriented metrics. AI retrieval assets are built from Silver text; they are not another medallion layer.

| Source dataset | Bronze | Silver | Gold or AI consumption |
|---|---|---|---|
| Alpaca daily bars | `price_responses`: original response pages and retrieval metadata | `daily_prices`: one typed, validated daily bar per stock/session | `market_metrics`: comparable returns, volatility, drawdown, and trend measures |
| Alpaca company news | `news_responses`: original article versions and retrieval metadata | `news_articles`: one selected, validated version per article | `research_documents` -> `research_chunks` -> RAG vector index |
| SEC company facts | `company_facts_responses`: original company snapshots and retrieval metadata | `company_facts`: filing-level typed facts with periods and provenance | `fundamental_metrics`: selected comparable financial measures |
| SEC selected filings | `filing_documents`: filing metadata and original HTML | `filing_sections`: cleaned Item 1 and Item 1A sections with provenance | `research_documents` -> `research_chunks` -> RAG vector index |

This inventory contains four Bronze datasets, four Silver datasets, two Gold data products, two shared AI retrieval datasets (`research_documents` and `research_chunks`), and a later vector index built from the chunk dataset. It excludes configuration and operational audit/quarantine records. Physical identifiers and storage details are finalized immediately before implementing each layer.

Columns evolve by purpose: Bronze keeps the complete source payload plus provenance; Silver selects, renames, derives, types, validates, and deduplicates the fields defined below; Gold changes the grain again to provide reusable comparison measures; the RAG retrieval assets transform validated Silver text into citation-ready documents and deterministic chunks. Unused source fields remain recoverable from Bronze.

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


## 5. Gold market metrics

**Use:** Current cross-company market comparison from validated Silver
`daily_prices`. Returns are split-adjusted close-to-close price returns and
exclude dividend income.

**One Gold record:** One configured symbol at one common current market
`as_of_date`.

**Key:** `(symbol, as_of_date)` within the fixed Alpaca SIP / split-adjusted /
1Day / USD dataset.

The MVP publishes a current snapshot rather than a historical metric series.
There must be exactly one row per configured symbol and every published row
must share the same `as_of_date`.

### Common as-of date and coverage

1. Use only validated Silver rows with `source_system = alpaca`, `feed = sip`,
   `adjustment = split`, `timeframe = 1Day`, and `currency = USD`.
2. Determine the greatest `trading_date` available for each configured symbol.
   Every configured symbol must have the same greatest date. A stale or
   mismatched symbol fails the refresh rather than causing Gold to silently
   fall back to an older common date.
3. That shared greatest trading date is `as_of_date`. Preserve its source
   `bar_timestamp` as `as_of_bar_timestamp`.
4. Lookback windows are counts of observed trading sessions, not calendar-day
   intervals.
5. Require at least 61 ordered closes per configured symbol through
   `as_of_date`. The last 61 trading dates must be identical across the
   configured universe. A missing or extra session in this comparison window
   fails publication.
6. The 61-close window supports 60 one-session returns and the 60-session
   return. The 20- and 5-session windows are deterministic suffixes of the
   same aligned history.
7. Gold does not publish partial rows or null metrics. Insufficient or
   misaligned coverage fails the complete refresh and preserves the previous
   successful Gold snapshot.

### Schema

| Field | Meaning | Type |
|---|---|---|
| source_system | `alpaca` | String |
| symbol | Configured project symbol | String |
| as_of_date | Shared latest completed trading date in America/New_York | Date |
| as_of_bar_timestamp | Silver timestamp of the as-of daily bar | UTC timestamp |
| close | Exact as-of Silver close | DECIMAL(20,8) |
| window_start_date_60d | Trading date at `t-60`, the first close in the 61-close comparison window | Date |
| observations_available | Number of validated Silver daily bars available for the symbol through `as_of_date` | Integer |
| return_1d | One-session close-to-close return | DECIMAL(20,10) |
| return_5d | Five-session close-to-close return | DECIMAL(20,10) |
| return_20d | Twenty-session close-to-close return | DECIMAL(20,10) |
| return_60d | Sixty-session close-to-close return | DECIMAL(20,10) |
| annualized_volatility_20d | Annualized sample standard deviation of the last 20 one-session returns | DECIMAL(20,10) |
| annualized_volatility_60d | Annualized sample standard deviation of the last 60 one-session returns | DECIMAL(20,10) |
| current_drawdown_60d | As-of close relative to the maximum close in the 61-close window | DECIMAL(20,10) |
| max_drawdown_60d | Worst peak-to-subsequent-close drawdown inside the 61-close window | DECIMAL(20,10) |
| sma_20 | Arithmetic mean of the latest 20 closes | DECIMAL(28,10) |
| sma_60 | Arithmetic mean of the latest 60 closes | DECIMAL(28,10) |
| close_vs_sma_20 | `close / sma_20 - 1` | DECIMAL(20,10) |
| close_vs_sma_60 | `close / sma_60 - 1` | DECIMAL(20,10) |
| sma_20_vs_sma_60 | `sma_20 / sma_60 - 1` | DECIMAL(20,10) |
| feed | `sip` | String |
| adjustment | `split` | String |
| timeframe | `1Day` | String |
| currency | `USD` | String |
| latest_source_response_id | Silver provenance of the as-of bar | String |
| latest_source_fetched_at | Original Bronze retrieval time of the as-of bar | UTC timestamp |
| latest_source_ingestion_run_id | Original Bronze ingestion run of the as-of bar | String |

Rate fields are decimal fractions: for example, `0.0500000000` means 5%.

### Metric formulas

For close `C[t]` and trading-session offset `N`:

- `return_Nd = C[t] / C[t-N] - 1` for `N` in 1, 5, 20, and 60.
- One-session return `r[i] = C[i] / C[i-1] - 1`.
- `annualized_volatility_Nd = sample_stddev(last N r[i]) * sqrt(252)` for
  `N` in 20 and 60.
- `current_drawdown_60d = C[t] / max(C[t-60:t]) - 1`.
- `max_drawdown_60d` is the minimum value of
  `C[j] / running_max(C[t-60:j]) - 1` over the 61-close window.
- `sma_20` and `sma_60` are arithmetic means of the latest 20 and 60 closes.
- Relative trend measures use the ratios defined in the schema.

Calculations start from exact Silver decimal closes. Derived values are rounded
only once at publication to their declared scale using deterministic
round-half-even behavior. Missing values are never treated as zero.

### Validation, publication, and replay

- Validate configured-universe completeness, common `as_of_date`, aligned
  61-session date coverage, required source settings, positive closes, and
  final metric ranges before publication.
- Returns and trend ratios must be finite. Annualized volatility must be
  nonnegative. Drawdowns must lie in `[-1, 0]`.
- Final `(symbol, as_of_date)` keys must be unique and every configured symbol
  must appear exactly once.
- Rebuild the current Gold snapshot deterministically from the current
  validated Silver `daily_prices` snapshot; do not use an older Gold snapshot
  as calculation input.
- Publish the complete `market_metrics` snapshot atomically only after all
  companies and metrics pass validation. A failed refresh preserves the
  previous successful Gold table.
- Preserve the as-of Silver bar's original Bronze provenance. Gold
  transformation-run metadata remains separate from source provenance.


## 6. Gold fundamental metrics

**Use:** Current cross-company fundamental comparison from validated Silver
`company_facts`.

**One Gold record:** One configured company using its latest eligible SEC
financial filing and the current Silver company-facts snapshot.

**Key:** `(symbol, as_of_date)`, where `as_of_date` is the filing date of the
selected latest eligible filing.

The MVP publishes one current snapshot rather than a historical metric series.
There must be exactly one row per configured company. Fundamental `as_of_date`
and reporting-period ends do not need to match across companies because SEC
filing calendars differ. Comparability is provided by trailing-twelve-month
construction and explicit period metadata.

### Source scope and latest filing

1. Use only validated Silver facts with `source_system = sec`,
   `taxonomy = us-gaap`, `unit = USD`, and the configured company identity.
2. Gold uses only these concepts:
   `RevenueFromContractWithCustomerExcludingAssessedTax`,
   `NetIncomeLoss`, and `Assets`.
3. Only exact `10-K` and `10-Q` filings are eligible for the current reporting
   filing. `8-K`, `10-K/A`, `10-Q/A`, and other forms are outside the MVP Gold
   selection rule.
4. Select the eligible filing with the greatest `filing_date` for each company.
   Multiple distinct accessions at that greatest date are ambiguous and fail
   publication.
5. The selected latest filing must provide the current-period revenue,
   net-income, and asset facts required by the rules below. Gold does not fall
   back to an older filing when the selected filing is incomplete.
6. All facts are read from the current Silver company-facts snapshot. Preserve
   the selected Silver snapshot's Bronze response provenance on the Gold row.

### Full-year fact version selection

For annual calculations, use exact `10-K` duration facts whose observed
duration is between 330 and 380 days.

For the same concept and actual `(period_start, period_end)`, prefer the
disclosure with the greatest `filing_date`. If multiple disclosures at that
greatest filing date disagree in value or period identity, fail rather than
choosing by input order.

Revenue and net-income annual periods used together must have identical
`period_start` and `period_end`.

### Current TTM construction

The selected latest filing determines one `fundamental_period_end`.

#### Latest filing is a 10-K

- Require current full-year revenue and net income ending on
  `fundamental_period_end`.
- `revenue_ttm` equals that full-year revenue.
- `net_income_ttm` equals that full-year net income.
- `ttm_derivation_method = annual`.

#### Latest filing is a 10-Q

- For revenue and net income, select the longest duration fact in the selected
  accession ending on `fundamental_period_end`. This is the current fiscal-YTD
  period. Revenue and net income must use the same YTD start and end dates.
- Select the comparative prior-year YTD facts disclosed in the same accession.
  Their duration must differ from the current YTD duration by no more than two
  days, and their period end must be 350 to 380 days before the current YTD
  period end.
- Select the latest-version full-year `10-K` facts whose `period_end` is exactly
  one day before the current YTD `period_start`.
- Derive:
  `TTM = latest_full_year + current_YTD - prior_year_comparable_YTD`.
- Apply the formula independently to revenue and net income.
- `ttm_derivation_method = annual_plus_ytd_minus_prior_ytd`.

Gold never sums quarterly disclosures to construct TTM when the deterministic
annual-plus-YTD bridge is available.

### Latest assets

Select the `Assets` instant fact from the selected latest filing whose
`period_end = fundamental_period_end`.

The fact must have no `period_start` and must be nonnegative. Gold does not
substitute a prior-quarter or prior-year asset value if the selected filing's
current asset fact is unavailable.

### Growth and profitability metrics

- `net_margin_ttm = net_income_ttm / revenue_ttm`.
- Revenue TTM must be positive.
- Select the latest and immediately preceding comparable full-year revenue
  facts after the annual version-selection rule.
- `revenue_growth_latest_fy =
  latest_fy_revenue / prior_fy_revenue - 1`.
- Prior full-year revenue must be positive.
- Select matching latest and immediately preceding full-year net-income facts.
- `net_income_change_latest_fy =
  latest_fy_net_income - prior_fy_net_income`.

The MVP intentionally uses an absolute net-income change rather than a
percentage growth rate because a zero or negative prior-year net income makes
percentage growth undefined or economically misleading.

### Schema

| Field | Meaning | Type |
|---|---|---|
| source_system | `sec` | String |
| symbol | Configured project symbol | String |
| cik | Validated configured SEC CIK | 10-digit string |
| as_of_date | Filing date of selected latest eligible filing | Date |
| fundamental_period_end | Current reporting-period end used by TTM and assets | Date |
| latest_filing_form | Selected `10-K` or `10-Q` | String |
| latest_accession_number | Selected current filing accession | String |
| revenue_ttm | Current trailing-twelve-month revenue | DECIMAL(30,8) |
| net_income_ttm | Current trailing-twelve-month net income | DECIMAL(30,8) |
| net_margin_ttm | `net_income_ttm / revenue_ttm` | DECIMAL(20,10) |
| assets_latest | Assets at `fundamental_period_end` | DECIMAL(30,8) |
| revenue_growth_latest_fy | Latest full-year revenue growth versus preceding full year | DECIMAL(20,10) |
| net_income_change_latest_fy | Latest full-year net income minus preceding full-year net income | DECIMAL(30,8) |
| latest_fy_end | Period end of latest full-year comparison basis | Date |
| prior_fy_end | Period end of preceding full-year comparison basis | Date |
| ttm_derivation_method | `annual` or `annual_plus_ytd_minus_prior_ytd` | String |
| latest_source_response_id | Bronze company-facts response underlying current Silver snapshot | String |
| latest_source_fetched_at | Original Bronze retrieval timestamp | UTC timestamp |
| latest_source_ingestion_run_id | Original Bronze ingestion run | String |

Rate fields are decimal fractions. Calculations start from exact Silver
decimal values and round derived rates only once at publication using
round-half-even behavior.

### Validation, publication, and replay

- Require every configured company exactly once.
- Require one unambiguous latest eligible filing per company.
- Require aligned revenue/net-income periods for every annual and YTD pair.
- Require the selected latest filing's current assets, revenue, and net income.
- Require all TTM bridge components when the latest filing is a `10-Q`.
- Require two comparable full-year periods for annual growth/change metrics.
- Require finite derived rates, positive TTM revenue, and nonnegative assets.
- Final `(symbol, as_of_date)` keys must be unique.
- Publish the complete `fundamental_metrics` snapshot atomically only after all
  configured companies pass validation.
- A failed refresh preserves the previous successful Gold snapshot.
- Identical Silver input must rebuild identical Gold output without duplicate
  accumulation or metric drift.


## 7. AI retrieval documents and chunks

**Use:** Retrieval-Augmented Generation (RAG) over validated company news and
SEC filing evidence.

These datasets are AI retrieval assets derived from Silver text. They are not
an additional medallion layer and do not replace the structured Gold products.

The retrieval flow is:

```text
Silver news_articles + filing_sections
        |
        v
research_documents
        |
        v
research_chunks
        |
        v
embeddings
        |
        v
vector index
        |
        v
controlled retrieval tool
        |
        v
Company Researcher
```

Structured numerical analysis continues to use controlled Gold-data tools.
The retrieval datasets exist for unstructured narrative evidence.

### 7.1 Why documents and chunks are separate

`research_documents` represents the current validated source document and its
source-level identity, version, cleaned text, citation metadata, and
provenance.

`research_chunks` represents the bounded retrieval units deterministically
derived from one exact document version.

The separation is intentional:

- Source-document identity remains independent of chunking parameters.
- Article or filing version changes can invalidate all child chunks cleanly.
- Chunking can be changed and re-evaluated without redefining source identity.
- One news article tagged to multiple configured companies is stored once
  rather than duplicated once per symbol.
- Citation lineage remains explicit from chunk to document to Silver and
  ultimately Bronze provenance.
- Document preparation can be tested independently from retrieval behavior.
- Vector indexes can be rebuilt from chunks without rebuilding unchanged source
  documents.
- A new chunking strategy can create new chunk identities while preserving the
  same document identity and document version.

The two datasets therefore separate two concerns:

```text
research_documents
    source identity + source version + citation lineage

research_chunks
    retrieval boundaries + retrieval identity + index metadata
```

### 7.2 `research_documents`

**One record:** One active retrieval-eligible source document version.

For news, one provider article is one document even when it has more than one
configured symbol.

For SEC filings, one validated filing section is one document. Item 1 and
Item 1A are separate documents because they are distinct evidence and citation
units.

The MVP publishes a current retrieval-document snapshot rather than an
append-only retrieval history. Superseded source versions remain recoverable
through existing Bronze/Silver lineage but must not remain active in current
RAG retrieval.

#### Document identity

`document_id` is stable across retrievals of the same logical source document.

Initial identities are:

```text
News:
alpaca:news:<article_id>

Filing:
sec:filing:<accession_number>:<section_code>
```

`document_version_id` identifies the exact retrieval-visible version of that
logical document.

The version identifier is a deterministic SHA-256 derived from canonical
source-version and citation fields, the cleaning strategy version, and
`document_text_sha256`. It does not include retrieval-only provenance such as
`source_response_id`, `source_fetched_at`, or
`source_ingestion_run_id`.

This distinction is important:

```text
same source content + later identical retrieval
    -> same document_version_id

changed article revision, citation metadata, configured-symbol scope,
cleaning rules, or cleaned source text
    -> new document_version_id

same document version + different Bronze retrieval provenance
    -> same document_version_id, selected provenance may differ
```

The canonical version fields are source-specific.

For news they include:

- `document_id`;
- sorted configured symbols;
- headline;
- text origin;
- cleaning strategy version;
- cleaned text hash;
- citation URL;
- article creation timestamp;
- article update timestamp;
- publisher.

For filing sections they include:

- `document_id`;
- configured symbol;
- filing form;
- filing date;
- report date;
- section code;
- section title;
- cleaning strategy version;
- cleaned section-text hash;
- citation URL.

Canonical serialization and hashing rules must be fixed in code and covered by
offline tests.

#### Schema

| Field | Meaning | Type |
|---|---|---|
| document_id | Stable logical source-document identity | String |
| document_version_id | SHA-256 identity of the current retrieval-visible document version | String |
| cleaning_strategy_version | Version of deterministic retrieval-text cleaning rules | String |
| source_type | `news` or `filing` | String |
| source_system | `alpaca` or `sec` | String |
| configured_symbols | Deterministic sorted unique configured-symbol set | Array of strings |
| title | News headline or deterministic filing-section title | String |
| document_text | Cleaned canonical retrieval text | String |
| document_text_sha256 | SHA-256 of exact UTF-8 `document_text` | String |
| text_origin | `content`, `summary`, or `filing_section` | String |
| evidence_date | Primary source date used for filtering and report context | Date |
| source_url | Original citation URL from Silver | String |
| article_id | Alpaca article identity; null for filings | Optional BIGINT |
| article_source | News publisher; null for filings | Optional string |
| article_created_at | Original news creation timestamp; null for filings | Optional UTC timestamp |
| article_updated_at | Selected news version timestamp; null for filings | Optional UTC timestamp |
| cik | SEC company CIK; null for news | Optional string |
| accession_number | SEC filing accession; null for news | Optional string |
| filing_form | Filing form; null for news | Optional string |
| filing_date | SEC filing date; null for news | Optional date |
| report_date | SEC reporting-period end; null for news | Optional date |
| section_code | Filing section identity; null for news | Optional string |
| section_title | Filing section title; null for news | Optional string |
| source_response_id | Selected Silver row's Bronze response provenance | String |
| source_fetched_at | Original Bronze retrieval timestamp | UTC timestamp |
| source_ingestion_run_id | Original Bronze ingestion run | String |

`configured_symbols` is always nonempty. It is sorted and unique so the same
logical scope has one deterministic representation.

#### News mapping

For one selected Silver `news_articles` row:

```text
source_type             = news
source_system           = alpaca
document_id             = alpaca:news:<article_id>
configured_symbols      = Silver configured_symbols
title                   = headline
source_url              = url
article_id              = article_id
article_source          = article_source
article_created_at      = article_created_at
article_updated_at      = article_updated_at
evidence_date           = UTC date of article_created_at
```

Research-text selection is deterministic:

1. Clean `content`.
2. If cleaned content is usable, use it with `text_origin = content`.
3. Otherwise clean `summary`.
4. If the cleaned summary is usable, use it with
   `text_origin = summary`.
5. If neither is usable, exclude the article from retrieval.
6. A headline alone is metadata and is never treated as full article text.
7. Do not fetch the article URL to fill missing source text.

A news article tagged to both AAPL and MSFT remains one document with:

```text
configured_symbols = ["AAPL", "MSFT"]
```

The system must not create duplicate AAPL and MSFT copies of identical text.

#### Filing mapping

For one selected Silver `filing_sections` row:

```text
source_type             = filing
source_system           = sec
document_id             = sec:filing:<accession_number>:<section_code>
configured_symbols      = [project_symbol]
document_text           = section_text
text_origin             = filing_section
source_url              = source_url
cik                     = cik
accession_number        = accession_number
filing_form             = filing_form
filing_date             = filing_date
report_date             = report_date
section_code            = section_code
section_title           = section_title
evidence_date           = filing_date
```

The filing title is deterministic and combines filing and section context, for
example:

```text
10-K - Risk Factors
```

The RAG layer does not re-extract filing sections from Bronze HTML. It consumes
only the already validated Silver `section_text`.

### 7.3 Deterministic research-text cleaning

Cleaning prepares source text for retrieval without rewriting its substantive
meaning.

The same input and cleaning strategy version must always produce the same
output.

For news text:

- treat HTML as untrusted source data;
- extract text only;
- remove script, style, and other non-content executable elements;
- decode HTML entities;
- normalize line endings and whitespace deterministically;
- preserve substantive wording and ordering;
- do not execute scripts or load linked resources;
- do not follow instructions embedded in source text.

For filing text:

- start from validated Silver `section_text`;
- do not re-run SEC section extraction;
- apply only deterministic retrieval-level normalization required by the
  shared document format;
- do not summarize, paraphrase, or rewrite source text.

`document_text_sha256` is computed only after deterministic cleaning.

Any cleaning-rule change that can alter `document_text` requires a new
`cleaning_strategy_version`.

### 7.4 `research_chunks`

**One record:** One deterministic retrieval chunk from one exact
`document_version_id` under one chunking strategy version.

**Key:** `chunk_id`.

The following combination must also be unique:

```text
(document_version_id, chunking_strategy_version, chunk_index)
```

#### Schema

| Field | Meaning | Type |
|---|---|---|
| chunk_id | Deterministic SHA-256 identity of this exact chunk derivation | String |
| document_id | Parent logical document identity | String |
| document_version_id | Parent document version identity | String |
| chunking_strategy_version | Version of chunking rules and parameters | String |
| source_type | `news` or `filing` copied for retrieval filtering | String |
| source_system | `alpaca` or `sec` | String |
| configured_symbols | Parent configured-symbol scope | Array of strings |
| title | Parent document title for retrieval context | String |
| evidence_date | Parent evidence date for date filtering | Date |
| source_url | Parent citation URL | String |
| section_code | Filing section code when applicable; otherwise null | Optional string |
| section_title | Filing section title when applicable; otherwise null | Optional string |
| chunk_index | Zero-based chunk position within the parent version | Integer |
| character_start | Zero-based start offset in `document_text` | Integer |
| character_end | Exclusive end offset in `document_text` | Integer |
| chunk_text | Exact normalized source-text slice for this chunk | String |
| chunk_text_sha256 | SHA-256 of exact UTF-8 `chunk_text` | String |
| source_response_id | Parent selected Bronze response provenance | String |
| source_fetched_at | Parent original Bronze retrieval timestamp | UTC timestamp |
| source_ingestion_run_id | Parent original Bronze ingestion run | String |

Canonical source metadata remains in `research_documents`. The chunk table
copies only metadata needed for filtering, retrieval, citation display, and
lineage without requiring a document join for every vector-search result.

### 7.5 Chunking strategy and rationale

The MVP chunking strategy is deterministic and structure-aware.

Its purpose is to produce retrieval units that are small enough for specific
semantic retrieval while retaining enough surrounding context to support a
claim.

Whole long filing sections are poor retrieval units because unrelated topics
can dilute embedding similarity. Extremely small fragments are also poor
retrieval units because they lose the context needed to interpret a claim.

The strategy therefore prefers meaningful text boundaries rather than
arbitrary cuts.

Boundary preference is:

preserved paragraph boundary, when available
        |
        v
sentence boundary
        |
        v
whitespace boundary
        |
        v
hard character boundary only when necessary

Paragraph structure is source-dependent. News cleaning may preserve meaningful
paragraph boundaries from source HTML, while the current validated SEC
filing_sections.section_text is already whitespace-normalized and therefore
cannot be assumed to retain original paragraph breaks.```

The implementation must:

1. operate on the exact normalized `document_text`;
2. preserve original source order;
3. identify deterministic paragraph and sentence boundaries;
4. accumulate text units toward a configured target size;
5. enforce a configured maximum size;
6. split an individually oversized text unit deterministically at whitespace,
   falling back to a hard character boundary only when required;
7. optionally carry a bounded amount of trailing source context into the next
   chunk;
8. assign contiguous zero-based `chunk_index` values;
9. preserve exact half-open character offsets
   `[character_start, character_end)`;
10. require `chunk_text` to equal the corresponding source-text slice;
11. exclude empty or whitespace-only chunks;
12. compute a deterministic hash for every final chunk.

Overlap is allowed only as a deliberate configured strategy. It must be bounded
and deterministic. Overlap preserves exact source text rather than generating
rewritten context.

The exact initial target size, maximum size, and overlap are not guessed in
this contract. They will be selected after measuring the actual Silver news
and filing text-length distributions and considering the chosen embedding
model's input constraints.

Those values become part of `chunking_strategy_version` and must be covered by
offline tests.

This allows the project to evaluate chunking rather than presenting an
arbitrary chunk size as universally correct.

### 7.6 Chunk identity and chunking-version behavior

`chunk_id` changes whenever the retrieval unit itself changes.

It is derived deterministically from at least:

```text
document_version_id
chunking_strategy_version
chunk_index
character_start
character_end
chunk_text_sha256
```

Therefore:

```text
same document + same strategy + same boundaries + same text
    -> same chunk_id

same document + changed chunking parameters
    -> different chunk_id

changed source document version
    -> different child chunk_ids
```

A change to target size, maximum size, overlap, sentence-boundary logic, or any
other rule that can change chunk boundaries requires a new
`chunking_strategy_version`.

Changing chunking strategy does not change `document_id` or
`document_version_id` when the underlying retrieval-visible source document
has not changed.

### 7.7 Citation and provenance lineage

Every retrieval result must support this lineage:

```text
chunk_id
    |
    v
document_version_id
    |
    v
document_id
    |
    v
Silver source business identity
    |
    v
source_response_id
    |
    v
Bronze retrieval provenance
```

A retrieved chunk must therefore be sufficient to recover:

- configured company scope;
- source type;
- news article or filing identity;
- source date;
- title or filing-section context;
- citation URL;
- exact parent document version;
- original selected Bronze provenance.

The model may cite evidence only through citation identifiers produced from
controlled retrieval results. It must not invent source URLs, document IDs, or
chunk IDs.

### 7.8 Validation and publication

Before `research_documents` publication:

- all document IDs and document-version IDs must be valid and deterministic;
- every `document_id` must appear at most once in the current snapshot;
- every `document_version_id` must be unique;
- configured-symbol arrays must be nonempty, sorted, unique, and restricted to
  the configured project universe;
- required source-specific metadata must be present;
- text must be nonblank after cleaning;
- stored text hashes must match the exact stored text;
- citation URLs must come from validated Silver source rows;
- source provenance must match the selected Silver row.

Before `research_chunks` publication:

- every chunk must reference an existing current document version;
- chunk indexes must be contiguous from zero for each document version;
- offsets must be valid and ordered;
- `chunk_text` must equal the exact parent-text slice indicated by its offsets;
- chunk hashes and chunk IDs must recompute exactly;
- final chunk IDs must be unique;
- every substantive source-text region must remain represented by the chunk
  sequence, allowing only explicitly configured overlap.

Both datasets use deterministic full-snapshot rebuilding for the MVP and are
published only after complete validation succeeds.

A failed rebuild preserves the previous successful snapshot.

### 7.9 Replay and invalidation

Identical validated Silver input plus identical cleaning and chunking versions
must reproduce identical:

- document IDs;
- document-version IDs;
- document text and text hashes;
- chunk boundaries;
- chunk indexes;
- chunk text and hashes;
- chunk IDs.

When a current Silver news article is revised, becomes ineligible, or changes
configured-symbol scope, the next successful document snapshot replaces its
previous active RAG representation.

When a filing section changes, its document version changes and its previous
chunks are no longer active.

When a document disappears from the current eligible source snapshot, its
document and chunks disappear from the current retrieval snapshot.

The later vector-index synchronization must remove or invalidate entries whose
`chunk_id` is no longer present in the current successful
`research_chunks` snapshot.

### 7.10 Embedding boundary

`research_chunks` contains source text and retrieval metadata, not embedding
vectors.

Embedding generation is a separate model-processing step:

```text
research_chunks
        |
        v
versioned embedding input
        |
        v
embedding model
        |
        v
vector index
```

This keeps deterministic text preparation independently testable from
model-specific behavior.

The embedding model, embedding-input formatting, vector-index implementation,
similarity metric, retrieval depth, relevance threshold, and optional reranker
are separate implementation and evaluation decisions.

Title or other metadata may later be supplied to the embedding model as
versioned embedding context, but that must not modify canonical `chunk_text` or
its source offsets.

### 7.11 Processing, indexing, and public-data gate

Real provider text, derived chunks, embeddings, and vector indexes must follow
the permission gate defined in `docs/AI_RESEARCH_CONTRACT.md` and the shared
safe-use rules in this data contract.

Until the applicable storage, processing, indexing, model-use, and
redistribution permissions are confirmed:

- implement document and chunk transformations with synthetic controlled
  fixtures;
- run deterministic offline tests against synthetic text;
- do not commit real article bodies, filing bodies, derived chunks, embeddings,
  or indexes to the public repository;
- do not send real provider text to an external model or embedding provider;
- do not treat API access alone as permission for redistribution or external
  model processing.

Permission verification is an explicit gate before a live real-text embedding
or vector-index build.

### 7.12 Initial implementation gate

The document/chunk foundation is ready for embedding work when:

- both source mappings are implemented;
- one multi-symbol news article remains one document;
- content-to-summary fallback is deterministic;
- filing sections remain traceable to accession and section;
- document identity and versioning tests pass;
- cleaning is deterministic and versioned;
- chunking is deterministic and versioned;
- chunk offsets reproduce exact source text;
- citation and Bronze/Silver lineage are preserved;
- superseded chunks cannot remain active after a successful rebuild;
- synthetic prompt-injection text remains data rather than instructions;
- the full offline test suite remains green.

Passing this gate does not mean the RAG system is complete. It means the
retrieval corpus is deterministic, traceable, citation-ready, and safe to use
as input to the later embedding and vector-index stages.


## Crucial test coverage

Use deterministic synthetic fixtures where appropriate. Existing data-layer rules are covered by offline tests; the RAG rows define the next retrieval-layer test targets.

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
| Gold market metrics | Aligned 61-close history produces one row per configured symbol; insufficient history, stale/mismatched latest dates, or a missing comparison-window session fail; formulas and deterministic rounding match fixtures; replay produces identical output. |
| Gold fundamental metrics | Annual and annual-plus-YTD-minus-prior-YTD construction follows the contracted filing/period rules; missing bridge components, ambiguous filings, invalid assets/revenue, or mismatched periods fail; replay reproduces identical metrics. |
| RAG documents | News content-to-summary fallback is deterministic; one multi-symbol article remains one document; filing sections retain citation/provenance lineage; identical input reproduces identical document/version IDs. |
| RAG chunks | Deterministic boundaries, offsets, hashes, and IDs reproduce exactly; changed chunking strategy changes chunk IDs without changing unchanged document identity; prompt-like source text remains data only. |
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
