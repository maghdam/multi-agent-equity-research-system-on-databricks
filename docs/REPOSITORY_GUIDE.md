# Repository Guide

This guide maps the repository by **architectural component and problem solved**.

The repository deliberately organizes files by artifact type:

- `src/equity_research/` contains reusable domain and application logic;
- `src/` contains Databricks job entry points and transformation runners;
- `resources/` contains Databricks Asset Bundle resource definitions;
- `scripts/` contains local access checks and controlled live smoke/evaluation runners;
- `tests/` contains credential-free deterministic and integration-style tests;
- `config/` contains shared project configuration;
- `.github/workflows/` contains CI;
- `docs/` and root Markdown files record contracts, architecture, decisions, and implementation evidence.

A logical component therefore often spans several folders. This guide provides the
cross-folder view: **what the component does, which files implement it, which
infrastructure runs it, and which tests verify it**.

For chronological implementation status and live-run evidence, see `PLAN.md`.
For data-product rules, see `DATA_CONTRACTS.md`. For AI behavior and model
strategy, see `docs/AI_RESEARCH_CONTRACT.md` and `docs/MODEL_STRATEGY.md`.

---

## 1. End-to-end architecture

```text
Alpaca prices/news + SEC company facts/filings
                    |
                    v
               Bronze Delta
      raw immutable provider history
                    |
                    v
               Silver Delta
       validated business records
          |                 |
          v                 v
   Gold metrics       RAG corpus
 authoritative          research_documents
 structured values      research_chunks
          |                 |
          v                 v
 controlled Gold      AI Search / HYBRID
      tools              retrieval
          |                 |
          v                 v
   Market Analyst     Company Researcher
    GPT OSS 20B         GPT OSS 20B
          |                 |
          +--------+--------+
                   |
                   v
        deterministic LangGraph
             Supervisor
                   |
                   v
        validated SupervisorState
                   |
                   v
       GPT OSS 120B terminal synthesis
                   |
                   v
       deterministic report validation
        + one bounded model repair
        + deterministic fallback
                   |
                   v
          grounded cited report
```

The project separates **factual authority** from **language generation**:

- structured numerical claims are authorized only by Gold-backed controlled tools;
- narrative claims are authorized only by controlled RAG evidence;
- LLM outputs are application-validated before they become worker findings or final
  report sections.

---

## 2. Repository conventions

| Location | Main role |
|---|---|
| `config/` | Shared supported-universe configuration |
| `src/equity_research/` | Reusable clients, transformations, RAG, tools, agents, Supervisor, report contracts |
| `src/*.py` | Databricks job entry points and operational verification runners |
| `resources/*.yml` | Databricks schemas, jobs, schedules, and Vector Search resources |
| `scripts/` | Local provider diagnostics, live tool/agent/graph/report smoke runners, retrieval evaluation |
| `tests/` | Credential-free unit, contract, parser, orchestration, and integration-style tests |
| `.github/workflows/ci.yml` | Pull-request and `main` CI |
| `databricks.yml` | Asset Bundle root configuration and target variables |
| `PLAN.md` | Current implementation position, completed gates, live-run evidence, next work |
| `DATA_CONTRACTS.md` | Bronze/Silver/Gold/RAG data contracts |
| `docs/AI_RESEARCH_CONTRACT.md` | Required AI behavior, evidence rules, failure behavior, evaluation cases |
| `docs/MODEL_STRATEGY.md` | Model allocation, retrieval/model baselines, evaluation strategy |
| `docs/DATA_USAGE_PERMISSIONS.md` | Private-runtime and public-portfolio source-content boundary |
| `docs/BUILD_GUIDE.md` | Build/development guidance |
| `docs/REPOSITORY_GUIDE.md` | This cross-folder component map |

The current flat `src/equity_research/` package is intentional. File prefixes make
local ownership visible, while this guide provides the architectural grouping.
A deeper package hierarchy should be introduced only if navigation/import complexity
becomes a demonstrated problem.

---

# Data Engineering

## 3. Shared equity configuration and scope

### Question solved

How does every pipeline, tool, and agent agree on the supported companies and their
provider identifiers?

### Files

**Configuration**

- `config/equities.json` — configured AAPL/MSFT universe and provider identifiers.

**Reusable logic**

- `src/equity_research/config.py` — loads and validates the shared configuration.

**Tests**

