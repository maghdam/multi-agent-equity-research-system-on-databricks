# Multi-Agent Equity Research System on Databricks - Implementation Plan

The MVP is intentionally limited to AAPL and MSFT. A milestone is complete only when its acceptance criteria are met.

## Milestone 1 - Data platform

- [ ] Define source schemas and data contracts.
- [ ] Ingest Alpaca historical prices into Bronze.
- [ ] Ingest Alpaca company news into Bronze.
- [ ] Ingest SEC fundamentals and selected filings into Bronze.
- [ ] Create cleaned, deduplicated Silver tables.
- [ ] Create Gold market and fundamental metrics.
- [ ] Add data-quality tests and freshness checks.
- [ ] Schedule the pipeline in Databricks.

**Acceptance criteria:** AAPL and MSFT data can be rebuilt from Bronze, passes validation, and produces reproducible Gold metrics with an `as_of` timestamp.

## Milestone 2 - Retrieval and multi-agent workflow

- [ ] Create curated filing and news documents with metadata.
- [ ] Chunk documents and create a vector index.
- [ ] Implement controlled SQL and retrieval tools.
- [ ] Implement the Market Analyst.
- [ ] Implement the Company Researcher.
- [ ] Implement the Supervisor workflow in LangGraph.
- [ ] Require structured outputs, citations, and error handling.
- [ ] Create and run an agent evaluation dataset.

**Acceptance criteria:** A comparison request produces a grounded report whose numerical claims match Gold tables and whose textual claims include valid sources.

## Milestone 3 - Application and deployment

- [ ] Build stock and period selection controls.
- [ ] Display market charts and comparison metrics.
- [ ] Display the generated research report and citations.
- [ ] Add follow-up chat over the report evidence.
- [ ] Add logging, monitoring, and secret management.
- [ ] Deploy the application on Databricks.
- [ ] Add screenshots, a short demo, and reproduction instructions.

**Acceptance criteria:** A new user can open the deployed application, compare AAPL and MSFT, inspect cited evidence, and reproduce the deployment from this repository.

## Later possibilities - outside the MVP

- Additional US equities.
- Read-only Alpaca MCP for live market context.
- Evaluated news sentiment.
- GDELT macro-event context.
- Paper-trading integration as a separate, explicitly controlled extension.