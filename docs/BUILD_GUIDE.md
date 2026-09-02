# Multi-Agent Equity Research System — Build Guide

## Purpose

This guide explains how to reproduce the project from an empty repository.
It complements:

- `README.md`: project purpose, architecture, and showcase
- `PLAN.md`: current progress and remaining milestones
- `DATA_CONTRACTS.md`: datasets, schemas, and quality rules

The guide records meaningful implementation steps, required files, commands,
verification gates, and current limitations. It does not contain credentials,
personal workspace identifiers, or temporary debugging transcripts.

## Delivery workflow

Development follows this repeatable workflow:

```text
Plan the slice
    ↓
Define contracts and configuration
    ↓
Implement locally
    ↓
Run offline tests
    ↓
Validate the Databricks bundle
    ↓
Review the deployment plan
    ↓
Deploy to the development workspace
    ↓
Run the Databricks job
    ↓
Verify the resulting data
    ↓
Commit, push, and review through a pull request


```

## Repository components

| File or directory | Responsibility |
|---|---|
| `databricks.yml` | Bundle identity, deployment targets, and environment variables |
| `resources/*.yml` | Databricks infrastructure and job definitions |
| `src/equity_research/` | Reusable Python application modules |
| `src/*.py` | Databricks notebook entry points |
| `config/` | Non-secret project configuration |
| `tests/` | Offline automated tests |
| `DATA_CONTRACTS.md` | Dataset schemas, rules, and provenance requirements |
| `PLAN.md` | Milestone status and next work |

## Milestone 1 — Data engineering

### Slice 1: Bronze daily-price ingestion

**Status:** Bounded ingestion, reusable source validation, pagination, retries,
backfill/incremental windows, and safe reruns are deployed and verified.

#### Goal

Retrieve daily bars for the configured equities and retain each successful
Alpaca response page as raw, replayable Bronze history with ingestion
provenance.

#### Components

| File | Purpose |
|---|---|
| `databricks.yml` | Defines the catalog, Bronze schema, secret scope, and development target |
| `resources/bronze.schema.yml` | Provisions and protects the Unity Catalog Bronze schema |
| `resources/bronze_price_ingestion.job.yml` | Defines the serverless ingestion job and its parameters |
| `src/bronze_price_ingestion.py` | Retrieves, validates, and persists the Alpaca response |
| `src/equity_research/alpaca_prices.py` | Provides reusable request, response, and pagination logic |
| `tests/test_alpaca_prices.py` | Verifies the source contract and pagination safety offline |
| `config/equities.json` | Defines the initial AAPL/MSFT live scope |
| `DATA_CONTRACTS.md` | Defines the Bronze response envelope and future Silver records |

#### Data flow

```text
config/equities.json
        ↓
Databricks job parameters and secrets
        ↓
Alpaca historical bars API
        ↓
Bronze price_responses Delta table
        ↓
SQL verification
```

#### Implementation stages

1. Configure runtime secrets.
2. Define bundle variables.
3. Define the Bronze schema.
4. Define the ingestion job.
5. Implement the Databricks notebook.
6. Validate and review the bundle plan.
7. Deploy and run the job.
8. Verify the persisted response.
9. Add reusable source tests and prove multi-page ingestion.
10. Add remaining production hardening.


#### Stage 1 — Configure runtime secrets

**Goal:** Allow the deployed Databricks job to authenticate with Alpaca without
placing credentials in source control, bundle configuration, notebook code, or
job output.

Local `.env` credentials are used only for local development checks.
Databricks workloads retrieve credentials from an encrypted Databricks secret
scope.

##### Resources created

```text
equity-research-dev
├── alpaca-api-key
└── alpaca-secret-key
```

Only the scope and key names are non-secret. The values must never be committed
or printed.

##### Procedure

The examples assume the Databricks CLI is authenticated and available as
`databricks`. If VS Code supplies the executable, it can instead be invoked
using its full path.

Authenticate a named CLI profile when required:

```powershell
databricks auth login `
  --host "<workspace-url>" `
  --profile "<profile>"
```

Confirm that the terminal profile is valid:

```powershell
databricks auth profiles
```

List existing scopes before creating one:

```powershell
databricks secrets list-scopes --profile "<profile>"
```

Create the development scope:

```powershell
databricks secrets create-scope "equity-research-dev" `
  --profile "<profile>"