- `tests/test_equity_config.py` — configuration parsing, normalization, and
  configuration-only expansion behavior.

### Guarantee

Provider tags or model output do not expand the supported universe automatically.
Ingestion, transformations, tools, and AI request validation all use the same
configured equity set.

---

## 4. Provider HTTP/client layer

### Question solved

How are Alpaca and SEC requests constructed, retried, rate-limited, parsed, and
validated before ingestion logic uses them?

### Alpaca files

- `src/equity_research/alpaca_http.py` — shared HTTP retry/rate-limit behavior.
- `src/equity_research/alpaca_prices.py` — price request construction, response
  parsing, pagination.
- `src/equity_research/alpaca_news.py` — news request construction, parsing,
  pagination.

**Tests**

- `tests/test_alpaca_http.py`
- `tests/test_alpaca_prices.py`
- `tests/test_alpaca_news.py`

### SEC files

- `src/equity_research/sec_http.py` — conservative SEC request policy,
  identification header, spacing, retries, response diagnostics.
- `src/equity_research/sec_company_facts.py` — company-facts request and parsing.
- `src/equity_research/sec_filings.py` — submissions parsing, exact 10-K selection,
  filing-document URL construction.

**Tests**

- `tests/test_sec_http.py`
- `tests/test_sec_company_facts.py`
- `tests/test_sec_filings.py`

### Local access diagnostics

- `scripts/check_alpaca_access.py`
- `scripts/check_alpaca_news_access.py`
- `scripts/check_sec_access.py`
- `scripts/check_sec_company_facts_access.py`
- `scripts/check_sec_filings_access.py`
- `scripts/check_sec_filing_document_access.py`

These diagnostics establish provider/runtime access without replacing the data
contracts or transformation tests.

---

## 5. Bronze ingestion

### Question solved

How do raw provider responses enter the lakehouse with immutable retrieval provenance?

### Price ingestion

**Job entry point**

- `src/bronze_price_ingestion.py`

**Reusable client**

- `src/equity_research/alpaca_prices.py`
- `src/equity_research/alpaca_http.py`

**Bundle resource**

- `resources/bronze_price_ingestion.job.yml`

### News ingestion

**Job entry point**

- `src/bronze_news_ingestion.py`

**Reusable client**

- `src/equity_research/alpaca_news.py`
- `src/equity_research/alpaca_http.py`

**Bundle resource**

- `resources/bronze_news_ingestion.job.yml`

### SEC company-facts ingestion

**Job entry point**

- `src/bronze_company_facts_ingestion.py`

**Reusable client**

- `src/equity_research/sec_company_facts.py`
- `src/equity_research/sec_http.py`

**Bundle resource**

- `resources/bronze_company_facts_ingestion.job.yml`

### Selected SEC filing ingestion

**Job entry point**

- `src/bronze_sec_filings_ingestion.py`

**Reusable client**

- `src/equity_research/sec_filings.py`
- `src/equity_research/sec_http.py`

**Bundle resource**

- `resources/bronze_sec_filings_ingestion.job.yml`

### Schema resource

- `resources/bronze.schema.yml`

### Core design

Bronze is append-only raw retrieval history. Response IDs, ingestion-run IDs,
request metadata, timestamps, provider identities, and payload/document hashes retain
exact retrieval provenance. Validation that requires business interpretation is kept
out of Bronze where possible.

---

## 6. Silver transformations

### Question solved

How does immutable raw provider history become deterministic, validated business
records suitable for analytics and RAG?

### Prices

- `src/equity_research/silver_prices.py` — deterministic price validation,
  business-key/version selection, conflict handling.
- `src/silver_price_transformation.py` — Databricks transformation entry point.
- `resources/silver_price_transformation.job.yml` — job resource.
- `tests/test_silver_prices.py` — transformation rules and replay behavior.

### News

- `src/equity_research/silver_news.py` — article validation, latest valid revision,
  symbol-scope derivation, conflict handling.
- `src/silver_news_transformation.py`
- `resources/silver_news_transformation.job.yml`
- `tests/test_silver_news.py`

### Company facts

- `src/equity_research/silver_company_facts.py` — configured-CIK validation,
  concept/unit filtering, period semantics, deterministic version selection.
- `src/silver_company_facts_transformation.py`
- `resources/silver_company_facts_transformation.job.yml`
- `tests/test_silver_company_facts.py`

### Filing sections

