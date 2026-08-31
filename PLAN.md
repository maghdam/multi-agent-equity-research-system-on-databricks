# Multi-Agent Equity Research System on Databricks - Implementation Plan

The MVP is intentionally limited to AAPL and MSFT. A milestone is complete only when its acceptance criteria are met.

**Scope decision:** Finish the two-stock workflow end to end before reconsidering broader stock coverage.

**Expansion design (planned):** Use one central equities configuration, initially AAPL and MSFT, for ingestion, scope checks, analytics, research tools, and UI selection. Adding another compatible US equity should require a configuration change and the normal onboarding/backfill checks, not changes to pipeline logic or stock-specific tables or agents. Resolve and validate required provider/SEC identifiers; report unsupported or ambiguous mappings rather than guessing. Provider news tags must never expand this configured universe automatically.

**Current step:** Milestone 1 - the SEC company-facts draft, diagnostic scripts, and saved README access instructions have been reviewed. Both SEC diagnostics passed an offline syntax check; the working-tree whitespace check passed, and `.env` is ignored and untracked. The local Git checkpoint is pending. Automated contract tests, full source-data validation, Gold coverage/selection, shared configuration, ingestion, and provider-data permission verification remain pending.

**Next small step:** Stage only `DATA_CONTRACTS.md`, `PLAN.md`, `README.md`, `scripts/check_sec_access.py`, and `scripts/check_sec_company_facts_access.py`. Review the staged file list, change summary, and whitespace check before committing. Do not stage `.env` or raw payloads. This prepares a local Git snapshot; it does not push to GitHub, deploy to Databricks, or run the APIs.

**Tracking rule:** After each small step, review the result and tick its checkbox. Leave a parent task unchecked until all its subtasks are verified. Update the current and next steps before moving on.