```

Add each credential through the interactive secret editor:

```powershell
databricks secrets put-secret `
  "equity-research-dev" "alpaca-api-key" `
  --profile "<profile>"

databricks secrets put-secret `
  "equity-research-dev" "alpaca-secret-key" `
  --profile "<profile>"
```

Paste only the credential value—not an assignment such as
`ALPACA_API_KEY=...`.

Verify only the scope and key names:

```powershell
databricks secrets list-secrets "equity-research-dev" `
  --profile "<profile>"
```

##### Security rules

- Never place secret values in Git, YAML, notebooks, screenshots, or logs.
- Never print a value returned by `dbutils.secrets.get`.
- Avoid passing secret values as command-line arguments because shell history
  can retain them.
- Version the expected scope and key names, but provision the values separately
  for every environment.
- A production organization may provision secrets through centrally managed
  infrastructure.

##### Verification gate

The scope contains both expected key names, and a deployed Databricks job can
retrieve them and call Alpaca without displaying either value.

#### Stage 2 — Define bundle variables and the development target

**Goal:** Define the project-level Databricks configuration once and make
environment-specific values reusable by schema, job, and notebook resources.

##### File updated

```text
databricks.yml
```

This is the root configuration file for the Databricks bundle. It identifies
the project, includes resource definitions, declares variables, and defines
deployment targets.

##### Configuration

```yaml
bundle:
  name: multi-agent-equity-research-system-on-databricks

include:
  - resources/*.yml

variables:
  data_catalog:
    description: Unity Catalog catalog containing the medallion schemas.
    default: workspace

  bronze_schema:
    description: Unity Catalog schema containing raw Bronze datasets.
    default: equity_research_bronze

  alpaca_secret_scope:
    description: Databricks secret scope containing the Alpaca credentials.
    default: equity-research-dev

targets:
  dev:
    mode: development
    default: true
    workspace:
      host: <workspace-url>
```

##### Configuration responsibilities

| Block | Responsibility |
|---|---|
| `bundle.name` | Gives the deployed project a stable logical identity |
| `include` | Loads schema, job, pipeline, and other resource files from `resources/` |
| `variables` | Centralizes environment-dependent non-secret values |
| `targets.dev` | Defines the development deployment environment |
| `mode: development` | Enables development-safe naming and behavior |
| `default: true` | Makes `dev` the default target when none is specified |
| `workspace.host` | Selects the existing Databricks workspace |

The configuration references an existing workspace and catalog. It does not
create a Databricks account, workspace, or the `workspace` catalog.

##### Variable flow

Resource files reuse bundle variables through substitutions:

```text
databricks.yml
├── ${var.data_catalog}
├── ${var.bronze_schema}
└── ${var.alpaca_secret_scope}
        ↓
schema and job resource definitions
        ↓
notebook task parameters
```

Only names and configuration values are stored here. Actual Alpaca credential
values remain in Databricks Secrets.

##### Development naming

Development mode isolates resources by adding a developer-specific prefix.
Therefore, the logical schema:

```text
equity_research_bronze
```

can be deployed in development as:

```text
dev_<developer>_equity_research_bronze
```

A later production target can use the clean logical name without the
development prefix.

Do not manually rename bundle-managed development resources because that can
break deployment-state tracking.

##### Validation

Validate the configuration before deploying resources:

```powershell
databricks bundle validate `
  --target "dev" `
  --profile "<profile>"
```

Expected validation information includes:

- Bundle name.
- Selected target.
- Workspace host.
- Authenticated user.
- Deployment path.
- `Validation OK!`

Warnings and errors must be reviewed before deployment rather than ignored.

##### Verification gate

The bundle validates successfully, resolves the `dev` target, and exposes the
catalog, schema, and secret-scope variables to included resource definitions.

#### Stage 3 — Define the Bronze schema

**Goal:** Manage the Unity Catalog container for raw datasets through
version-controlled bundle configuration instead of creating it manually in the
Databricks UI.

##### File created

```text
resources/bronze.schema.yml
```

Keeping the schema in its own resource file makes infrastructure changes easier
to review and prevents job definitions from becoming mixed with data-governance
configuration.

##### Resource definition

```yaml
resources:
  schemas:
    bronze:
      name: ${var.bronze_schema}
      catalog_name: ${var.data_catalog}
      comment: Raw, replayable source responses for the equity research system.
      lifecycle:
        prevent_destroy: true
```

##### Configuration responsibilities

