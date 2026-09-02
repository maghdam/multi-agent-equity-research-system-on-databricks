# Multi-Agent Equity Research System on Databricks - Implementation Plan

Build a small research app that compares AAPL and MSFT using market data, company fundamentals, and cited news/filing evidence. See [README.md](README.md) for the architecture and expected output.

**Current position:** Milestone 1. The Bronze price, news, and SEC company-facts ingestion jobs are complete for the MVP: 59 offline tests cover configuration, requests, responses, pagination, retries, date windows, and SEC HTTP policies; append-only provenance and safe-rerun behavior are verified in Databricks for prices, news, and company facts. Remaining Milestone 1 work: SEC filings ingestion, then Silver transformations and validation.

**Next:** Build Bronze SEC filings ingestion using the same raw-source provenance, conservative SEC access policy, and bounded verification approach.

## Working approach

For each meaningful step: explain its purpose, implement one coherent piece, test normal behavior and important failures, then record the result and tick the task. Keep teaching and routine diagnostic output in chat. Keep lasting decisions, reproducible checks, and milestone evidence in the repository.

Develop locally, version code and bundle configuration in GitHub, and run deployed workloads in Databricks. A draft or access check is not a working pipeline. Each milestone ends with a tested gate. AI requirements and evaluation examples can be drafted early, but agent implementation depends on a minimum validated data slice.

