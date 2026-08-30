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
- Decimal precision and scale will be finalized after inspecting sample data.
- Additional source fields remain preserved in the raw payload.

### Feed and price-adjustment decisions

- Requested feed: `sip` — consolidated US equity market data.
- Adjustment: `split` — adjust historical prices and volumes
  for forward and reverse stock splits.
- Return interpretation: split-adjusted price returns,
  excluding dividend income.
- Include only completed trading days before the current
  date in America/New_York; exclude the current day's partial bar.
- Historical SIP access must be verified with our account
  before ingestion.
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

### Still to define
- Verify historical SIP access using an authenticated sample request.
- Decimal precision and scale (after inspecting source samples).