| Setting | Purpose |
|---|---|
| `schemas.bronze` | Logical bundle identifier used by other resources |
| `name` | Reuses the logical Bronze schema name from `databricks.yml` |
| `catalog_name` | Places the schema inside the configured Unity Catalog catalog |
| `comment` | Documents the schema's data-engineering purpose |
| `prevent_destroy` | Blocks accidental deletion through bundle operations |

This resource creates the schema only. It does not:

- Create the Databricks workspace.
- Create the existing `workspace` catalog.
- Create Bronze tables.
- Retrieve or transform source data.

The logical resource can be referenced elsewhere as:

```text
${resources.schemas.bronze.catalog_name}
${resources.schemas.bronze.name}
```

This ensures jobs use the actual deployed schema name, including any
development prefix added by Databricks.

##### Resulting namespace

```text
<data catalog>.<deployed Bronze schema>
```

For example, a development deployment can produce:

```text
workspace.dev_<developer>_equity_research_bronze
```

Raw tables such as `price_responses`, `news_responses`, and
`company_facts_responses` will be created inside this shared Bronze schema.

##### Verification gate

Bundle validation recognizes the schema resource, deployment creates a managed
Unity Catalog schema, and subsequent deployment plans show it as unchanged.

#### Stage 4 — Define the Bronze ingestion job

**Goal:** Define how Databricks executes the Bronze price notebook and connects
it to the deployed schema, secret scope, and bounded request parameters.

##### File created

```text
resources/bronze_price_ingestion.job.yml
```

This file defines orchestration. It tells Databricks what to run and with which
parameters, but it does not contain API extraction or Delta-write logic.

##### Job definition

```yaml
resources:
  jobs:
    bronze_price_ingestion:
      name: ${bundle.name}-bronze-price-ingestion
      description: >-
        Ingests configured daily equity-price response pages into a managed
        Bronze Delta table.
      max_concurrent_runs: 1
      parameters:
        - name: load_mode
          default: backfill
        - name: start
          default: "2026-08-27T00:00:00-04:00"
        - name: end
          default: "2026-08-27T23:59:59-04:00"
        - name: lookback_days
          default: "7"
        - name: page_limit
          default: "10000"

      tasks:
        - task_key: ingest_bronze_prices
          notebook_task:
            notebook_path: ../src/bronze_price_ingestion.py
            base_parameters:
              catalog: ${resources.schemas.bronze.catalog_name}
              bronze_schema: ${resources.schemas.bronze.name}
              secret_scope: ${var.alpaca_secret_scope}
              load_mode: "{{job.parameters.load_mode}}"
              start: "{{job.parameters.start}}"
              end: "{{job.parameters.end}}"
              lookback_days: "{{job.parameters.lookback_days}}"
              page_limit: "{{job.parameters.page_limit}}"
          timeout_seconds: 300
```

##### Job responsibilities

| Setting | Purpose |
|---|---|
| `jobs.bronze_price_ingestion` | Logical bundle identifier for deployment and execution |
| `name` | Builds the displayed job name from the bundle identity |
| `max_concurrent_runs: 1` | Prevents overlapping ingestion executions |
| `parameters` | Defines the operator-facing backfill/incremental request interface |
| `task_key` | Gives the notebook task a stable orchestration identifier |
| `notebook_path` | Selects the Python notebook entry point |
| `base_parameters` | Passes environment and request values to notebook widgets |
| `page_limit` | Bounds each Alpaca response while allowing continuation-token pagination |
| `timeout_seconds` | Prevents an unresponsive task from running indefinitely |

The schema parameters reference the deployed schema resource:

```text
${resources.schemas.bronze.catalog_name}
${resources.schemas.bronze.name}
```

This avoids hard-coding the development-prefixed schema name.

The secret-scope parameter passes only the non-secret scope name:

```text
${var.alpaca_secret_scope}
```

The notebook retrieves the actual values at runtime.

##### Load modes

The default backfill uses one known completed trading day:

```text
start: 2026-08-27T00:00:00-04:00
end:   2026-08-27T23:59:59-04:00
```

This bounded window makes the first persistent test predictable and inexpensive.
Operators can override these job-level parameters without changing or deploying
code. Incremental mode calculates a seven-calendar-day overlap ending at
23:59:59 on the previous New York day, so it excludes the current incomplete
daily bar.

Pagination was proven separately by temporarily setting `page_limit` to `1`.
The verified run retrieved two pages under one ingestion ID: page 1 returned a
continuation token, page 2 reused it and returned no next token, and both pages
were appended together. The routine limit was then restored to `10000`.