- `src/equity_research/silver_filing_sections.py` — latest filing/retrieval
  selection, 10-K identity checks, Item 1 / Item 1A extraction, cleanup and
  content-quality validation.
- `src/silver_filing_sections_transformation.py`
- `resources/silver_filing_sections_transformation.job.yml`
- `tests/test_silver_filing_sections.py`

### Schema resource

- `resources/silver.schema.yml`

### Core design

Silver uses fail-before-publication validation. Invalid or ambiguous snapshots do not
produce a partially trusted Silver table. Dedicated row-level quarantine tables are
deferred for the MVP because the current workflows publish only after whole-snapshot
validation succeeds.

---

## 7. Gold analytical metrics

### Question solved

Where do authoritative market and fundamental numbers used by the AI system come
from?

### Market metrics

- `src/equity_research/gold_market_metrics.py` — 1/5/20/60-session returns,
  volatility, drawdown, SMA/trend measures, aligned comparison-date semantics.
- `src/gold_market_metrics_transformation.py` — Databricks entry point.
- `resources/gold_market_metrics_transformation.job.yml`
- `tests/test_gold_market_metrics.py`

### Fundamental metrics

- `src/equity_research/gold_fundamental_metrics.py` — annual or
  annual-plus-YTD-minus-prior-YTD TTM construction, assets, profitability and
  growth/change metrics.
- `src/gold_fundamental_metrics_transformation.py`
- `resources/gold_fundamental_metrics_transformation.job.yml`
- `tests/test_gold_fundamental_metrics.py`

### Schema resource

- `resources/gold.schema.yml`

### Guarantee

Market/fundamental numerical claims in the AI layer are authorized only by these
controlled Gold products. The RAG subsystem is not a substitute for structured
financial metrics.

---

## 8. Scheduled orchestration and data verification

### Question solved

How are the separate ingestion/transformation jobs connected into repeatable refresh
workflows with a final quality/freshness/lineage gate?

### Daily market/news workflow

- `resources/daily_market_refresh.job.yml` — orchestrates price/news Bronze through
  Silver and market Gold.
- `src/daily_market_refresh_verification.py` — final freshness, coverage,
  uniqueness, common-market-date, scope and lineage verification.

### Weekly SEC/fundamentals workflow

- `resources/weekly_fundamentals_refresh.job.yml` — orchestrates SEC company facts
  and filings through Silver and fundamental Gold.
- `src/weekly_fundamentals_refresh_verification.py` — final source freshness,
  configured-company coverage, uniqueness, business recency and lineage checks.

### Supporting resources

- all corresponding Bronze/Silver/Gold job resource files under `resources/`.

### Design

The final verification task is a workflow gate rather than an informational report:
upstream jobs may have succeeded technically, but the parent refresh is not considered
healthy until the expected business-data state and lineage are verified.

---

# Retrieval-Augmented Generation

## 9. Research corpus

### Question solved

How do validated news articles and filing sections become deterministic, citation-ready
retrieval documents and chunks?

### Reusable logic

- `src/equity_research/research_documents.py` — deterministic research-document
  identities, source metadata and snapshot semantics.
- `src/equity_research/research_chunks.py` — cleaning/chunking, offsets, chunk IDs,
  text hashes and replay behavior.

### Databricks entry point

- `src/rag_research_corpus_transformation.py`

### Resources

- `resources/ai.schema.yml`
- `resources/rag_research_corpus_transformation.job.yml`
- `resources/rag_research_chunks.vector_search.yml`

### Tests

- `tests/test_research_documents.py`
- `tests/test_research_chunks.py`

### Guarantee

Chunk identity and provenance remain traceable back to validated Silver business
records and then to Bronze retrieval provenance. Real provider source text remains
inside the approved private-runtime boundary.

---

## 10. Retrieval evaluation

### Question solved

How do we measure whether Vector Search returns relevant evidence rather than relying
on anecdotal queries?

### Files

- `src/equity_research/retrieval_evaluation.py` — deterministic retrieval metrics
  and evaluation-case contracts.
- `scripts/run_live_retrieval_evaluation.py` — controlled live evaluation against
  the managed index.
- `tests/test_retrieval_evaluation.py`
- `tests/test_live_retrieval_evaluation.py`
- `tests/fixtures/` — reviewed/frozen test fixtures and labels where applicable.

### Current role

