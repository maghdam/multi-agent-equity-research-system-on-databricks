# Data Contracts

## Daily stock prices — draft

### Purpose
Provide historical prices for comparing AAPL and MSFT.

### Scope
- Planned source: Alpaca historical stock bars.
- Symbols: AAPL and MSFT.
- Bar frequency: daily.

### Meaning of one record
One record describes one stock's trading session:
opening price, highest price, lowest price, closing price,
and traded volume, for a specified data feed and adjustment setting.

### Core field definitions

These are our planned normalized fields. Bronze will preserve the
original source payload; this table describes the parsed record.

| Project field | Source | Logical type | Required | Meaning |
|---|---|---|---|---|
| symbol | Symbol key in the bars response | String | Yes | Stock ticker: AAPL or MSFT |
| bar_timestamp | t | Timestamp in UTC | Yes | Start of the daily bar interval |
| trading_date | Derived from bar_timestamp | Date | Yes | Bar date in America/New_York |
| open | o | Decimal number | Yes | Opening price of the bar |
| high | h | Decimal number | Yes | Highest price of the bar |
| low | l | Decimal number | Yes | Lowest price of the bar |
| close | c | Decimal number | Yes | Closing price of the bar |
| volume | v | Decimal number | Yes | Traded share quantity for the chosen feed and adjustment setting |

- Prices will be requested in USD.
- Required means present and non-null in an accepted normalized record.
- These are logical types, not yet a Spark table definition.
- Silver numeric types and precision rules are defined under
  Silver numeric storage policy below.
- Additional source fields remain preserved in the raw payload.

### Feed and price-adjustment decisions

- Requested feed: `sip` — consolidated US equity market data.
- Adjustment: `split` — adjust historical prices and volumes
  for forward and reverse stock splits.
- Return interpretation: split-adjusted price returns,
  excluding dividend income.
- Include only completed trading days before the current
  date in America/New_York; exclude the current day's partial bar.
- Historical SIP sample access has been verified for our account;
  see Historical access verification below.
- Do not automatically switch to IEX if SIP access fails;
  review and document any feed change.

### Record identity and duplicate handling

#### Business key

Within the Alpaca daily-bar dataset in USD, a record is identified by:

(symbol, bar_timestamp, feed, adjustment)

Feed and adjustment come from the request settings and must accompany
the record. Prices and volume are values, not parts of the key.

#### Bronze policy

Preserve the original payload and retrieval history.
Separate fetches may contain the same business record.

#### Silver policy

Keep one accepted current record per business key.

- New key: insert the valid record.
- Same key and unchanged values: do not create another business row.
- Same key and changed values: use the more recently retrieved valid
  version, based on retrieval metadata defined in the next step.
- Reprocessing an older observation must not overwrite a newer one.
- If conflicting versions cannot be ordered reliably, flag them
  for review rather than choosing arbitrarily.

Reprocessing identical inputs must leave the Silver business
records unchanged.

### Ingestion metadata

Store these fields alongside Bronze payloads and carry them into
the parsed records. All fields below are required.

| Field | Logical type | Meaning |
|---|---|---|
| source_system | String | Data provider: `alpaca` |
| feed | String | Requested market-data feed: `sip` |
| adjustment | String | Requested adjustment setting: `split` |
| timeframe | String | Requested bar interval: `1Day` |
| currency | String | Requested price currency: `USD` |
| fetched_at | Timestamp in UTC | When a successful API response was received |
| ingestion_run_id | String | Unique identifier generated for the ingestion execution |

Rules:

- All bars in the same API response share its fetched_at timestamp.
- All pages fetched during one ingestion execution share its
  ingestion_run_id.
- Preserve the original metadata when reprocessing stored Bronze data.
- Use fetched_at to order retrieved observations; it is not a
  provider-supplied correction timestamp.
- Neither fetched_at nor ingestion_run_id belongs in the business key.
- Never store API keys or authorization headers in this metadata.

### Validation rules

Apply these checks before accepting records into Silver.

1. Required fields:
   All required core fields and metadata must be present and non-null.
   Required strings must not be empty. Timestamps must parse correctly,
   and numeric values must be finite numbers.

2. Dataset scope:
   symbol must be AAPL or MSFT.
   source_system must be alpaca, feed sip, adjustment split,
   timeframe 1Day, and currency USD.

3. Positive values:
   open, high, low, close, and volume must all be greater than zero.

4. Price consistency:
   low <= high
   low <= open <= high
   low <= close <= high

5. Date consistency:
   trading_date must equal the date of bar_timestamp in America/New_York.
   It must be earlier than the date of fetched_at in America/New_York.

6. Uniqueness:
   After duplicate handling, Silver must contain at most one record
   per business key: (symbol, bar_timestamp, feed, adjustment).

Failure handling:
Retain invalid source records in Bronze. Exclude them from Silver
and record the failed rules with their ingestion_run_id for review.
If Silver uniqueness fails, fail the validation step.

These checks do not establish that all expected trading days were
received. Completeness and freshness require separate checks.

### Representative examples

These are synthetic examples, not actual market observations.

Valid baseline record:

- symbol: AAPL
- bar_timestamp: 2026-08-27T04:00:00Z
- trading_date: 2026-08-27
- open: 100; high: 105; low: 99; close: 103; volume: 1000
- source_system: alpaca; feed: sip; adjustment: split
- timeframe: 1Day; currency: USD
- fetched_at: 2026-08-28T10:00:00Z
- ingestion_run_id: example-run-001