**Diagnostics-to-pipeline workflow (planned):** The `scripts/check_*.py` files check local source access and inspect bounded samples; they are not production ingestion jobs or comprehensive API tests. Refactor reusable request/parsing logic into functions for Bronze ingestion, adding shared configuration, pagination where needed, rate-limit/retry handling, ingestion metadata, and persistent raw storage. Databricks jobs/notebooks will orchestrate the pipeline; Silver and Gold will process persisted data according to the contracts, not rerun the diagnostic scripts. Keep useful diagnostics as optional manual checks, and use separate offline fixture-based tests for CI.

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
  - [x] Review and commit the news contract and access-check checkpoint without credentials or article bodies (`0ee0331`).
  - [ ] Define the SEC company-facts and selected-filings contracts.
    - [x] Draft the company-facts purpose and initial scope.
    - [x] Review official SEC automated-access requirements: the [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) require no API key; use an identifying project/contact `User-Agent` per the [SEC FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions). The [fair-access limit](https://www.sec.gov/about/developer-resources) is at most 10 requests per second per user across machines; plan sequential sample checks at no more than one request per second. Runtime evidence is recorded separately below.
    - [x] Configure private local `SEC_USER_AGENT` and verify its presence without displaying its value (local `db` check returned `True`; `.env` is Git-ignored and untracked).
    - [x] Create and review `scripts/check_sec_access.py` for one read-only ticker-directory request (saved script reviewed; Python syntax passed without executing the script or making a network request).
    - [x] Resolve and verify the configured companies' SEC identifiers using official metadata (initial two-company check; reusable onboarding validation remains planned).
      - [x] Run the local ticker-directory check and inspect its output (user-run HTTP 200; AAPL -> `0000320193`, Apple Inc.; MSFT -> `0000789019`, MICROSOFT CORP; directory lookup only, not a company-facts request).
      - [x] Record directory-access evidence and limitations in `DATA_CONTRACTS.md` (saved section reviewed against the user-run output; directory access is explicitly distinguished from company-facts access).
      - [x] Cross-check the resolved identities against company-level SEC response metadata before persistent ingestion (user-run Company Facts output: AAPL `0000320193`, Apple Inc.; MSFT `0000789019`, MICROSOFT CORPORATION. Returned CIKs match the directory; displayed names were reviewed, including Microsoft's label difference).
    - [x] Inspect a small read-only company-facts sample, including candidate concepts, units, reporting periods, and filing provenance (exploratory sample and limitations documented; not full dataset validation).
      - [x] Prepare and review `scripts/check_sec_company_facts_access.py` for sequential AAPL/MSFT access and response-metadata checks (saved script reviewed; Python syntax passed without executing the script or making SEC requests).
      - [x] Run the company-facts access check and review its output before selecting candidate facts (user-run HTTP 200 for both; taxonomies `dei` and `us-gaap`; 503 AAPL and 562 MSFT US-GAAP concepts observed, not fixed expected counts).
      - [x] Record company-facts access evidence and limitations in `DATA_CONTRACTS.md`; refresh earlier access-status wording (saved scope and both evidence sections reviewed against the user-run outputs).
      - [x] Add and review candidate-concept metadata inspection in the existing company-facts diagnostic, without additional requests per run (saved block and company-loop indentation reviewed; Python syntax passed without executing the updated script).
      - [x] Run and review candidate-concept presence, labels, units, and observation counts; do not finalize mappings from presence alone (user-run HTTP 200 for both; all three candidates present in USD. AAPL/MSFT observation counts: revenue 117/134, net income 338/340, total assets 146/142).
      - [x] Record candidate-concept metadata evidence and its limits in `DATA_CONTRACTS.md`; refresh earlier candidate-status wording (saved scope and evidence sections reviewed against the user-run output).
      - [x] Inspect representative observations, including financial values, units, reporting periods, and filing provenance (12 response-order examples reviewed; exploratory inspection only, not full coverage or financial validation).
        - [x] Add and review bounded response-order sampling and decimal-aware JSON parsing in the existing diagnostic (saved executable nesting and `parse_float=Decimal` reviewed; Python syntax passed without running the updated script).
        - [x] Run the updated diagnostic and review sample values, dates, and filing references; identify any additional samples needed before defining the contract (user-run HTTP 200 for both; two observations per candidate in USD. Recent-period coverage and final selection rules still require verification before Gold metrics).
      - [x] Record observation-sample findings and limitations in `DATA_CONTRACTS.md`; update the earlier metadata-only checkpoint wording (saved findings and checkpoint wording reviewed against the user-run output).
    - [x] Define company-fact grain, field mappings, units, reporting periods, filing provenance, and version handling (all design subtasks saved and reviewed; validation/examples, Gold metric selection, implementation, and automated tests remain separate work).
      - [x] Define the meaning of one logical filing-level fact observation (saved grain definition reviewed; business key and version/conflict policies are tracked separately below).
      - [x] Define core field names, source mappings, logical types, and required/optional values (all three field groups saved and reviewed; normalization/version rules and physical decimal storage are tracked separately below).
        - [x] Define company and source identity fields: CIK, taxonomy, concept, unit, and accession number (saved mappings, logical types, required values, CIK formatting, and filing-versus-fact identity distinction reviewed).
        - [x] Define financial value and period fields (saved `fact_value`, `period_start`, and `period_end` mappings, logical types, duration/instant requirements, and amount/date preservation rules reviewed; physical decimal storage policy is tracked separately below).
        - [x] Define descriptive and filing metadata fields (saved mappings for entity name, concept label, filing form/date, fiscal labels, and optional frame reviewed; response descriptions, fact dates, and filing/public-availability meanings remain distinct).
      - [x] Define unit and reporting-period rules, retaining original filing metadata separately from fact dates (saved three-concept USD scope, out-of-scope versus invalid distinction, missing-data policy, duration/instant constraints, and separation from Gold metric selection reviewed).
      - [x] Finalize company-fact decimal storage precision/scale and exact parsing/cast rules before implementing the Silver schema (saved `DECIMAL(28,8)` policy and earlier cross-reference reviewed, including exact parsing, finite numeric types, trailing-zero equivalence, and rejection of lossy casts; implementation and automated boundary tests remain pending).
      - [x] Define ingestion metadata and replay provenance, linking observations to their original Bronze response (saved `source_system`, `source_response_id`, `fetched_at`, and `ingestion_run_id` definitions reviewed, including response lineage, replay preservation, and separation from filing identity).
      - [x] Define business keys and within-response duplicate/conflict handling (saved eight-field key, null-safe instant identity, distinct-filing preservation, normalized duplicate equality, and conflict failure before publication reviewed; heading indentation corrected and verified).
      - [x] Define cross-retrieval version/replay and as-of selection rules (saved whole-response selection by original retrieval time, identical-payload tie handling, no gap filling, validation/atomic publication, and replay/historical-cutoff boundaries reviewed; Gold filing selection and historical-query implementation remain pending).
    - [x] Define concise company-facts validation rules and failure actions (saved response/provenance, scope, field/type, amount/period, and publication checks reviewed; invalid facts, failed refreshes, and unavailable data remain distinct; automation and full source validation remain pending).
    - [x] Review representative company-facts examples (14 saved synthetic scenario rows checked against the documented numeric, period, scope, duplicate/conflict, snapshot, and historical-cutoff rules; expected outcomes reviewed manually, not executed as automated tests).
    - [x] Finish the company-facts contract consistency review (full draft and 14 synthetic scenario rows reviewed; two stale grain/identity references corrected and verified; this is a reviewed draft, not automated or full source-data validation).
    - [x] Finish SEC diagnostic formatting and offline syntax review without changing request behavior (saved import grouping, blank lines, and sampling-comment alignment reviewed; both diagnostics passed AST parsing without importing or executing the scripts or making API requests).
    - [x] Document private SEC setup, diagnostic commands, and limitations concisely in `README.md` (saved collapsible section reviewed; placeholder contact only, both diagnostic commands, expected output, and access-check versus ingestion/validation limitations documented).
    - [ ] Review and commit the SEC company-facts contract and diagnostic checkpoint without private settings or raw payloads.
    - [ ] Define the separate selected-filings contract, including document identity, text selection, citations, and content-use boundaries.
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