The independent six-case holdout established HYBRID retrieval as the provisional
baseline and identified near-duplicate evidence as a measured weakness. Future MLflow
evaluation should log these deterministic metrics rather than replacing them with an
LLM judge.

---

# Controlled AI Access Layer

## 11. Request scope and controlled tools

### Question solved

How can agents use project data without arbitrary SQL, unsupported symbols, stale
values, or unconstrained retrieval?

### Shared scope

- `src/equity_research/tool_scope.py` — validates one/two supported symbols,
  normalization, duplicates and unsupported requests.

### Structured Gold access

- `src/equity_research/structured_data_tools.py` — controlled market/fundamental
  tool contracts, readiness and freshness semantics.
- `src/equity_research/structured_data_access.py` — exact approved Gold projections
  and execution boundary.

### Controlled retrieval

- `src/equity_research/retrieval_tools.py` — bounded HYBRID retrieval, metadata
  filtering, evidence-record parsing, citation metadata and client-side scope checks.

### Databricks CLI adapter

- `src/equity_research/databricks_cli_runtime.py` — Statement Execution, Vector
  Search and model-serving CLI-backed runtime used without adding a Databricks Python
  SDK dependency.

### Tests

- `tests/test_structured_data_tools.py`
- `tests/test_tool_access_requests.py`
- `tests/test_databricks_tool_runtime.py`

### Live smoke

- `scripts/run_controlled_tool_smoke.py`

### Guarantees

- unsupported symbols fail before data access;
- SQL is limited to approved Gold tables/projections;
- stale/missing values are explicit states rather than silently usable numbers;
- retrieval is bounded, symbol/source filtered, and rechecked client-side;
- evidence IDs and citation metadata are application-controlled.

---

# Worker Agents

## 12. Market Analyst

### Question solved

How are authoritative Gold metrics converted into useful analytical findings without
allowing the model to redefine the numbers or their dates?

### Files

**Contracts and validation**

- `src/equity_research/market_analyst.py`

**Shared agent structures**

- `src/equity_research/agent_contracts.py`

**Prompt/schema configuration**

- `src/equity_research/worker_agent_prompts.py`

**Model runtime**

- `src/equity_research/worker_agent_runtime.py`

### Tests

- `tests/test_worker_agent_contracts.py`
- `tests/test_worker_agent_runtime.py`

### Live smoke

- `scripts/run_worker_agent_smoke.py`

### Validation boundary

GPT OSS 20B produces structured findings, but application validation checks symbol
scope, dataset/dimension, metric fields, exact as-of dates, readiness, non-null values,
and complete coverage of ready market/fundamental dimensions.

---

## 13. Company Researcher

### Question solved

How are retrieved news and SEC passages converted into grounded developments and
principal-risk findings without invented citations or source-text instructions?

### Files

**Contracts and validation**

- `src/equity_research/company_researcher.py`

**Shared agent structures**

- `src/equity_research/agent_contracts.py`

**Prompt/schema configuration**

- `src/equity_research/worker_agent_prompts.py`

**Model runtime**

- `src/equity_research/worker_agent_runtime.py`

### Tests

- `tests/test_worker_agent_contracts.py`
- `tests/test_worker_agent_runtime.py`

### Live smoke

- `scripts/run_worker_agent_smoke.py`

### Validation boundary

- retrieved source text is labeled `untrusted_text`;
- returned evidence IDs must already exist in controlled retrieval;
- recent developments use news evidence;
- filing-only Item 1A risks are `company_disclosed_risk`;
- `risk_context` requires news evidence;
- insufficient evidence becomes an explicit limitation rather than an unsupported
  finding.

---

# Supervisor and Final Report

## 14. Deterministic Supervisor contracts

### Question solved

How does the system represent the request, worker routes, failures, limitations, and
overall ready/degraded/unavailable state without delegating workflow control to an
LLM?

### Files

- `src/equity_research/supervisor_contracts.py`
- `tests/test_supervisor_contracts.py`

### Main structures

- `SupervisorRequest`
- `SupervisorRoute`
- `SupervisorPlan`
- `SupervisorWorkerOutcome`
- `SupervisorWorkerFailure`
- `SupervisorState`

The supported worker routes are fixed and application-controlled.

---

## 15. LangGraph worker orchestration

### Question solved

How are the three specialist routes executed and joined into one validated Supervisor
state?

### Files

**Graph**