For each case, start from the baseline and change only what is listed.

| Case | Change | Expected outcome |
|---|---|---|
| Valid record | No change | Pass record checks |
| Invalid closing price | close = 106 | Reject: rule 4 |
| Boundary closing price | close = 105 | Pass record checks |
| Zero volume | volume = 0 | Reject: rule 3 |
| Unsupported symbol | symbol = TSLA | Reject: rule 2 |
| Missing required value | close = null | Reject: rule 1 |
| Same-day observation | fetched_at = 2026-08-27T10:00:00Z | Reject: rule 5 |
| Duplicate input | Receive the baseline twice | Both pass record checks; retain one Silver business row |
| Duplicate Silver output | Two rows with the same business key remain after deduplication | Fail uniqueness validation: rule 6 |

These are documented expectations. Automated tests are not implemented yet.

### Historical access verification

- Script: `scripts/check_alpaca_access.py`
- Requested trading date: 2026-08-27, America/New_York.
- Symbols: AAPL and MSFT.
- Settings: timeframe `1Day`, feed `sip`, adjustment `split`,
  currency `USD`.
- Result: HTTP 200; one daily bar returned for each symbol.
- Pagination: `next_page_token` was null; no further pages.
- Scope: local historical-data access only. Databricks ingestion
  and real-time data access have not been verified.

### Silver numeric storage policy

- Fields: `open`, `high`, `low`, `close`, and `volume`.
- Storage type: `DECIMAL(20,8)` — up to 12 integer digits
  and 8 fractional digits.
- Keep volume decimal; integer-valued samples do not establish
  that all future values will be integers.
- This is our MVP storage policy, not an Alpaca precision guarantee.
- Parse source numeric values directly as decimals, without an
  intermediate conversion to binary floating-point.
- Validate exact representability before casting to the Silver type.
- If a value would overflow or require rounding, retain the original
  record in Bronze, exclude it from Silver, and record the failure.
- Do not silently round or truncate source values.

## Company news — draft

### Purpose

Provide dated, source-linked news context for researching
AAPL and MSFT.

News provides context; it does not by itself prove that an event
caused a stock-price movement.

### Scope

- Planned source: Alpaca News API, using HTTP requests.
- Research scope: articles whose selected current version contains
  at least one configured equity, initially AAPL or MSFT.
- Apply this research filter after validation and version selection.
  Do not discard a valid observed revision solely because it no
  longer contains a supported stock; process it so outdated
  research relationships can be removed.
- Preserve the full provider symbol list, even when other
  companies are also mentioned.
- There may be zero or many articles for a company on a given day.
- Local news sample access and non-empty content have been
  verified; see News access verification below for the limits.

### Meaning of one record

One business record represents one provider news article.

An article associated with both AAPL and MSFT remains one article,
not two independent articles.

Repeated retrievals and article updates will be handled through
the Bronze and Silver duplicate/version policies defined later.

### News access verification

- Script: `scripts/check_alpaca_news_access.py`
- Request window: 2026-08-24T00:00:00Z through
  2026-08-28T23:59:59Z.
- Requested symbols: AAPL and MSFT.
- Settings: limit 3, sort descending by updated date,
  include_content=true, exclude_contentless=false.
- Result: HTTP 200; three articles returned.
- Observed article IDs: 61503279, 61499522, 61495044.
- One article was tagged AAPL; two were tagged MSFT.
- Other provider symbol tags remained present.
- Observed article source: benzinga; API provider: Alpaca.
- All three articles returned non-empty headline, summary,
  and content strings.
- More pages were available. Only the first page was inspected.
- This verifies local sample access, not complete news coverage,
  content quality, or permission to redistribute article text.
- Content availability for every future article is not guaranteed.

### Core field definitions

These describe our normalized article records.
Bronze preserves the original API response.

| Project field | Source | Logical type | Required | Meaning |
|---|---|---|---|---|
| article_id | id | Integer | Yes | Provider's article identifier |
| headline | headline | String | Yes | Article headline |
| symbols | symbols | Array of strings | Yes | Full list of provider-associated tickers |
| article_created_at | created_at | UTC timestamp | Yes | Provider's article creation time |
| article_updated_at | updated_at | UTC timestamp | Yes | Provider's article update time |
| article_source | source | String | Yes | Originating news source, such as benzinga |
| url | url | String | Yes | Source link used for citations |
| summary | summary | String | No | Provider-supplied summary, when available |
| content | content | String | No | Provider-supplied article body; may contain HTML |

- Required means present and non-null for an accepted normalized
  record. These are our acceptance requirements, not guarantees
  about every API response.
- Required strings must also be non-empty.
- Missing summary or content alone does not invalidate the article's
  metadata. Eligibility for research retrieval will be defined later.
- Never invent missing text or assume the headline represents
  the full article.
- Article creation/update timestamps are different from our
  ingestion timestamp, which will be defined separately.
- article_source identifies the news origin; source_system will
  identify the API provider, alpaca.
- Additional fields, including author and images, remain preserved
  in Bronze even though they are outside this initial core schema.

### Article identity

The business key is:

(source_system, article_id)

- source_system is `alpaca`; article_id comes from the API's `id`.
- Including source_system keeps identifiers from different API
  providers separate.
- article_source, such as `benzinga`, identifies the originating
  publisher; it is not the same as source_system.
