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