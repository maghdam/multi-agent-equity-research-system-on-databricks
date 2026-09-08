# Multi-Agent Equity Research System on Databricks

> A production-oriented end-to-end portfolio project combining Databricks data engineering, agentic AI engineering, evaluation, and application delivery.

**Status:** ✅ Milestone 1 — Data Engineering complete · ✅ Milestone 2 — AI Engineering complete · ✅ Milestone 3 — Application Delivery complete

**Live Databricks App:** [Open the deployed Equity Research Workspace](https://equity-research-dev-7474654299884940.aws.databricksapps.com/)  
*Databricks authentication and app access are required; anonymous public access is not supported by Databricks Apps.*

## Overview

Equity research often requires analysts and investors to collect market prices, company fundamentals, regulatory filings, and recent news from separate sources. This project creates a private Databricks application that turns those sources into structured, cited research over US equities.

The application is designed as a research assistant. It will not execute trades, predict prices, or provide financial advice.

## Target user

The private application is built for the project owner as an individual investor/researcher who wants to research one company or compare two companies without manually assembling information from multiple systems. The public portfolio surface is the GitHub repository, documentation, tests, selected screenshots, and a link to the live private Databricks deployment. Because Databricks Apps do not support anonymous public access, external visitors can open and test the live app only when they have been granted Databricks/app access.

## MVP

The MVP:

- Support AAPL and MSFT.
- Ingest historical market data and recent news from Alpaca.
- Ingest company fundamentals and selected filing sections from SEC EDGAR.
- Process data through Bronze, Silver, and Gold Delta tables.
- Provide structured financial analytics plus Retrieval-Augmented Generation (RAG) over validated news and SEC filing evidence with citations.
- Coordinate a Supervisor, Market Analyst, and Company Researcher with LangGraph.
- Presents results in a private Databricks Dash workspace with normalized market charts, validated cited reports, publication-safe evidence provenance, session-bound grounded follow-up chat, and privacy-safe application telemetry.

The MVP will not include trading execution, price prediction, portfolio optimization, GDELT, cTrader, or live Alpaca MCP access.

## Current progress

- **Bronze:** 4/4 MVP datasets implemented and live-verified.
- **Silver:** 4/4 MVP datasets implemented and live-verified: `daily_prices`, `news_articles`, `company_facts`, and `filing_sections`.
- **Gold:** 2/2 analytical metric tables implemented and live-verified: `market_metrics` and `fundamental_metrics`.
- **Daily market/news refresh:** scheduled at 01:00 America/New_York Tuesday-Saturday, with incremental Bronze ingestion, Silver/Gold rebuilds, and an automated quality/freshness/lineage verification gate. The first real periodic scheduler run completed successfully end-to-end.
- **Weekly SEC/fundamentals refresh:** scheduled at 02:00 America/New_York Sunday, with SEC company-facts and selected 10-K ingestion, Silver rebuilds, Gold fundamental metrics, and a final freshness/coverage/lineage verification gate. The full DAG is manually live-verified; the first periodic Sunday execution is pending.
- **Milestone 1 — Data Engineering:** complete. Bronze, Silver, Gold, CI, scheduled refresh orchestration, quality/freshness/lineage gates, safe replay behavior, and controlled deployment verification are all implemented and verified. The deployment gate was executed from the CI-tested `main` commit `caa3dcb` and completed with a converged bundle plan plus a successful serverless Spark smoke test.
- **Operational audit policy:** the MVP uses fail-before-publication validation rather than partial publication plus quarantine tables. Immutable Bronze provenance, validation diagnostics, deterministic replay, Databricks job history, and final verification gates provide the required operational evidence; dedicated row-level rejection tables are deferred until a mixed valid/invalid batch workflow requires them.
- **Milestone 2 — AI Engineering:** complete. The deterministic RAG corpus, managed GTE embeddings/AI Search index, independent retrieval holdout, controlled Gold/retrieval tools, GPT OSS 20B Market Analyst and Company Researcher workers, deterministic LangGraph Supervisor, GPT OSS 120B terminal synthesis, report provenance validation, bounded repair/fallback, MLflow tracing, route-aware retrieval relevance/sufficiency, trace-aware narrative grounding, controlled E3-E6 failure/security evaluation, and the final E1/E2 managed regression baseline are implemented and live-verified. Pull-request CI now exposes a dedicated 107-test credential-free AI-evaluation gate plus the full 482-test repository suite; GitHub Actions run #25 passed both with Ruff clean on Python 3.14.7. Credentialed Databricks SQL, Vector Search, and model evaluations remain deliberately separate, bounded live checks.
- **Milestone 3 — Application Delivery:** complete. The configuration-driven Dash workspace is deployed privately on Databricks Apps and live-verified for single-company and AAPL/MSFT comparison research. It renders controlled Gold metrics, normalized Silver price history, validated cited reports, publication-safe evidence cards, signed session-bound follow-up answers, fixed-category feedback, and bounded `APP_EVENT` telemetry. The final PR CI passed, the milestone was merged to `main` as `89bc3df`, and the exact merged snapshot was redeployed and live-smoke-tested successfully on 2026-09-07.
- Detailed implementation evidence and run links are tracked in [PLAN.md](PLAN.md).

## Portfolio preview

### AAPL vs MSFT research workspace

![AAPL vs MSFT comparison overview](docs/screenshots/01-comparison-overview.png)

### Normalized market comparison

![AAPL vs MSFT normalized 60-session market comparison](docs/screenshots/02-market-comparison.png)

### Validated cited research report

![Validated AAPL vs MSFT research report](docs/screenshots/03-research-report.png)

## Databricks platform architecture in practice

### Automated daily market & news pipeline

Bronze ingestion → Silver transformation → Gold market metrics → automated verification.

![Databricks daily market and news refresh workflow](docs/screenshots/08-databricks-daily-refresh-workflow.png)

### Automated weekly fundamentals & SEC filings pipeline

Company facts + SEC filings → Silver transformations → Gold fundamentals → automated verification.

![Databricks weekly fundamentals and SEC filings workflow](docs/screenshots/09-databricks-weekly-fundamentals-workflow.png)

### Unity Catalog — real Bronze, Silver, Gold, and AI/RAG assets

![Databricks Catalog showing the implemented medallion and AI/RAG assets](docs/screenshots/06-databricks-catalog.png)

### MLflow GenAI evaluation — final managed E1/E2 regression baseline

The final managed evaluation run `spiffy-rat-765` (`248395fd300d449ab98d496a4a39fcdc`) keeps the full Databricks metrics table readable across four screenshots. Click any image to inspect it at full resolution.

<table>
<tr>
<td width="50%"><a href="docs/screenshots/07-mlflow-evaluation-1.png"><img src="docs/screenshots/07-mlflow-evaluation-1.png" alt="MLflow evaluation metrics part 1"></a></td>
<td width="50%"><a href="docs/screenshots/07-mlflow-evaluation-2.png"><img src="docs/screenshots/07-mlflow-evaluation-2.png" alt="MLflow evaluation metrics part 2"></a></td>
</tr>
<tr>
<td width="50%"><a href="docs/screenshots/07-mlflow-evaluation-3.png"><img src="docs/screenshots/07-mlflow-evaluation-3.png" alt="MLflow evaluation metrics part 3"></a></td>
<td width="50%"><a href="docs/screenshots/07-mlflow-evaluation-4.png"><img src="docs/screenshots/07-mlflow-evaluation-4.png" alt="MLflow evaluation metrics part 4"></a></td>
</tr>
</table>

| Final evaluation signal | Mean |
| --- | ---: |
| Report section grounding contract | 1.000 |
| Safety | 1.000 |
| Retrieval trace sufficiency | 1.000 |
| Relevance to query | 1.000 |
| Narrative trace groundedness | 1.000 |
| Required report sections | 1.000 |
| Overall retrieval relevance | 0.861 |
| Retrieval empty-route count | 0 |

The non-perfect retrieval-relevance score is retained deliberately: the portfolio shows the measured precision/recall tradeoff rather than hiding it behind only perfect metrics.

See the [portfolio demo walkthrough](docs/PORTFOLIO_DEMO.md) for the evidence-provenance, grounded follow-up, evaluation, operations, and reproduction walkthrough.

## Architecture

```mermaid
flowchart TB
    sources["Sources<br/>Alpaca Market Data + News<br/>SEC Company Facts + Filings"]
    milestone1["Milestone 1 — Data Engineering ✅"]
    bronze["Bronze"]
    silver["Silver"]
    gold["Gold metrics"]
    corpus["RAG corpus<br/>(news + filings)"]
    milestone2["Milestone 2 — AI Engineering ✅"]
    gold_tools["Controlled Gold tools"]
    vector_search["Vector Search / RAG"]
    market_analyst["Market Analyst<br/>GPT OSS 20B"]
    company_researcher["Company Researcher<br/>GPT OSS 20B"]
    supervisor["LangGraph Supervisor"]
    synthesis["GPT OSS 120B"]
    validation["Deterministic validation<br/>Numeric fidelity / provenance<br/>Repair + fallback"]
    report["Grounded cited report"]
    traces["MLflow traces"]
    evaluation["MLflow evaluation"]
    regression["CI / regression"]
    app["Milestone 3 — Databricks App ✅<br/>Charts · cited report · grounded follow-up<br/>GPT OSS 120B follow-up over signed active research context"]

    sources --> milestone1 --> bronze --> silver
    silver --> gold
    silver --> corpus
    gold --> milestone2
    corpus --> milestone2
    milestone2 --> gold_tools --> market_analyst
    milestone2 --> vector_search --> company_researcher
    market_analyst --> supervisor
    company_researcher --> supervisor
    supervisor --> synthesis --> validation --> report
    report --> traces
    report --> evaluation
    traces --> regression
    evaluation --> regression
    regression --> app
```

Gold is intentionally **not** a one-to-one mirror of Silver. Structured price and fundamental data feed analytical Gold tables, while validated news and filing text primarily become retrieval/indexing assets for the AI layer.

## Expected output

A user can ask:

> Compare Apple and Microsoft over the last six months. Which had stronger market and financial performance, what recent developments matter, and what are the principal risks?

The application returns:

- Market-return, volatility, drawdown, and trend comparisons.
- Fundamental-performance comparisons.
- Relevant filing and news evidence with dates and citations.
- A concise research summary and stated limitations.
- Follow-up answers grounded in the retrieved evidence.

## Technology

- Databricks and Delta Lake
- Bronze-Silver-Gold architecture
- Python, PySpark, and SQL
- Alpaca Market Data and News APIs
- SEC EDGAR APIs
- LangGraph multi-agent orchestration
- Retrieval-Augmented Generation (RAG) with deterministic research documents/chunks, embeddings, and vector retrieval for filings and news
- Databricks Foundation Model APIs: GTE Large (En) embedding baseline, GPT OSS 20B workers, GPT OSS 120B terminal synthesis
- MLflow 3 tracing and GenAI evaluation with deterministic retrieval metrics, code-based scorers, and LLM judges
- Automated data-quality and agent evaluations

## Implementation

Development follows one end-to-end workflow:

1. **Project foundations:** scope, architecture, repository, and Databricks smoke test.
2. **Data Engineering:** source contracts, Bronze/Silver/Gold pipelines, quality, scheduling, and deployment checks.
3. **AI Engineering:** retrieval and tools, the multi-agent workflow, tracing, and evaluation.
4. **Application delivery:** private Databricks App, controlled presentation adapters, signed follow-up sessions, privacy-safe telemetry, publication audit, deployment verification, and reproducible portfolio demonstration.

Each milestone has a tested completion gate. See [PLAN.md](PLAN.md) for progress, [DATA_CONTRACTS.md](DATA_CONTRACTS.md) for data and RAG corpus rules, [docs/AI_RESEARCH_CONTRACT.md](docs/AI_RESEARCH_CONTRACT.md) for behavioral requirements, [docs/MODEL_STRATEGY.md](docs/MODEL_STRATEGY.md) for model allocation and evaluation strategy, [docs/EVALUATION_RUNBOOK.md](docs/EVALUATION_RUNBOOK.md) for the credential-free versus credentialed evaluation boundary, [docs/APP_DESIGN.md](docs/APP_DESIGN.md) for the application product/runtime design, [docs/APP_OPERATIONS.md](docs/APP_OPERATIONS.md) for telemetry and secure-runtime operations, [docs/APP_RELEASE_RUNBOOK.md](docs/APP_RELEASE_RUNBOOK.md) for release/reproduction checks, [docs/PORTFOLIO_DEMO.md](docs/PORTFOLIO_DEMO.md) for the concise employer-facing walkthrough, [docs/REPOSITORY_GUIDE.md](docs/REPOSITORY_GUIDE.md) for the component map, and [docs/DATA_USAGE_PERMISSIONS.md](docs/DATA_USAGE_PERMISSIONS.md) for the private-runtime/public-portfolio publication boundary.

## Local Alpaca access check

This read-only check requests daily AAPL and MSFT bars for
2026-08-27 using the SIP feed, split adjustment, and USD.

The successful local check used Python 3.14.7. This is not a
Databricks runtime requirement.

### Setup — Windows PowerShell

With Python installed, run from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create a `.env` file in the repository root and enter your
Alpaca paper-account credentials privately:

```dotenv
ALPACA_API_KEY=your_api_key_here
ALPACA_SECRET_KEY=your_secret_key_here
```

The `.env` file is ignored by Git. Never commit or share it.

### Run

```powershell
.\.venv\Scripts\python.exe scripts/check_alpaca_access.py
```

Expected output:

- `HTTP status: 200`
- One daily bar for AAPL and one for MSFT.
- `next_page_token: null`

Inspect all three conditions; HTTP 200 alone does not establish
sample completeness. If the check fails, investigate without
automatically switching feeds.

This check does not place trades, create tables, run on Databricks,
or validate the full data contract.

## Local Alpaca news access check

This read-only script requests one page of AAPL/MSFT news for
the fixed UTC window specified in the script: August 24–28, 2026.
It requests up to three articles, including content when available.

Reuse the dependencies and private `.env` configuration described
above. No additional credentials or packages are required.

Run from the repository root using one of these commands.

With the `.venv` setup above:

```powershell
.\.venv\Scripts\python.exe scripts/check_alpaca_news_access.py
```

With an already active environment containing the dependencies,
such as the project's local `db` environment:

```powershell
python scripts/check_alpaca_news_access.py
```

Verified sample output:

```text
HTTP status: 200
Articles returned: 3
More pages available: True
```

The remaining output shows article metadata and the types and
lengths of text fields. It does not print credentials, headlines,
summaries, or article bodies.

`More pages available: True` is expected for the verified sample:
the script intentionally inspects only the first page.

A future response may differ if provider data or access changes.
This check does not establish complete news coverage, validate
the full contract, or create Databricks tables.

See [DATA_CONTRACTS.md](DATA_CONTRACTS.md) for the documented
schema, validation rules, and content-use boundaries.

## Local SEC access checks

<details>
<summary>Setup, commands, and expected output</summary>

Reuse the Python dependencies described above. In your private
`.env`, configure a project identifier and real contact email,
replacing the placeholder locally:

```dotenv
SEC_USER_AGENT="EquityResearchLearningProject your-email@example.com"
```

Never commit `.env` or its private values. The SEC diagnostics
do not send Alpaca credentials.

From the repository root, with your project environment active:

```powershell
python scripts/check_sec_access.py
python scripts/check_sec_company_facts_access.py
```

With the documented `.venv` setup, use
`.\.venv\Scripts\python.exe` instead of `python`.

Expected results:

- Directory check: HTTP 200, AAPL CIK `0000320193`,
  and MSFT CIK `0000789019`.
- Company-facts check: HTTP 200 for each company, matching CIKs,
  concept metadata, units, observation counts, and up to two
  sample observations per inspected concept/unit.

Inspect the output; HTTP 200 alone does not validate the contract.
Counts and sample data may change. Samples follow response order
and are not a latest-value selection.

These are local, read-only source diagnostics. They do not save
response payloads, create Databricks tables, or implement the
Bronze/Silver/Gold pipeline.

</details>

## Disclaimer

This project is for educational and portfolio demonstration purposes. Its outputs are informational and are not investment advice.

## License

This project is licensed under the [MIT License](LICENSE).
