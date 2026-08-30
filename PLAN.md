# Multi-Agent Equity Research System on Databricks - Implementation Plan

The MVP is intentionally limited to AAPL and MSFT. A milestone is complete only when its acceptance criteria are met.

**Current step:** Milestone 1 - daily price contract examples reviewed; local Git checkpoint pending.

**Next small step:** Stage, review, and commit the daily price contract draft and plan updates locally before the API access check.

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
  - [ ] Commit the reviewed daily price contract draft and plan updates as a local checkpoint.
  - [ ] Verify historical SIP access with an authenticated sample request.
  - [ ] Finalize decimal precision and scale after inspecting source samples.
  - [ ] Define the Alpaca company-news contract.
  - [ ] Define the SEC company-facts and selected-filings contracts.
- [ ] Add basic GitHub Actions CI alongside the contracts: formatting, linting, and contract/unit tests on pull requests and `main`, using fixtures without live API credentials.
- [ ] Ingest Alpaca historical prices into Bronze.
- [ ] After the first Bronze job works, verify secure non-interactive Databricks authentication supported by Free Edition; document manual CLI deployment as the fallback if unavailable.
- [ ] Add controlled CD: manually trigger deployment of a CI-tested `main` commit, validate the bundle, deploy to `dev`, and run a verification job. Record the commit and Databricks run link.
- [ ] Ingest Alpaca company news into Bronze.
- [ ] Ingest SEC fundamentals and selected filings into Bronze.
- [ ] Create cleaned, deduplicated Silver tables.
- [ ] Create Gold market and fundamental metrics.
- [ ] Add data-quality tests and freshness checks.
- [ ] Schedule the pipeline in Databricks.

**Acceptance criteria:** AAPL and MSFT data can be rebuilt from Bronze, passes validation, and produces reproducible Gold metrics with an `as_of` timestamp.

**CI/CD acceptance criteria:** CI passes on the tested commit. Deployment and post-deployment verification are reproducible through GitHub Actions, or through the documented manual fallback if Free Edition authentication prevents unattended deployment. Deployment does not replace the scheduled data-refresh job.

## Milestone 2 - Retrieval and multi-agent workflow

- [ ] Create curated filing and news documents with metadata.
- [ ] Chunk documents and create a vector index.
- [ ] Implement controlled SQL and retrieval tools.
- [ ] Implement the Market Analyst.
- [ ] Implement the Company Researcher.
- [ ] Implement the Supervisor workflow in LangGraph.
- [ ] Require structured outputs, citations, and error handling.
- [ ] Create and run an agent evaluation dataset.
- [ ] Extend CI with agent/tool unit tests and offline evaluations; run live-model evaluations separately with controlled credentials and usage limits before release.

**Acceptance criteria:** A comparison request produces a grounded report whose numerical claims match Gold tables and whose textual claims include valid sources.

## Milestone 3 - Application and deployment

- [ ] Build stock and period selection controls.
- [ ] Display market charts and comparison metrics.
- [ ] Display the generated research report and citations.
- [ ] Add follow-up chat over the report evidence.
- [ ] Add logging, monitoring, and secret management.
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