- Retrieving the same key again does not create a new business article.
- An updated article with the same key remains the same article.
  Version selection and duplicate handling are defined separately.
- Headlines, URLs, symbol lists, and timestamps are not part of
  the business key.
- Different article IDs remain separate records, even if their
  headlines match. Cross-article similarity detection is outside
  the MVP.

### Relationships to supported stocks

- The supported research universe is currently AAPL and MSFT.
- Preserve the complete provider `symbols` array.
- An article is eligible for MVP research when its symbols contain
  at least one supported stock.
- Its supported-stock relationships are the unique intersection
  of its provider symbols and our supported research universe.
- An article associated with both AAPL and MSFT remains one
  business article, available to research queries for either stock.
- Other symbol tags do not automatically expand our supported
  universe or establish complete data coverage for those stocks.
- Provider tags indicate an association, not guaranteed relevance
  to every research question.

Examples:

- Provider symbols [AAPL, MSFT]: one article associated with
  both supported stocks.
- Provider symbols [IREN, MSFT, NVDA]: preserve all three tags;
  the supported-stock relationship is MSFT only.
- Provider symbols [TSLA]: outside the current research scope.

These are logical relationship rules. Physical tables or views
will be defined during implementation.

### Ingestion metadata and timestamp meanings

Our ingestion process adds these fields to each retrieved article:

| Field | Logical type | Required | Meaning |
|---|---|---|---|
| source_system | String | Yes | API provider; fixed to `alpaca` |
| fetched_at | UTC timestamp | Yes | When our process received the successful API response |
| ingestion_run_id | String | Yes | Unique identifier for the ingestion execution |

- These fields are assigned by our pipeline, not copied from
  the article's publication metadata.
- Articles from the same response share the same fetched_at.
- All pages retrieved within one ingestion execution share
  the same ingestion_run_id. Each response has its own fetched_at.
- source_system participates in the article business key.
  fetched_at and ingestion_run_id do not.

Timestamp meanings:

- article_created_at: when the provider says the article was created.
- article_updated_at: when the provider says the article was updated.
- fetched_at: when our system retrieved this observation.
- Provider timestamps do not prove when our system had access
  to that article version.
- A later fetched_at does not, by itself, mean the article changed.

Replay and security:

- Store ingestion metadata alongside the original Bronze data.
- When reprocessing saved Bronze data, preserve its original
  fetched_at and ingestion_run_id.
- A new API retrieval receives new retrieval metadata, even
  when the returned article is unchanged.
- Track a later transformation execution separately; do not
  overwrite the original ingestion metadata.
- Never store API keys, secrets, or authentication headers
  in records or logs.

Article version selection and duplicate handling are defined
in the next section.

### Article updates and duplicate handling

Bronze preserves the original responses and retrieval history.
Silver keeps at most one current accepted article per business key:

(source_system, article_id)

Version selection:

- Among records that pass validation, select the greatest
  article_updated_at for each business key.
- Compare incoming records with the existing Silver version.
  An older revision must not overwrite a newer revision,
  even if the older revision was fetched later.
- Replace article fields together as one version. Do not fill
  missing text in a newer revision with text from an older one.

Identical repeats:

- Records with the same business key, article_updated_at, and
  source-derived core field values are duplicate observations.
- Exclude ingestion metadata from this content comparison.
  Compare symbols as a set, ignoring order and repeated tags;
  Bronze still preserves the original array.
- Collapse identical repeats to one Silver record.
- Retain metadata from the earliest fetched_at among identical
  observations. If tied, use the lexicographically smallest
  ingestion_run_id as a deterministic tie-breaker.

Conflicting observations:

- If observations at the selected article_updated_at contain
  different source-derived core field values, flag a conflict.
- Do not assume that a later fetched_at resolves the conflict.
- Preserve the observations in Bronze and log the business key
  and relevant ingestion run IDs.
- Fail the news Silver refresh before writing updates.
  Leave the previous successful Silver snapshot unchanged;
  do not report the failed refresh as successful or fresh.

Stock relationships and replay:

- Derive supported-stock relationships from the selected
  version's symbols, not the union of historical symbol tags.
- Remove relationships no longer present in the selected version.
- If no supported symbols remain, exclude the article from
  current research results.
- Processing the same saved Bronze inputs again must produce
  the same Silver result without adding duplicate articles.

  ### News validation rules

These are our project's acceptance rules, not guarantees about
every API response.

1. Required fields:
   All required core fields and ingestion metadata must be present,
   non-null, and have the defined logical types.
   Required strings must contain a non-whitespace character.

2. Identity and provider:
   article_id must be a positive integer, not a Boolean or string.
   source_system must equal `alpaca`.
   Do not restrict article_source to `benzinga`; that was only
   the publisher observed in our sample.

3. Symbol structure:
   symbols must be an array of non-empty, non-whitespace strings.
   An empty array is structurally valid.
   Other tickers, repeated tags, or a different tag order do not
   make an article invalid.

4. Timestamp consistency:
   Timestamps must include timezone information and be converted
   to UTC without guessing a missing timezone.
   Require:
   article_created_at <= article_updated_at <= fetched_at
   Unexpected ordering is a validation failure; do not alter
   timestamps to make the record pass.
   This is a strict MVP policy with no clock-skew allowance.

5. Citation URL:
   url must be an absolute HTTP or HTTPS URL with a hostname
   and without an embedded username or password.
   This validates structure only; it does not prove the link
   is reachable, trustworthy, or safe to fetch automatically.