- `src/equity_research/supervisor_graph.py`

**Real Databricks worker adapters**

- `src/equity_research/supervisor_worker_runtime.py`

**Tests**

- `tests/test_supervisor_graph.py`
- `tests/test_supervisor_worker_runtime.py`

**Live smoke**

- `scripts/run_supervisor_graph_smoke.py`

### Flow

```text
                    START
                      |
          +-----------+-----------+
          v           v           v
   market_analysis  recent_     principal_
                    developments risks
          |           |           |
          +-----------+-----------+
                      v
                   aggregate
                      |
                      v
              SupervisorState
```

For comparisons, Company Researcher execution is performed per symbol/topic and then
merged deterministically. This prevents one requested company from disappearing
silently from a multi-company model response.

Recent-development evidence is also filtered before the worker for known non-company
development noise such as 13F holdings, insider-sale/Rule 10b5-1 items,
analyst/price-target commentary, moving-average/Golden-Cross material, and related
technical-analysis observations.

---

## 16. Final report synthesis and provenance

### Question solved

How are validated worker findings turned into readable final prose while preserving
factual authority, citations, partial-data states, and failure containment?

### Files

**Report contracts, provenance validation and deterministic fallback**

- `src/equity_research/supervisor_report.py`

**GPT OSS 120B prompt and response schema**

- `src/equity_research/supervisor_report_prompts.py`

**120B runtime, one repair and fallback selection**

- `src/equity_research/supervisor_report_runtime.py`

**Complete app-facing graph**

- `src/equity_research/supervisor_research_graph.py`

**Tests**

- `tests/test_supervisor_report.py`
- `tests/test_supervisor_report_runtime.py`
- `tests/test_supervisor_research_graph.py`

**Live end-to-end smoke**

- `scripts/run_supervisor_report_smoke.py`

### Provenance paths

Structured claims:

```text
final report section
       |
       v
market_analysis source_finding_id
       |
       v
validated Market Analyst finding
       |
       v
MetricReference
       |
       v
Gold market_metrics / fundamental_metrics
```

Narrative claims:

```text
final report section
       |
       v
Company Researcher source_finding_id
       |
       v
validated ResearchFinding
       |
       v
evidence_id
       |
       v
research_chunk
       |
       v
validated Silver source record
       |
       v
Bronze retrieval provenance
```

---

## 17. Report defense-in-depth

The final report path intentionally uses several independent controls. A failure in
one layer should not automatically become a published unsupported claim.

### Layer 1 — request scope guard

- only configured one-company or two-company requests are accepted;
- unsupported symbols fail before workers/tools execute.

Files: `tool_scope.py`, `supervisor_contracts.py`.

### Layer 2 — controlled factual inputs

- financial numbers come only from approved Gold tools;
- narrative evidence comes only from controlled retrieval.

Files: `structured_data_tools.py`, `structured_data_access.py`,
`retrieval_tools.py`.

### Layer 3 — freshness and missing-data semantics

- stale/missing structured data is exposed as unavailable rather than usable values;
- incomplete evidence becomes a limitation.

Files: controlled tool modules and worker contracts.

### Layer 4 — retrieved text is untrusted

Provider news/filing text is evidence, not application instructions. Prompt-like text
inside a source cannot override agent/tool policy.

Files: `company_researcher.py`, `worker_agent_prompts.py`.

### Layer 5 — worker structured-output validation

GPT OSS 20B outputs are validated for scope, fields, dates, source semantics,
coverage, and evidence IDs before becoming trusted worker findings.

Files: `market_analyst.py`, `company_researcher.py`,
`worker_agent_runtime.py`.

### Layer 6 — per-company comparison coverage

Company Researcher runs independently for each requested symbol/topic before
deterministic merge. Missing company evidence becomes explicit rather than silent
omission.

File: `supervisor_worker_runtime.py`.

### Layer 7 — evidence relevance filtering

Known market/ownership/technical-analysis noise is filtered from recent-development
evidence before Company Researcher synthesis.

File: `supervisor_worker_runtime.py`.

### Layer 8 — deterministic Supervisor state

Worker outcomes become an application-controlled `ready`, `degraded`, or
`unavailable` state. Worker exceptions do not silently disappear.

Files: `supervisor_contracts.py`, `supervisor_graph.py`.

### Layer 9 — final model sees validated findings, not raw provider text