Repeating the same incremental interval creates a separate Bronze ingestion
record. The verified safe rerun retained identical response hashes under
different ingestion IDs and timestamps. Silver later removes duplicate business
bars. A scheduled refresh trigger remains pending.

##### Future task dependencies

Silver and Gold tasks will later use orchestration dependencies:

```text
ingest_bronze_prices
        ↓
validate_silver_daily_prices
        ↓
build_gold_market_metrics
```

A downstream task must not publish results when its upstream data task fails.

##### Verification gate

Bundle deployment creates or updates the job, resolves the actual deployed
schema name, and passes the expected parameters to the notebook task.

#### Stage 5 — Implement the Bronze ingestion notebook

**Goal:** Retrieve every page in a bounded Alpaca request, validate its minimum
structure, and append the original responses with shared run provenance to a
managed Bronze Delta table.

##### File created

```text
src/bronze_price_ingestion.py
```

The file uses Databricks notebook-source format:

```python
# Databricks notebook source
```

This allows the `.py` file to remain reviewable in Git while executing as a
Databricks notebook task.

##### Execution blocks

| Block | Responsibility |
|---|---|
| Constants and helper functions | Define the fixed Alpaca host/path and validate catalog identifiers |
| Job parameters | Read catalog, schema, secret-scope, load-mode, date, lookback, and page-limit values |
| Window resolution | Validate an explicit backfill or calculate a completed-day incremental overlap |
| Shared configuration | Load the supported equities from `config/equities.json` |
| Runtime secrets | Retrieve Alpaca credentials without printing them |
| API request | Request daily-bar pages using the contract settings and continuation tokens |
| Response validation | Check HTTP status, JSON structure, symbols, bars, and pagination metadata |
| Pagination safety | Stop on the final page and reject repeated tokens or excessive page counts |
| Retry safety | Retry temporary network, rate-limit, timeout, and server failures with bounded backoff |
| Bronze table definition | Create the managed Delta table with an explicit raw-envelope schema |
| Append | Store all pages from one successful retrieval under one ingestion ID |
| Post-write verification | Confirm persisted rows equal retrieved pages for the ingestion ID |

##### Read job parameters

The job YAML passes values to notebook widgets:

```python
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("bronze_schema", "")
dbutils.widgets.text("secret_scope", "")
dbutils.widgets.text("load_mode", "backfill")
dbutils.widgets.text("start", "")
dbutils.widgets.text("end", "")
dbutils.widgets.text("lookback_days", "7")
dbutils.widgets.text("page_limit", "10000")
```

The notebook validates required parameters before performing external or
persistent operations. Catalog and schema identifiers are restricted to safe
identifier characters before being used in SQL.

##### Load scope and credentials

The configured equities are loaded from the shared project configuration:

```python
equities = load_equities()
symbols = [equity.alpaca_symbol for equity in equities.values()]
```

This prevents AAPL and MSFT from being duplicated as hard-coded pipeline logic.

Credentials are retrieved only at runtime:

```python
api_key = dbutils.secrets.get(
    scope=secret_scope,
    key="alpaca-api-key",
)

api_secret = dbutils.secrets.get(
    scope=secret_scope,
    key="alpaca-secret-key",
)
```

The values are used only in request headers and are never printed or persisted.

##### Request contract

The request uses the agreed market-data settings:

```text
symbols: configured equities
timeframe: 1Day
feed: sip
adjustment: split
currency: USD
start/end: resolved backfill or incremental window
```

The request is sent only to the fixed HTTPS Alpaca market-data host.
Redirect-following is avoided so authentication headers are not forwarded to
another host.

##### Validate before persistence

The notebook fails before writing when:

- The request cannot be completed.
- Alpaca returns a non-200 status.
- The response is not valid UTF-8 JSON.
- The response does not contain a `bars` object.
- A configured symbol has no returned bar across the complete page sequence.
- Pagination metadata has an unexpected type.

This first slice performs minimum source-response validation. Full business
validation belongs in Silver.

##### Bronze response envelope

One Bronze row represents one successfully received API response page—not one
individual stock bar.

The row retains:

```text
Response identity
├── source_response_id
└── ingestion_run_id

Request provenance
├── source endpoint
├── request parameters
├── request page token
└── page number

Response provenance
├── HTTP status
├── next page token
├── original JSON payload
├── response byte count
├── SHA-256 content hash
├── records received
└── fetched_at timestamp
```