6. Optional text:
   summary and content may be missing or null.
   Non-null values must be strings.
   Normalize missing, null, or whitespace-only values to null
   in Silver; preserve the original values in Bronze.
   Missing optional text does not invalidate article metadata.

7. Silver uniqueness:
   After version selection and duplicate handling, each business
   key must occur at most once.
   A uniqueness failure stops the news Silver refresh before
   publication, leaving the previous successful snapshot unchanged.

Failure handling:

- Retain rejected observations in Bronze and exclude them from
  Silver version-selection candidates.
- Record the failed rule, ingestion_run_id, and business key
  when available. Do not log credentials or full article text.

Research eligibility:

- Apply supported-stock filtering after version selection.
- An empty symbols array or no AAPL/MSFT overlap makes the
  selected version ineligible for current research, not malformed.
  This allows revisions to remove outdated stock relationships.
- Passing metadata validation does not establish usable research
  text, factual accuracy, freshness, or complete news coverage.
- Research-text eligibility and content-use boundaries are
  defined separately.

  ### Record-validation examples

This baseline is entirely synthetic. The URL is a placeholder;
no API call or actual news content is required.

```json
{
  "source_system": "alpaca",
  "article_id": 1001,
  "headline": "Synthetic company update",
  "symbols": ["AAPL", "MSFT"],
  "article_created_at": "2026-08-28T10:00:00Z",
  "article_updated_at": "2026-08-28T11:00:00Z",
  "article_source": "example_publisher",
  "url": "https://example.com/news/1001",
  "summary": "Synthetic summary for contract testing.",
  "content": "Synthetic article body for contract testing.",
  "fetched_at": "2026-08-28T12:00:00Z",
  "ingestion_run_id": "example-news-run-001"
}
```

Each example starts independently from the baseline.
Change only the indicated fields; do not accumulate changes.

| Change | Expected outcome |
|---|---|
| No change | Pass record validation; associated with both supported stocks |
| headline = "   " | Reject: rule 1, required string contains only whitespace |
| article_id = 0 | Reject: rule 2, identifier must be positive |
| symbols = ["AAPL", 42] | Reject: rule 3, every tag must be a string |
| article_updated_at = "2026-08-28T09:00:00Z" | Reject: rule 4, update precedes creation |
| article_updated_at = "2026-08-28T12:01:00Z" | Reject: rule 4, update is later than retrieval |
| url = "/news/1001" | Reject: rule 5, URL is not absolute |
| content = 42 | Reject: rule 6, optional text must be a string or null |
| summary = null and content = null | Pass metadata validation; usable research text is not established |
| symbols = ["TSLA"] | Pass record validation; outside the current research scope |
| symbols = [] | Pass record validation; no supported-stock relationships |

Passing these examples does not establish factual accuracy,
link availability, or research-text eligibility.

Silver uniqueness, duplicate observations, revisions, and replay
require separate multi-record examples.

These are documented expectations, not automated test results.

### Duplicate, revision, and replay examples

For cases 1–6, start independently with the synthetic baseline
already in Silver. Do not accumulate changes between cases.

The incoming observation is a copy of the baseline, with:

- fetched_at = "2026-08-28T13:00:00Z"
- ingestion_run_id = "example-news-run-002"

Apply any additional changes specified below.
The business key remains (alpaca, 1001).

1. Identical repeat
   Additional changes: none.
   Expected: one Silver article remains. Keep the baseline's
   fetched_at and ingestion_run_id because it is the earliest
   observation of this identical version.

2. Newer revision
   Set article_updated_at = "2026-08-28T12:30:00Z".
   Set headline = "Revised synthetic company update".
   Expected: replace the baseline with this revision, including
   its ingestion metadata. Silver still contains one article.

3. Older revision retrieved later
   Set article_updated_at = "2026-08-28T10:30:00Z".
   Expected: keep the baseline's 11:00 revision.
   The incoming observation's later fetched_at does not make
   its provider revision newer.

4. Conflicting observations
   Keep article_updated_at at the baseline's 11:00 timestamp,
   but set headline = "Conflicting synthetic headline".
   Expected: flag a conflict and fail the news Silver refresh
   before writing updates. Preserve both observations in Bronze
   and leave the previous Silver snapshot unchanged.

5. Supported-stock relationships removed
   Set article_updated_at = "2026-08-28T12:30:00Z".
   Set symbols = ["TSLA"].
   Expected: accept the newer metadata version, but remove its
   AAPL/MSFT relationships and exclude it from current research.
   Do not retain the older version's symbol associations.

6. Newer revision without optional text
   Set article_updated_at = "2026-08-28T12:30:00Z".
   Set summary = null and content = null.
   Expected: accept the newer metadata version with null text.
   Do not copy text from the previous revision.

7. Replay
   After completing case 2, process the same saved Bronze
   observations again, preserving their ingestion metadata.
   Expected: the Silver article and its metadata remain unchanged.
   No additional article is created.

8. Publication uniqueness check
   Suppose the proposed Silver result still contains two rows
   with business key (alpaca, 1001).
   Expected: fail validation rule 7 before publication and leave
   the previous successful snapshot unchanged.
   Duplicate input observations are allowed; duplicate business
   keys in the published Silver result are not.

These are documented expectations, not executed test results.

### Research-text eligibility and content-use boundaries

Text selection:

- Use the selected, validated article version and its current
  supported-stock relationships.
