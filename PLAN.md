# Multi-Agent Equity Research System on Databricks - Implementation Plan

The MVP is intentionally limited to AAPL and MSFT. A milestone is complete only when its acceptance criteria are met.

**Scope decision:** Finish the two-stock workflow end to end before reconsidering broader stock coverage.

**Expansion design (planned):** Use one central equities configuration, initially AAPL and MSFT, for ingestion, scope checks, analytics, research tools, and UI selection. Adding another compatible US equity should require a configuration change and the normal onboarding/backfill checks, not changes to pipeline logic or stock-specific tables or agents. Resolve and validate required provider/SEC identifiers; report unsupported or ambiguous mappings rather than guessing. Provider news tags must never expand this configured universe automatically.

**Current step:** Milestone 1 - the reviewed company-news contract and local access-check instructions are saved; `README.md` matches the script and the previously verified sample output. `.env` is ignored and untracked, and staging the news checkpoint is next. Ingestion, automated tests, shared-equities configuration, and permission verification remain pending; the live MVP remains AAPL and MSFT.

**Next small step:** Stage only `DATA_CONTRACTS.md`, `PLAN.md`, `README.md`, and `scripts/check_alpaca_news_access.py`. Inspect the staged filenames, change summary, and whitespace check before the local commit. Do not include `.env`, real article bodies, or generated workspace files; no API rerun, commit, or push is needed during this staging step.

**Tracking rule:** After each small step, review the result and tick its checkbox. Leave a parent task unchecked until all its subtasks are verified. Update the current and next steps before moving on.

## Phase 0 - Development setup

- [x] Set up the local Git repository, GitHub remote, and Databricks development bundle.
- [x] Validate, deploy, and run the serverless Spark smoke test; verify the returned pass marker.
- [x] Commit and push the verified smoke-test checkpoint (`e0f8eb5`).

