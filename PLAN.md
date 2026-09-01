# Multi-Agent Equity Research System on Databricks - Implementation Plan

Build a small research app that compares AAPL and MSFT using market data, company fundamentals, and cited news/filing evidence. See [README.md](README.md) for the architecture and expected output.

**Current position:** Milestone 1. Development setup, local source-access checks, and the shared AAPL/MSFT configuration/loader are complete. Price, news, and company-facts contracts are reviewed drafts; filing-text rules are partly defined. Production ingestion is not implemented.

**Next:** Review and commit the configuration/documentation checkpoint; then build the first Bronze price job. Finish the remaining filing rules when implementing that source.

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

- [ ] Confirm provider storage/retention/processing permissions and configure runtime secrets before persistent ingestion. Use synthetic fixtures if permissions remain unresolved.
- [ ] Build the first Bronze price job with reusable request logic, pagination, bounded retries/rate limits, raw storage, and ingestion metadata.
- [ ] Demonstrate that the first price transformation accepts a third compatible fixture equity without stock-specific pipeline changes; do not expand live scope.
- [ ] Add Bronze news, company facts, and selected filings using the same ingestion conventions.
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