- Prefer readable plain text extracted from content.
- If content has no usable text, use a non-empty cleaned summary,
  explicitly identified as summary-only evidence.
- Record whether the retrieval document uses content or summary.
  This is derived document metadata, not a provider field.
- If neither supplies usable text, retain the article metadata
  but exclude it from text retrieval.
- Do not invent missing text, treat a headline as a full article,
  or reuse text from an older revision.
- Text availability alone does not establish factual accuracy
  or relevance to the user's question.

Safe processing and traceability:

- Extract plain text without executing HTML or loading embedded
  scripts, images, or other remote resources.
- Do not render raw provider HTML in the application.
- Treat article text as untrusted evidence, never as instructions
  to agents or tools.
- Do not automatically visit article URLs to obtain missing text.
- Preserve the article business key, source URL, publisher,
  article timestamps, and ingestion provenance with retrieval
  documents so evidence can be traced to the selected version.
- Generated factual claims must be supported by the cited evidence.
- Invalidate stale retrieval entries when an article revision or
  its research eligibility changes. Do not return outdated text
  merely because it remains in an index.

Permitted use:

- API access does not by itself establish permission for every
  storage, processing, or publication use.
- Confirm applicable account and provider terms before persistent
  storage, indexing, or sending article text to model providers.
  Document any retention restrictions.
- Separately confirm permitted public display and redistribution,
  including generated outputs; summaries are not an automatic
  workaround for usage restrictions.
- Do not commit real provider payloads, article bodies, or derived
  text indexes to the public repository. Use synthetic test data.
- Until public-use permissions are confirmed, use clearly labelled
  synthetic data for the public demonstration.
- These rules document our safeguards; they do not establish
  that the necessary permissions have already been obtained.


## SEC company facts — draft

### Purpose

Provide company-reported financial figures to support research
and comparisons alongside stock prices and news.

These figures describe business performance and financial position;
they are not stock-price predictions or analyst estimates.

### Scope

- Planned source: SEC EDGAR Company Facts API.
- Companies come from the planned shared equities configuration,
  initially AAPL and MSFT.
- The SEC identifies reporting entities using a Central Index Key
  (CIK). Resolve and verify the ticker-to-entity mapping before
  requesting company facts.
- Focus on selected company-wide financial metrics.
  Initial candidates are revenue, net income, and total assets.
- Confirm exact source concepts, units, and reporting periods
  after inspecting sample responses.
- Preserve the reporting-period and filing provenance needed
  to explain where each financial figure came from.
- Full filing narrative text is a separate dataset and will
  have its own contract.
- Local Company Facts API access and the presence of the three
  candidate concepts are verified for AAPL and MSFT, with USD
  observations. Suitability and reporting-period coverage still
  require validation.

### Directory access verification

- Script: `scripts/check_sec_access.py`.
- Source: https://www.sec.gov/files/company_tickers.json
- Execution: local `db` environment.
- Result: HTTP 200, confirmed from user-run output.

Returned directory mappings:

- AAPL: CIK `0000320193`, company `Apple Inc.`
- MSFT: CIK `0000789019`, company `MICROSOFT CORP`

This check verifies directory access and resolves the two
tickers to SEC identifiers. It does not retrieve financial facts.

At the directory-only checkpoint, company-facts API access
and company-level identity checks had not yet been tested.
The separate company-facts check below records the next result.

No SEC response payload or private User-Agent value was
saved by the script.

### Company-facts access verification

- Script: `scripts/check_sec_company_facts_access.py`.
- Execution: local `db` environment.
- Result: HTTP 200 for both companies, confirmed from user-run output.
- AAPL: entity name `Apple Inc.`, 503 US-GAAP concepts.
- MSFT: entity name `MICROSOFT CORPORATION`, 562 US-GAAP concepts.
- Both responses contain the `dei` and `us-gaap` taxonomies.
- Both returned CIKs match the previously recorded directory mappings.

Microsoft's directory name is `MICROSOFT CORP`; its company-facts
name is `MICROSOFT CORPORATION`. The matching CIK identifies the
same reporting entity despite this name-label difference.

Concept counts describe the observed responses. They are not
fixed validation thresholds or evidence that particular metrics
are suitable for comparison.

The initial access check did not validate financial values.
Candidate-concept metadata is recorded below. Reporting-period
and filing-provenance checks are required before final metric
selection.

The script printed metadata only and did not persist the
response payloads or deploy anything to Databricks.

### Candidate-concept metadata inspection

Evidence: user-run output from
`scripts/check_sec_company_facts_access.py`.
Both company requests returned HTTP 200.

All three candidates were present under `us-gaap`, with USD
observations:

- Revenue: `RevenueFromContractWithCustomerExcludingAssessedTax`
  Source label: `Revenue from Contract with Customer, Excluding Assessed Tax`.
  Observation counts: AAPL 117; MSFT 134.

- Net income: `NetIncomeLoss`
  Source label: `Net Income (Loss) Attributable to Parent`.
  Observation counts: AAPL 338; MSFT 340.

- Total assets: `Assets`
  Source label: `Assets`.
  Observation counts: AAPL 146; MSFT 142.

These counts are observed array lengths, not deduplicated
reporting-period counts or fixed validation thresholds.

This metadata-only check established candidate presence and units,
not coverage or comparability. The observation sample below
examines dates, values, and filing references. Full validation
and final selection rules remain pending.

### Observation sample findings