**Evidence:** [Successful Phase 0 Databricks run](https://dbc-5e700074-422e.cloud.databricks.com/jobs/962241359191284/runs/277255524412899?o=7474654299884940) (requires workspace access).

## Milestone 1 - Data platform

- [x] Create and switch to the local `feature/data-contracts` branch.
- [ ] Define source schemas and data contracts in [DATA_CONTRACTS.md](DATA_CONTRACTS.md).
  - [x] Create the document and draft the daily price purpose, scope, and meaning of one record.
  - [x] Define daily price field names, meanings, logical types, and required values.
  - [x] Select and document the data feed and price-adjustment setting.
  - [x] Define record identifiers and duplicate handling.
  - [x] Define ingestion metadata.
  - [x] Define daily price validation rules.
  - [x] Review representative valid and invalid examples.
  - [x] Commit the reviewed daily price contract draft and plan updates as a local checkpoint (`94d9225`).
  - [x] Verify historical SIP access with an authenticated sample request.
    - [x] Confirm availability of an Alpaca paper-trading API key pair; never share or commit credentials (user-confirmed).
    - [x] Configure private local credentials (user-entered; `.env` existence and Git exclusion verified without reading secret values).
    - [x] Verify local dependencies: `python-dotenv` 1.2.3 (user-provided package output) and `requests` 2.34.2 (local package check) in the `db` environment.
    - [x] Verify that the local test can load the required credentials without printing their values (user-provided output: both presence checks returned `True`).
    - [x] Run a minimal read-only historical bars request and inspect the response (`scripts/check_alpaca_access.py`; user-run HTTP 200, one bar per symbol for 2026-08-27, `next_page_token: null`; saved request uses `sip`, `split`, `1Day`, and `USD`).
  - [x] Record the historical access-check evidence in `DATA_CONTRACTS.md`.
  - [x] Finalize decimal precision and scale after inspecting source samples (`DECIMAL(20,8)` for OHLC and volume; exact parsing and rejection of lossy conversions are documented, not yet implemented).
  - [x] Record local access-check dependencies and run instructions before the next code checkpoint.
    - [x] Record the verified direct dependency versions in `requirements.txt` (`python-dotenv==1.2.3` and `requests==2.34.2`).
    - [x] Document local setup, private credential configuration, the run command, and expected results in `README.md`.
  - [x] Review and commit the daily-price contract and local access-check checkpoint without credentials (`bfb8122`).
  - [x] Define the Alpaca company-news contract (reviewed draft; implementation and automated tests remain pending).
    - [x] Draft the news purpose, scope, and meaning of one record.
    - [x] Verify news API access with a small read-only sample and inspect article fields and content availability (`scripts/check_alpaca_news_access.py`; user-run HTTP 200, three articles, non-empty text fields, and more pages available; no full text displayed).
    - [x] Record the news sample-access evidence and its limits in `DATA_CONTRACTS.md`.
    - [x] Define core article fields, source mappings, logical types, and required/optional values.
    - [x] Define article identity and relationships to supported symbols.
    - [x] Define ingestion metadata and timestamp meanings.
    - [x] Define article update and duplicate handling.
    - [x] Define news validation rules.
    - [x] Review representative valid and invalid article examples.
    - [x] Review duplicate, revision, and replay examples.
    - [x] Define research-text eligibility and content-use boundaries (policy documented; actual permissions remain unverified).
    - [x] Clarify research scope versus accepted article revisions and finish the full news-contract review.
  - [x] Document the local news access-check command, expected output, and sample limitations in `README.md`.
  - [ ] Review and commit the news contract and access-check checkpoint without credentials or article bodies.
  - [ ] Define the SEC company-facts and selected-filings contracts.
- [ ] Create one shared equities configuration and loader before the first ingestion job; initialize it with AAPL and MSFT.
  - [ ] Drive ingestion requests, price scope validation, and news research-eligibility checks from this configuration; retain full provider news tags and apply news scope filtering after version selection.
  - [ ] Resolve and validate required provider/SEC identifiers during onboarding, with clear failures for unavailable or ambiguous mappings.
  - [ ] Make contract scope definitions configuration-driven while keeping existing examples explicitly tied to their two-stock test universe.
- [ ] Add basic GitHub Actions CI alongside the contracts: formatting, linting, and contract/unit tests on pull requests and `main`, using fixtures without live API credentials.
- [ ] Add an offline third-equity fixture test showing that a configuration change uses the same ingestion/transformation logic without stock-specific code; do not expand live API requests for this test.
- [ ] Confirm and document permitted provider-data storage, retention, and processing before persistent ingestion; use synthetic fixtures where permissions remain unresolved.
- [ ] Ingest Alpaca historical prices into Bronze.
- [ ] After the first Bronze job works, verify secure non-interactive Databricks authentication supported by Free Edition; document manual CLI deployment as the fallback if unavailable.
- [ ] Add controlled CD: manually trigger deployment of a CI-tested `main` commit, validate the bundle, deploy to `dev`, and run a verification job. Record the commit and Databricks run link.
- [ ] Ingest Alpaca company news into Bronze.
- [ ] Ingest SEC fundamentals and selected filings into Bronze.
- [ ] Create cleaned, deduplicated Silver tables.
- [ ] Create Gold market and fundamental metrics using shared per-symbol logic for the configured equities.
- [ ] Add data-quality tests and freshness checks.
- [ ] Schedule the pipeline in Databricks.

**Acceptance criteria:** AAPL and MSFT data can be rebuilt from Bronze, passes validation, and produces reproducible Gold metrics with an `as_of` timestamp.

**Extensibility acceptance criteria:** Offline tests demonstrate adding a compatible equity through configuration alone, with no pipeline-logic changes. Live onboarding still requires available source data, validated identifiers, backfill, and readiness checks; missing data is reported, not invented.

**CI/CD acceptance criteria:** CI passes on the tested commit. Deployment and post-deployment verification are reproducible through GitHub Actions, or through the documented manual fallback if Free Edition authentication prevents unattended deployment. Deployment does not replace the scheduled data-refresh job.

## Milestone 2 - Retrieval and multi-agent workflow

- [ ] Create curated filing and news documents with metadata.
- [ ] Confirm permitted text indexing, model/embedding-provider processing, and retention before using real provider content for retrieval or model calls; keep synthetic fixtures as the fallback.
- [ ] Chunk documents and create a vector index.
- [ ] Implement controlled SQL and retrieval tools that validate requested symbols against the shared configuration and data readiness.
- [ ] Implement the Market Analyst.
- [ ] Implement the Company Researcher.
- [ ] Implement the Supervisor workflow in LangGraph.
- [ ] Require structured outputs, citations, and error handling.
- [ ] Create and run an agent evaluation dataset.
- [ ] Extend CI with agent/tool unit tests and offline evaluations; run live-model evaluations separately with controlled credentials and usage limits before release.

**Acceptance criteria:** A comparison request produces a grounded report whose numerical claims match Gold tables and whose textual claims include valid sources.

## Milestone 3 - Application and deployment

- [ ] Build stock and period selection controls from the shared equities configuration and readiness status; do not maintain a separate UI stock list.
- [ ] Display market charts and comparison metrics.
- [ ] Display the generated research report and citations.
- [ ] Add follow-up chat over the report evidence.
- [ ] Add logging, monitoring, and secret management.
- [ ] Confirm permitted public display and redistribution of real provider data and derived outputs before sharing the application or demo; use clearly labelled synthetic demo data if permission is unresolved. Review [Alpaca's redistribution guidance](https://alpaca.markets/support/redistribute-alpaca-api) and the applicable account/provider terms; API access alone is not approval.
- [ ] Deploy the application on Databricks.
- [ ] Extend controlled CD to deploy/start the application and verify its health; keep release deployment manually triggered from a CI-tested commit.
- [ ] Add screenshots, a short demo, and reproduction instructions.
- [ ] Document CI checks, deployment authentication, release verification, and how to redeploy a previous known-good code version without automatically reverting data.

**Acceptance criteria:** A new user can open the deployed application, compare AAPL and MSFT, inspect cited evidence, and reproduce the deployment from this repository.

## Later possibilities - outside the MVP

- Additional US equities.
- Read-only Alpaca MCP for live market context.
- Evaluated news sentiment.
- GDELT macro-event context.
- Paper-trading integration as a separate, explicitly controlled extension.