This structure adapts the [Databricks medallion architecture](https://docs.databricks.com/aws/en/lakehouse/medallion), [CI/CD workflow](https://docs.databricks.com/aws/en/dev-tools/ci-cd/flows), and [agent lifecycle](https://docs.databricks.com/aws/en/agents/agents-dev-lifecycle) to the MVP's scale.

## Phase 0 - Project foundations: complete

- [x] Define the problem, intended user, MVP output, exclusions, and architecture.
- [x] Set up the local repository, GitHub remote, and Databricks development bundle.
- [x] Validate, deploy, and run the serverless Spark smoke test; commit and push the verified checkpoint.

**Gate:** The repository and Databricks deployment path work from recorded commit `e0f8eb5`; [successful smoke-test run](https://dbc-5e700074-422e.cloud.databricks.com/jobs/962241359191284/runs/277255524412899?o=7474654299884940) (workspace access required).

## Milestone 1 - Data Engineering: trustworthy data (in progress)

### Design the data products

- [x] Verify local Alpaca prices/news and SEC directory/company-facts/filing-metadata access; inspect one AAPL filing document.
- [x] Define the source-to-Bronze-to-Silver-to-Gold inventory and review draft price, news, and company-facts contracts in [DATA_CONTRACTS.md](DATA_CONTRACTS.md).
- [ ] Finish filing selection, amendment handling, extraction boundaries, and representative tests.
- [x] Create the shared AAPL/MSFT configuration and validated loader; verify the real configuration and configuration-only expansion with four passing offline tests.

### Build the transformations

- [ ] Confirm provider storage, retention, and processing permissions before sustained ingestion. Use synthetic fixtures if permissions remain unresolved.
- [x] Configure development runtime secrets and verify serverless Alpaca access without exposing credentials.
- [x] Deploy and SQL-verify one bounded Bronze price-response append for AAPL and MSFT; see the [successful development run](https://dbc-5e700074-422e.cloud.databricks.com/jobs/260103230393545/runs/898971715711565?o=7474654299884940) (workspace access required).
- [x] Add reusable price-request construction, response parsing, and bounded cycle-safe pagination with 18 passing offline tests; verify a [two-page development run](https://dbc-5e700074-422e.cloud.databricks.com/jobs/260103230393545/runs/686396093451117?o=7474654299884940) and its continuation-token chain through SQL (workspace access required).
- [x] Add bounded retry and rate-limit handling with deterministic policy tests; verify a [routine retry-enabled development run](https://dbc-5e700074-422e.cloud.databricks.com/jobs/260103230393545/runs/360486532686779?o=7474654299884940) (workspace access required).
- [x] Add configurable backfill and rolling incremental windows with 26 passing offline tests; verify an [incremental run](https://dbc-5e700074-422e.cloud.databricks.com/jobs/260103230393545/runs/1002689227433019?o=7474654299884940) and an identical [safe rerun](https://dbc-5e700074-422e.cloud.databricks.com/jobs/260103230393545/runs/424518002298178?o=7474654299884940) preserved under distinct ingestion IDs (workspace access required).
- [ ] Demonstrate that the first price transformation accepts a third compatible fixture equity without stock-specific pipeline changes; do not expand live scope.
- [x] Build Bronze news ingestion using the same raw-envelope, reusable-client, retry, pagination, and verification conventions.
  - Reusable Alpaca news request/response/pagination logic covered by offline tests.
  - Shared Alpaca HTTP retry policy extracted and reused by price/news ingestion.
  - Backfill and rolling 7-day incremental news windows implemented.
  - `news_responses` stores append-only raw response envelopes with request, pagination, payload-hash, retrieval-time, and ingestion-run provenance.
  - 45 offline tests pass and `databricks bundle validate -t dev` succeeds.
  - Live bounded backfill (AAPL/MSFT, 2026-08-24–2026-08-28, page limit 3): 84 articles across 29 response pages; full continuation-token chain verified; see [backfill run](https://dbc-5e700074-422e.cloud.databricks.com/jobs/752273509776159/runs/541455067040587?o=7474654299884940) (workspace access required).
  - Live incremental run (7-day overlap, page limit 50): 105 articles across 3 pages (50/50/5).
  - Safe rerun verified: identical historical request produced 29/29 identical payload hashes while preserving both runs under distinct ingestion IDs and distinct response IDs; see [rerun](https://dbc-5e700074-422e.cloud.databricks.com/jobs/752273509776159/runs/764960512099615?o=7474654299884940) (workspace access required).
- [x] Build Bronze SEC company-facts ingestion using the same raw-source provenance and conservative access policy.
  - Reusable SEC company-facts request path construction and envelope parsing covered by offline tests.
  - Shared SEC HTTP access policy (User-Agent header, minimum 200ms spacing, bounded retry backoff) implemented in `sec_http.py`.
  - `company_facts_responses` stores append-only raw SEC JSON response snapshots with CIK, entity name, payload hash, retrieval timestamp, and ingestion-run provenance.
  - 59 offline tests pass and `databricks bundle validate -t dev` succeeds.
  - Live Databricks run appends exactly 2 raw company-facts snapshots for AAPL and MSFT with correct CIK/entity mappings and HTTP 200 OK responses; see [company-facts run](https://dbc-5e700074-422e.cloud.databricks.com/jobs/29449776245070/runs/1091317525267833?o=7474654299884940) (workspace access required).
  - Safe rerun verified: immediate rerun produced identical payload hashes while preserving both runs under distinct ingestion run IDs and response IDs.
- [ ] Add Bronze selected SEC filings using the same raw-source provenance conventions.
- [ ] Build Silver validation and deduplication with rejection reporting, safe version selection, and replay tests.
- [ ] Define comparable periods and filing versions; build Gold market and fundamental metrics with clear `as_of` timestamps and coverage limits.

### Automate and verify

- [ ] Add GitHub Actions CI for formatting, linting, contract/unit tests, and bundle validation on pull requests and `main`; no live credentials required.
- [ ] Configure initial backfills and scheduled incremental refreshes; verify quality, freshness, missing-data reporting, failure visibility, and safe reruns.
- [ ] Add controlled deployment from a CI-tested `main` commit: deploy the bundle to `dev`, run verification, and record the commit/run link. Use a documented manual CLI fallback if Free Edition cannot authenticate unattended.

**Gate:** AAPL and MSFT can be rebuilt from Bronze into tested Silver and Gold outputs. Data quality, replay, freshness, CI, and deployment checks pass, and code deployment remains separate from scheduled data refresh.

**Expansion rule:** Ingestion, scope checks, analytics, tools, and UI use the same equities configuration. Adding a compatible stock requires configuration plus identifier, backfill, and readiness checks—not stock-specific pipeline code. Provider news tags never expand the universe automatically.

## Milestone 2 - AI Engineering: grounded research (pending)

- [ ] Define the report structure, agent responsibilities, important failure behavior, and a small representative evaluation set.
- [ ] Confirm indexing/model-processing permissions; prepare cleaned news/filing documents, chunks, metadata, and a vector index.
- [ ] Build and independently test controlled SQL and retrieval tools that check configured symbols and data readiness.
- [ ] Implement the Market Analyst, Company Researcher, and LangGraph Supervisor with structured reports, citations, and clear errors.
- [ ] Add MLflow tracing and evaluate numerical correctness, retrieval relevance, citation support, missing/stale evidence, tool routing, latency, and cost.
- [ ] Correct measured weaknesses and rerun the same evaluations to check for regressions.
- [ ] Extend CI with deterministic tool tests and offline evaluations; run credentialed live-model evaluations separately with controlled usage.

**Gate:** Representative one-stock and comparison requests produce grounded reports: numbers match Gold, narrative claims have supporting citations, and missing or stale evidence is disclosed.

## Milestone 3 - Application and end-to-end delivery (pending)

- [ ] Build configured stock/period selection, charts, comparison metrics, a cited report, and evidence-grounded follow-up chat.
- [ ] Add application logging, monitoring, feedback collection, and secure secret handling.
- [ ] Confirm public display/redistribution permissions for provider data and derived outputs; use clearly labelled synthetic demo data if unresolved.
- [ ] Deploy the app on Databricks and extend controlled deployment with startup, health, and end-to-end verification.
- [ ] Add screenshots, example output, a short demo, and concise reproduction instructions covering CI, authentication, release checks, and redeploying a known-good version.

**Gate:** An intended user can access the deployed app, research one supported stock or compare both, inspect citations, and follow the repository's reproduction/deployment instructions. Access requirements and Free Edition limitations are explicit.

## Outside the MVP

Broader live stock coverage, sentiment scoring, GDELT, cTrader, live Alpaca MCP, price prediction, portfolio optimization, and trading execution.