Evidence: user-run output from
`scripts/check_sec_company_facts_access.py`.
Both requests returned HTTP 200. Two observations per candidate
concept and company were inspected: 12 observations in total.

Findings:

- Revenue and net-income examples describe a duration, using
  `start` and `end`. Asset examples describe a snapshot at `end`,
  with no `start`. Missing start dates are therefore not
  automatically invalid for every concept.

- Filing labels do not determine an observation's period.
  Microsoft's revenue example covers 2016-07-02 to 2016-09-30,
  despite `fy: 2018`, `fp: FY`, and `form: 10-K`.
  Preserve actual dates; do not classify periods using those
  filing labels alone.

- The same period can have different reported values.
  Apple's net income for 2006-10-01 to 2007-09-29 appears as
  USD 3,496,000,000 in a 10-K and USD 3,495,000,000 in a 10-K/A.
  Preserve filing provenance and both observed versions until
  explicit selection rules are applied.

- Identical asset values also appear in different filings.
  Matching dates and values do not establish that two records
  have the same filing provenance. Do not sum repeated disclosures.

- `frame` is absent in some observations. The printed `<absent>`
  marker is produced by the diagnostic, not supplied by SEC.
  Do not store that marker as a financial value or treat it as zero.

Keep observation dates separate from filing dates, and retain
`accn`, `form`, and `filed` for traceability.

These are historical response-order examples, not latest-value
selections. Recent coverage, comparability, version selection,
and automated validation remain to be established.

### Meaning of one record

One logical record represents one numerical fact reported
by a company in a specific SEC filing.

It describes:

- One reporting company, identified by CIK.
- One taxonomy and concept, such as `us-gaap` and `NetIncomeLoss`.
- One measurement unit, such as USD.
- One financial period: `start` and `end` for a duration,
  or `end` alone for an instant.
- One filing, identified by its accession number (`accn`).

The reported value and supporting filing metadata belong
to that observation.

A complete Company Facts API response contains many such
observations; it is not one financial-fact record.

Different filings remain separate observations, even when
their concept, period, and value match.

For example, Apple's net income for 2006-10-01 to 2007-09-29
in the original 10-K and the 10-K/A represents two separate
filing-level observations.

Bronze will preserve raw responses and retrieval history.
Repeated API retrievals do not create new SEC filings.

The business key, duplicate/conflict handling, and retrieval
snapshot/replay rules are defined in the sections below.
Selecting comparable Gold metrics and their filing versions
remains separate work.

### Core field definitions

These are planned normalized fields. Bronze preserves the original
source payload. Required means present and non-null in an accepted
normalized record; this is our project policy, not an API guarantee.

#### Company and source identity

| Project field | Source | Logical type | Required | Meaning |
|---|---|---|---|---|
| cik | Top-level `cik` | String | Yes | Reporting company's SEC identifier, normalized to 10 digits with leading zeros. |
| taxonomy | Key under `facts` | String | Yes | Concept namespace, such as `us-gaap`. |
| concept | Key under `facts[taxonomy]` | String | Yes | Financial concept, such as `NetIncomeLoss`. |
| unit | Key under `facts[taxonomy][concept].units` | String | Yes | Measurement unit, such as `USD`. |
| accession_number | Observation's `accn` | String | Yes | Identifier of the filing containing the observation; preserve its hyphens. |

Validate CIK before formatting it. For example, source value
320193 becomes "0000320193"; never truncate an invalid identifier.

Preserve taxonomy, concept, and unit keys as supplied.
Interpret the concept together with its taxonomy.

An accession number identifies a filing, not an individual fact.
The complete key, including the financial period fields,
is defined under Record identity and within-response duplicates.

#### Financial value and period

| Project field | Source | Logical type | Required | Meaning |
|---|---|---|---|---|
| fact_value | Observation's `val` | Decimal | Yes | Reported numerical amount, measured in the observation's `unit`. |
| period_start | Observation's `start` | Date | For duration facts | Beginning of the financial period; null for instant facts. |
| period_end | Observation's `end` | Date | Yes | End of a duration, or the measurement date of an instant fact. |

For the current candidate concepts:

- Revenue and net income describe a duration and require both dates.
- Total assets describe an instant and require only `period_end`.
- A missing start date does not turn a duration fact into an
  instant fact. Determine the expected period type from the concept.

Preserve actual source dates as dates, not timestamps.
For duration facts, `period_start` must not exceed `period_end`.
Do not replace these dates with filing dates or fiscal labels.

Preserve the reported amount and sign. A missing value is not zero,
and a negative value is not automatically invalid: net income
can represent a loss.

The planned Silver storage type for `fact_value` is `DECIMAL(28,8)`.
Exact parsing and conversion rules are defined under
Company-fact numeric storage policy below.

#### Descriptive and filing metadata

| Project field | Source | Logical type | Required | Meaning |
|---|---|---|---|---|
| entity_name | Top-level `entityName` | String | No | Company name supplied in the retrieved response; CIK remains the identifier. |
| concept_label | `facts[taxonomy][concept].label` | String | No | Human-readable description of the concept. |
| filing_form | Observation's `form` | String | Yes | Filing type, such as `10-K`, `10-Q`, or `10-K/A`; preserve amendment suffixes. |
| filing_date | Observation's `filed` | Date | Yes | SEC filing date associated with the observation. |
| filing_fiscal_year | Observation's `fy` | Integer | No | Fiscal-year label associated with the filing, not necessarily the year measured by the fact. |
| filing_fiscal_period | Observation's `fp` | String | No | Filing's fiscal-period label, such as `FY` or `Q1`; not a classification of the fact's duration. |
| frame | Observation's `frame` | String | No | SEC calendar-alignment label, when supplied; preserve its original value. |