GPT OSS 120B synthesizes over controlled worker findings and provenance. Raw article
or filing bodies are not reintroduced at the final synthesis stage.

Files: `supervisor_report.py`, `supervisor_report_prompts.py`.

### Layer 10 — section/provenance validation

The final report must contain the exact required sections, correct source classes,
valid source-finding IDs, correct available/degraded/unavailable behavior, and
comparison provenance inherited from grounded base sections.

File: `supervisor_report.py`.

### Layer 11 — comparative-language guard

Unsupported directional/evaluative relations such as `higher`, `lower`, `above`,
`below`, `larger`, `smaller`, `strong`, `weak`, `better`, `worse`,
`outperformed`, and `underperformed` are rejected unless grounded in cited worker
statements.

File: `supervisor_report.py`.

### Layer 12 — one bounded model repair

A deterministic report-contract failure can trigger one controlled GPT OSS 120B
repair request containing the validator error and the same controlled context.

Files: `supervisor_report_prompts.py`, `supervisor_report_runtime.py`.

### Layer 13 — deterministic fallback

If the repaired model response still violates the deterministic report contract, the
system renders from validated worker findings only. No third LLM retry is required.

The fallback is then passed through the **same report validator**; it is not a bypass.

Files: `supervisor_report.py`, `supervisor_report_runtime.py`.

### Observable synthesis outcome

The report exposes:

- `model` — first model synthesis passed;
- `repaired_model` — one repair was required and passed;
- `deterministic_fallback` — both model attempts violated the report contract and
  validated worker findings were rendered deterministically.

This signal is intended for later MLflow evaluation and monitoring.

---

# Complete App-Facing Research Graph

## 18. Terminal research graph

### Question solved

How does the repository represent the complete application research path as one
LangGraph rather than running final synthesis outside the graph?

### Files

- `src/equity_research/supervisor_research_graph.py`
- `tests/test_supervisor_research_graph.py`
- `scripts/run_supervisor_report_smoke.py`

### Flow

```text
START
  |
  v
worker_supervisor
(existing parallel worker subgraph)
  |
  v
validated SupervisorState
  |
  v
final_report_synthesis
(GPT OSS 120B + validation/repair/fallback)
  |
  v
END
```

The worker-only graph remains reusable independently, while the research graph is the
app-facing composition.

---

# Databricks Infrastructure

## 19. Asset Bundle and resources

### Question solved

Where are schemas, jobs, schedules, and managed Vector Search infrastructure declared?

### Bundle root

- `databricks.yml` — shared variables, resource inclusion, targets and workspace
  deployment configuration.

### Schema resources

- `resources/bronze.schema.yml`
- `resources/silver.schema.yml`
- `resources/gold.schema.yml`
- `resources/ai.schema.yml`

### Job resources

Bronze:
- `resources/bronze_price_ingestion.job.yml`
- `resources/bronze_news_ingestion.job.yml`
- `resources/bronze_company_facts_ingestion.job.yml`
- `resources/bronze_sec_filings_ingestion.job.yml`

Silver:
- `resources/silver_price_transformation.job.yml`
- `resources/silver_news_transformation.job.yml`
- `resources/silver_company_facts_transformation.job.yml`
- `resources/silver_filing_sections_transformation.job.yml`

Gold:
- `resources/gold_market_metrics_transformation.job.yml`
- `resources/gold_fundamental_metrics_transformation.job.yml`

RAG:
- `resources/rag_research_corpus_transformation.job.yml`
- `resources/rag_research_chunks.vector_search.yml`

Orchestration:
- `resources/daily_market_refresh.job.yml`
- `resources/weekly_fundamentals_refresh.job.yml`

Foundation smoke:
- `resources/phase_0_smoke_test.job.yml`
- `src/phase_0_smoke_test.py`

### Typical deployment lifecycle

```text
databricks bundle validate -t dev
        |
        v
databricks bundle plan -t dev
        |
        v
databricks bundle deploy -t dev
        |
        v
databricks bundle run <job> -t dev
```

Deployment changes code/resources. Running a job executes a deployed resource; these
are intentionally separate operations.

---

# Testing, CI and Live Verification

## 20. Test strategy

The repository uses different verification layers for different failure modes.

### Deterministic unit/contract tests

Stored under `tests/`.

These verify exact behavior such as:

- provider request construction and retry semantics;
- configuration scope;
- Silver/Gold formulas and version selection;
- corpus identities/chunk replay;
- controlled tool scope/freshness;
- worker output contracts;
- Supervisor routing/state behavior;
- report provenance and semantic guards;
- repair/fallback failure semantics.

### Integration-style offline tests

Also under `tests/`.

Mocks/fakes are used to verify that components interact correctly without requiring
credentials. Examples include Databricks runtime parsing, graph execution, terminal
research graph behavior and model-response handling.

### Live smoke/evaluation runners

Stored under `scripts/`.

- `run_controlled_tool_smoke.py`
- `run_live_retrieval_evaluation.py`
- `run_worker_agent_smoke.py`
- `run_supervisor_graph_smoke.py`
- `run_supervisor_report_smoke.py`

These exercise real Databricks SQL, Vector Search and/or Foundation Model services
while keeping provider source text out of terminal output.

### CI

- `.github/workflows/ci.yml`

Credential-free PR/`main` CI runs Ruff and the full offline test suite. Live
Databricks/model verification remains a separate controlled gate because it requires
workspace credentials and consumes external services.

---

## 21. Dependencies and Python project configuration

- `requirements.txt` — runtime dependencies, including LangGraph.
- `requirements-dev.txt` — development/test dependencies.
- `pyproject.toml` — project/lint configuration.

Dependency changes should remain tied to a component need rather than accumulating
unused libraries.

---

# Documentation Map

## 22. Which document should a reader use?

| Question | Document |
|---|---|
| What is the project and high-level architecture? | `README.md` |
| What is complete, what was live-verified, and what comes next? | `PLAN.md` |
| What are the Bronze/Silver/Gold/RAG data guarantees? | `DATA_CONTRACTS.md` |
| What must the AI system do or refuse to do? | `docs/AI_RESEARCH_CONTRACT.md` |
| Why were particular embedding/LLM/evaluation choices made? | `docs/MODEL_STRATEGY.md` |
| What source content may be processed privately or published? | `docs/DATA_USAGE_PERMISSIONS.md` |
| How is the project built/developed? | `docs/BUILD_GUIDE.md` |
| Which files implement component X, across all folders? | `docs/REPOSITORY_GUIDE.md` |

---

# Current AI Engineering Checkpoint

## 23. Implemented through the Supervisor/report slice

As of the 2026-09-06 Supervisor/report merge:

- data engineering foundation — complete;
- deterministic RAG corpus — implemented/live-verified;
- managed embedding + Vector Search baseline — implemented/live-verified;
- independent retrieval holdout — implemented/live-evaluated;
- controlled Gold/retrieval tools — implemented/live-verified;
- Market Analyst GPT OSS 20B — implemented/live-verified;
- Company Researcher GPT OSS 20B — implemented/live-verified;
- deterministic LangGraph Supervisor — implemented/live-verified;
- GPT OSS 120B terminal synthesis — implemented/live-verified;
- report provenance/semantic validation — implemented/live-verified;
- bounded repair + deterministic fallback — implemented, with repair observed live and
  fallback verified offline;
- full terminal research graph — implemented/live-verified.

The final offline Supervisor branch gate contained **392 passing tests**, Ruff clean,
clean diff checks, and successful AAPL single-company and AAPL/MSFT comparison terminal
graph smokes.

---

# Next Component

## 24. MLflow tracing and GenAI evaluation

The next AI Engineering component will answer:

> How reliably does the complete research system behave across representative cases,
> and where do quality, retrieval, latency, token, repair, or fallback weaknesses
> occur?

Expected future files will be added to this guide when implemented. The evaluation
layer should combine:

- exact code-based numerical/citation checks;
- existing deterministic retrieval metrics;
- MLflow tracing across retriever/tool/worker/Supervisor spans;
- semantic judges for report relevance, groundedness, correctness, safety and project
  guidelines;
- repair/fallback-rate measurement;
- latency, token and cost measurements;
- repeated evaluation against the same representative E1-E6 cases.

---

## Maintenance rule

When a meaningful new component is added:

1. keep implementation/tests/resources in their existing artifact-type folders;
2. add the component to this guide;
3. list its implementation, entry point, resource, tests and live verification;
4. record durable guarantees/failure behavior, not temporary debugging notes;
5. keep chronological run evidence in `PLAN.md` rather than duplicating long run logs
   here.

This keeps the repository navigable without introducing folder nesting solely for
documentation purposes.