Credentials are not included in request parameters or response storage.

##### Delta persistence

The notebook creates `price_responses` with explicit SQL DDL when the table does
not already exist. It retrieves all required pages before building a Spark
DataFrame with an explicit schema and appending them in one Delta write:

```text
mode: append
format: delta
table: <catalog>.<Bronze schema>.price_responses
```

Bronze is append-only retrieval history. Repeating the same request produces a
new retrieval record. Silver will later apply business-key deduplication and
replay rules.

##### Post-write verification

After the append, the notebook filters the table by `ingestion_run_id` and
requires the persisted row count to equal the number of retrieved pages.

A successful execution returns:

```text
BRONZE_PRICE_APPEND=PASSED
rows_appended=<retrieved-page-count>
```

##### Current limitations

This slice does not yet implement:

- Scheduled refreshes.
- Operational failure tables.
- Silver validation and deduplication.

##### Verification gate

The gate consists of 26 passing offline tests plus deployed backfill,
multi-page, incremental, retry-enabled, and safe-rerun executions. Raw pages are
retained without exposing credentials, and identical reruns remain auditable
under distinct ingestion IDs.

#### Stages 6–8 — Validate, deploy, run, and verify

**Goal:** Apply the bundle through a controlled sequence and verify both the
Databricks resources and the data written by the job.

##### Operational sequence

```text
Validate configuration
        ↓
Review proposed resource changes
        ↓
Deploy code and resources
        ↓
Execute the job
        ↓
Verify schema, table, and row contents
```

##### 1. Validate

```powershell
databricks bundle validate `
  --target "dev" `
  --profile "<profile>"
```

Validation checks bundle syntax, substitutions, resource references, the
selected target, and workspace access.

Expected result:

```text
Validation OK!
```

A warning should be understood and resolved before deployment.

##### 2. Review the deployment plan

```powershell
databricks bundle plan `
  --target "dev" `
  --profile "<profile>"
```

Review the counts and named operations before continuing:

```text
add
change
delete
unchanged
```

Stop when the plan proposes an unexpected deletion or resource recreation.
This is particularly important after changing catalog, schema, or resource
names because those changes can affect persisted data.

##### 3. Deploy

```powershell
databricks bundle deploy `
  --target "dev" `
  --profile "<profile>"
```

Deployment:

- Synchronizes project files to the bundle's workspace path.
- Creates or updates the managed Bronze schema.
- Creates or updates the ingestion job.
- Does not execute the job automatically.

The deployment result should contain only the expected file and resource
changes.

##### 4. Run

```powershell
databricks bundle run bronze_price_ingestion `
  --target "dev" `
  --profile "<profile>"
```

A successful run returns a Databricks run URL and terminates with:

```text
BRONZE_PRICE_APPEND=PASSED
rows_appended=<retrieved-page-count>
```

Each successful run stores every response page required for the bounded request
under one `ingestion_run_id`.

##### 5. Verify Unity Catalog resources

List the deployed schemas:

```powershell
databricks schemas list "<catalog>" `
  --profile "<profile>"
```

List tables inside the deployed Bronze schema:

```powershell
databricks tables list `
  "<catalog>" "<deployed-bronze-schema>" `
  --profile "<profile>"
```

Expected managed table:

```text
<catalog>.<deployed-bronze-schema>.price_responses
```

##### 6. Verify persisted metadata

Run a bounded query in the Databricks SQL Editor:

```sql
SELECT
    source_response_id,
    source_system,
    page_number,
    http_status,
    records_received,
    fetched_at,
    ingestion_run_id
FROM <catalog>.<deployed-bronze-schema>.price_responses
ORDER BY fetched_at DESC;
```

For the initial AAPL/MSFT slice, the latest row should show:

```text
source_system     alpaca
page_number       1
http_status       200
records_received  2
```

The Catalog Overview verifies table structure. The SQL query verifies stored
data. Both checks are required.

##### Evidence retained

Keep durable evidence concise:

- Successful bundle validation.
- Reviewed deployment plan.
- Successful Databricks run URL.
- Expected managed table.
- Verified metadata row.

Do not commit full raw API responses, secret values, personal CLI profiles, or
large terminal transcripts.

##### Verification gate

The bundle deploys without unexpected destructive changes, the serverless job
terminates successfully, and SQL verification confirms one valid Bronze
response envelope for the configured equities.