Names and concept labels describe the retrieved response.
Do not assume they are historical descriptions as of the filing date.
They are not record identifiers.

Preserve missing optional values as null, never as the diagnostic
marker "<absent>". Do not invent missing fiscal labels or frames.

Financial dates remain authoritative for the observation's period.
Do not replace them with `filing_fiscal_year`,
`filing_fiscal_period`, or dates inferred from `frame`.

Keep `filing_date` separate from our future retrieval timestamp.
It is not an exact timestamp of public availability.

### Unit and reporting-period rules

Initial Silver normalization will support these inspected
candidate concepts from the `us-gaap` taxonomy:

| Concept | Accepted unit | Period type |
|---|---|---|
| RevenueFromContractWithCustomerExcludingAssessedTax | USD | Duration |
| NetIncomeLoss | USD | Duration |
| Assets | USD | Instant |

This defines initial normalization scope, not proof of recent
coverage or suitability for every Gold metric.

#### Units

- Preserve amounts in their reported USD units. Do not convert
  currencies or rescale stored values into millions or billions.
- Other taxonomy/concept/unit combinations remain in raw Bronze
  data but are outside this initial Silver scope. Out of scope
  does not automatically mean invalid source data.
- If a selected concept or its USD observations are unavailable,
  report that absence. Do not substitute zero or silently choose
  another concept or currency.

#### Reporting periods

- Duration facts require valid start and end dates, with
  `period_start <= period_end`.
- Instant facts require a valid end date and an absent or null
  start date. Flag an unexpected start date rather than erase it.
- Determine duration versus instant from the configured concept,
  not from whether a start date happens to be missing.
- Preserve reported periods. Do not assume every duration is a
  standalone quarter or a full year, or classify it solely from
  filing form, fiscal labels, or frame.
- Silver will not annualize amounts, derive standalone quarters,
  or sum repeated disclosures.

Gold rules will separately define comparable metric periods,
filing-version selection, and coverage requirements.

### Company-fact numeric storage policy

- Field: `fact_value`.
- Silver storage type: `DECIMAL(28,8)` — 20 integer digits
  and 8 fractional digits.
- This is our MVP storage policy, not an SEC precision guarantee.

Parse JSON integer values as exact integers and fractional values
as decimals, without an intermediate binary floating-point value.
Convert integers directly to decimals when preparing Silver records.

Accept only finite numeric values. Reject missing/null values,
booleans, numeric strings, NaN, and infinity.

Validate exact representability before casting:

- The amount must fit the storage range.
- Conversion must preserve its numerical value without rounding
  or truncation.
- Extra trailing fractional zeros are acceptable when removing
  them does not change the value.

For example, 123.450000000 is exactly representable,
but 123.456789012 would require rounding and must be rejected.

Keep rejected source observations in Bronze, exclude them from
Silver, and record the validation failure. Never replace them
with zero or a rounded amount.

Implementation and automated boundary tests remain pending.

### Ingestion metadata

Our pipeline adds these required fields to each stored Bronze
response and carries them into its parsed fact observations.

| Field | Logical type | Meaning |
|---|---|---|
| source_system | String | Source identifier; fixed to `sec_edgar`. |
| source_response_id | String | Unique identifier generated for each successfully retrieved response. |
| fetched_at | Timestamp in UTC | When our process received the successful API response. |
| ingestion_run_id | String | Unique identifier for the ingestion execution. |

Rules:

- Each `source_response_id` identifies one original Bronze response.
  All facts extracted from that response share its metadata.
- Requests within one ingestion execution share `ingestion_run_id`.
  Each successful response has its own response ID and timestamp.
- A new API retrieval gets a new response ID and timestamp,
  even when its content is unchanged.
- Reprocessing stored Bronze data preserves all original ingestion
  metadata. Track the transformation execution separately.
- `filing_date` describes the source filing; `fetched_at` describes
  our retrieval. Neither proves the exact time of public availability.
- Response IDs, run IDs, and retrieval timestamps are not part of
  the financial-fact business key. Repeated retrievals do not
  represent new SEC filings.
- Never copy `.env` values or private request headers into
  data records or logs.


### Record identity and within-response duplicates

The business key for a filing-level fact is:

    (source_system, cik, taxonomy, concept, unit,
     period_start, period_end, accession_number)

- For instant facts, compare null `period_start` values as equal.
  Do not replace null with an invented date.
- Different accession numbers represent separate filing-level
  observations, even when the period and amount match.
- The amount, descriptive labels, retrieval timestamp, response ID,
  and run ID are not part of this business key.

Apply the following checks to valid, in-scope observations within
each `source_response_id`:

- Same key and identical normalized source fields: keep one
  observation. Compare decimal amounts by numerical value,
  so extra trailing zeros do not create a difference.
- Same key but differing normalized source fields: flag a conflict.
  Do not resolve it by choosing whichever appears first or last
  in the response array.
- A conflict fails the SEC Silver refresh before publication.
  Preserve the original Bronze response and record the affected
  key, response ID, and conflicting field names.
- If a previously successful Silver result exists, leave it
  unchanged and report the refresh failure; do not present it
  as newly refreshed.

These rules handle duplicates within one retrieved response.
Selection across different retrievals, and selection of a filing
for a Gold metric or historical cutoff, are defined separately.

### Cross-retrieval selection and replay

#### Current Silver snapshot

- For each `(source_system, cik)`, select the complete retrieved
  response with the greatest original `fetched_at`.
- Select the response before applying fact-level validation.
  Do not silently fall back to an older response when the newest
  response contains invalid or missing observations.
- If responses tie at the latest timestamp, choose the smallest
  `source_response_id` only when their raw payloads are identical.
  Different payloads at the same latest timestamp are ambiguous
  and fail the refresh.
- Apply the contract to the selected response. Invalid individual
  facts follow the documented exclusion rules; response-level
  failures or within-response conflicts fail the SEC refresh.
- Publish the validated refresh atomically. On failure, preserve
  the previous successful Silver result and report the failure.
- A successful refresh replaces each company's current facts
  with accepted observations from its selected response.
  Do not fill gaps with facts from older responses.
- Preserve distinct filings within the selected response.
  Changes between different retrievals are snapshot changes,
  not automatically within-response conflicts. Bronze retains
  the earlier responses.

#### Replay and historical cutoffs

- Replay uses original retrieval metadata, not the replay time.
  An older replay must not overwrite a newer current snapshot.
- For a historical retrieval cutoff `T` in UTC, apply the same
  selection rules only to stored responses with `fetched_at <= T`.
  If none exists, report that historical snapshot as unavailable.
- Historical reconstruction must not overwrite current Silver.
- Do not use today's response with an old `filing_date` filter
  and claim it reconstructs what our pipeline knew at that time.
- These cutoffs describe stored observations, not exact public
  availability or complete historical market knowledge.

Gold period/filing selection and historical-query implementation
remain separate work.

### Validation rules and failure actions

Apply the existing contract through these checks:

| Check | Requirement | Failure action |
|---|---|---|
| Response | Successful retrieval, expected JSON object/array structure, and reporting CIK matching the configured request. | Fail the SEC refresh. |
| Provenance | Required source, response ID, run ID, and UTC retrieval timestamp; response ID links to the original Bronze payload. | Fail the SEC refresh. |
| Scope | Documented taxonomy/concept/unit combination. | Retain in Bronze and classify as out of scope, not automatically invalid. |
| Fact fields | Required fields present, declared types respected, and identifiers correctly formatted. | Exclude the invalid observation from Silver. |
| Amount and period | Existing exact-decimal and duration/instant rules satisfied. | Exclude the invalid observation from Silver. |
| Publication | Snapshot selection is unambiguous, no within-response conflicts, and final business keys are unique. | Fail the SEC refresh before publication. |

Field details:

- Normalize a validated reporting CIK to 10 ASCII digits.
- Accession numbers must have the form:
  10 ASCII digits, hyphen, 2 digits, hyphen, 6 digits.
  Do not require their prefix to match the reporting CIK.
- Required strings must be nonblank. Dates must be real calendar
  dates parsed from YYYY-MM-DD source values.
- Optional strings that are missing, null, or blank become null.
  Other supplied values must have the declared type.
- A supplied `filing_fiscal_year` must be an integer, not a boolean.
  Do not silently coerce numeric strings into numeric fields.

Missing selected concepts or USD observations are reported as
unavailable, not replaced with zeros or older-response facts.

Record accepted, rejected, out-of-scope, and duplicate counts,
plus response IDs and failed rule names. Preserve raw evidence
in Bronze without logging credentials or private request headers.

Failed fetches or refreshes must remain visible as failures.
Do not present an older successful result as newly refreshed.

These checks are documented requirements; automated tests
and complete source-data validation remain pending.

### Representative contract examples

These are synthetic scenarios, not actual company disclosures.
Assume all unspecified fields and ingestion metadata are valid.
Numeric examples represent JSON numbers unless explicitly quoted.

| Scenario | Expected outcome |
|---|---|
| `NetIncomeLoss` is -100 USD with valid duration dates. | Accept; a loss is not automatically invalid. |
| `Assets` has a valid end date and no start date. | Accept as an instant fact. |
| Revenue has an end date but no start date. | Exclude the invalid fact. |
| `fact_value` is 123.456789012 or 1e20. | Exclude: the first requires rounding; the second exceeds the storage range. |
| `fact_value` is the string `"100"`. | Exclude; do not silently convert numeric strings. |
| Response CIK differs from the requested company's CIK. | Fail the SEC refresh. |
| A selected concept is reported in EUR rather than USD. | Classify that observation as out of scope. |
| Same key and identical normalized fields occur twice within one response. | Keep one observation. |
| Same key has values 100 and 101 within one response. | Fail the SEC refresh because of a conflict. |
| Same concept, period, unit, and value appear under two accession numbers. | Preserve both filing-level observations. |
| An older response reports 100; a newer response reports 101 for the same key. | Use 101 from the selected newer snapshot; retain both responses in Bronze. |
| A fact exists in an older response but is absent from the selected newer valid response. | Do not carry the old fact into current Silver. |
| Two responses share the latest retrieval timestamp but have different raw payloads. | Fail the SEC refresh because selection is ambiguous. |
| No stored response has `fetched_at <= T`. | Report the historical snapshot as unavailable. |

Excluding an invalid fact does not automatically fail the entire
refresh. A refresh-level failure preserves any previous successful
Silver output and must remain visible as a failure.

These are expected outcomes for future tests, not evidence that
automated tests have passed.