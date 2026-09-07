# Databricks App Design

## Product shape

Milestone 3 uses a hybrid **equity research workspace** rather than a pure chatbot
or pure BI dashboard.

- Dashboard surfaces structured market/fundamental analytics.
- The validated report surfaces developments, risks, comparison, citations, and limitations.
- Follow-up chat is attached to the active research session; it is not an unrestricted agent.

## MVP layout

```text
+-----------------------------------------------------------------------+
| Equity Research Workspace                                             |
+-----------------------------------------------------------------------+
| Primary company | Compare with | Market window | Run Research         |
+-----------------------------------------------------------------------+
| Overview | Market | Fundamentals | Research Report | Evidence         |
|                                                                       |
|                    active research workspace                          |
+-----------------------------------------------------------------------+
| Follow-up research                                                    |
| Ask about the active validated research session...             [Ask] |
+-----------------------------------------------------------------------+
```

## Selection and scalability

The selectors are searchable and configuration-driven. The current universe contains
AAPL and MSFT, but the control does not need redesign when the supported universe
grows.

The key distinction is:

```text
supported universe size != deep-research request size
```

A future universe may contain thousands of equities while one deep-research request
remains intentionally bounded to one company or a two-company comparison.

## Market-window contract

The initial app exposes only exact windows already supported by Gold `market_metrics`:

- 1 trading session;
- 5 trading sessions;
- 20 trading sessions;
- 60 trading sessions.

The UI must not call these arbitrary calendar periods such as "6 months". Additional
calendar/custom periods require an explicit backend/data-contract change first.

## Theme

The application supports explicit **Light** and **Dark** themes from the header. The
selected theme is stored in browser-local Dash state so the preference persists
across refreshes on the same browser.

The theme is presentation-only: it must not change research/session state, data
selection, backend routing, or evaluation behavior.

## Main views

### Overview

Key market/fundamental metrics, report status, limitations, and a compact research summary.

### Market

Normalized price history for comparison plus exact controlled Gold market metrics.

### Fundamentals

Comparison-oriented controlled fundamental metrics with filing/as-of dates and
missing/stale states.

### Research Report

Renders the existing validated Supervisor report with citations and limitations.

### Evidence

Shows citation-linked news/SEC evidence metadata and approved excerpts while
preserving the provider-content/publication boundary.

### Follow-up research

Follow-up is session-bound rather than a new unrestricted research agent.

After a successful live research run, `app_followup.py` builds a JSON-safe context
from:

- the active one/two-company scope and exact selected market window;
- final cited worker findings from the validated Supervisor state;
- controlled structured values already surfaced by the app;
- validated final report sections and limitations;
- publication-safe evidence metadata and original-source links.

Raw retrieved news/filing chunk text and news headlines are not copied into the
browser follow-up context.

The browser-held context is HMAC-signed with an ephemeral process key. Every Ask
callback verifies the signature and schema before the context is trusted. Client-side
tampering therefore fails closed. A process restart or instance change may invalidate
an existing conversation; the user simply reruns research to create a fresh signed
session. This avoids maintaining a server-side cache or persisting chat state for the
MVP.

Conversation history is bounded to the six most recent question/answer turns. A new
research run resets the history so a previous company/window can never silently carry
into a new research session.

Follow-up synthesis uses `system.ai.gpt-oss-120b` with strict JSON output. Runtime
validation requires every substantive answer to cite only source IDs from the signed
context; evidence IDs must be linked to a cited source. Numerical claims must already
exist in cited source text, and guarded comparative/directional terms must already be
grounded there. One bounded repair is allowed after deterministic validation failure;
a second failure returns a deterministic grounded-failure response instead of an
unsupported answer.

The UI renders source IDs as chips and safe evidence citations as links to the
original source. Local preview mode does not enable follow-up chat.

## Thin application layer

```text
Dash layout / callbacks
        |
        v
application service / presentation adapters
        |
        v
existing equity_research contracts + Supervisor research graph
```

The UI must not recalculate business metrics, build retrieval queries, or validate
citations itself.

## Framework baseline

The MVP uses **Dash** because the application is primarily a research workspace with
charts, comparison tables, report rendering, and contextual follow-up chat.

The repository-root `app.py` is the UI entry point and `app.yaml` defines the
Databricks Apps command. The first shell intentionally performs no live SQL, Vector
Search, or model calls.

## Runtime boundary

The deployed Databricks App must use its own app service principal plus Databricks
App resource bindings/unified authentication. It must not depend on the developer's
local Databricks CLI profile.

The existing CLI adapters remain valid for local smoke/evaluation workflows. The app
service is therefore runtime-agnostic:

```text
Dash
  |
  v
app_service.py
  |
  +--> local/evaluation runtime adapters (CLI where appropriate)
  |
  +--> deployed Databricks App runtime
       service principal + bound SQL/AI Search/model resources
```

This keeps application orchestration reusable while allowing deployment-specific
authentication and transport to change without rewriting UI/business contracts.

## Databricks-native transport

`src/equity_research/databricks_app_runtime.py` keeps the Milestone 2 request and
validation contracts unchanged while replacing local CLI transport with Databricks
Apps unified authentication.

The deployed runtime uses `WorkspaceClient()`, which resolves the app service
principal credentials from the Databricks Apps environment. It sends the existing
controlled requests through authenticated workspace APIs:

- Statement Execution for Gold access;
- AI Search query for filtered RAG retrieval;
- AI Gateway chat completions for GPT OSS 20B/120B.

One atomic runtime call returns both the exact structured snapshot loaded during the
Market Analyst route and the final Supervisor result. This avoids duplicate Gold SQL
queries and avoids mutable cross-session caches in a multi-user app process.

Physical warehouse/index values are resolved from environment variables populated by
Databricks App resource bindings rather than hard-coded in Python.

## Bound application resources

The first deployment binding is defined in
`resources/equity_research.app.yml`. The app receives only the resources required
for research execution:

- `sql-warehouse` — `CAN_USE`;
- `market-metrics` — `SELECT`;
- `fundamental-metrics` — `SELECT`;
- `daily-prices` — `SELECT`, used only for validated chart presentation;
- `research-index` — `SELECT`.

`app.yaml` maps those resource keys into environment variables using `valueFrom`.
For the two Gold resources and the AI Search index, Databricks injects the full
three-level Unity Catalog name. The runtime derives the Gold catalog/schema from the
bound table names and verifies that both Gold resources share the same location.

The `Run Research` callback has two intentional execution modes:

```text
local process without app resource variables
        -> validate selection + Supervisor request preview only

deployed Databricks App with bound resource variables
        -> app_service.py
        -> DatabricksAppResearchRuntime
        -> real controlled Gold + RAG + multi-agent research
```

The deployed callback now renders the validated structured snapshot, normalized
Silver price-history chart, final report sections, limitations, and evidence
provenance. Local execution remains preview-only when the core bound resource
variables are absent. The optional `daily-prices` binding affects only the chart
and never disables the core research path.

## Normalized market-history chart

The Market tab uses validated Silver `daily_prices` only for chart presentation.
The chart does not call Alpaca and does not attempt to reconstruct daily history from
aggregate Gold metrics.

For a selected `N`-session market window, the application:

1. requests exactly `N+1` closes for each selected company;
2. verifies that the final trading date equals the ready Gold
   `market_metrics.as_of_date`;
3. requires aligned trading dates across comparison companies;
4. normalizes each validated series to `100` at its first close;
5. plots normalized performance while preserving Gold as the authoritative source
   for report metrics and numeric claims.

The Silver table is bound to the Databricks App with read-only `SELECT` permission.
Price-history access is presentation-only: a history-query or alignment failure must
not fail the research graph or substitute unvalidated values. The Market tab instead
shows an explicit chart-unavailable limitation while keeping validated Gold/report
content visible.

## First rendered research result

The first result renderer uses only data already carried by the validated
`AppResearchSession`:

- Overview: selected-company Gold snapshot plus a validated research summary;
- Market: exact Gold market metrics and as-of/readiness state;
- Fundamentals: exact Gold fundamental metrics and filing/as-of state;
- Research Report: validated section text, section status, source-finding IDs, and
  explicit limitations;
- Evidence: publication-safe metadata for evidence IDs actually cited by the
  validated report, including source family, active-scope symbols, evidence date,
  source domain/link, filing section when applicable, retrieval rank, source record
  identity, chunk position, and supported report finding IDs.

Daily normalized price history is loaded through its separate controlled Silver
presentation query rather than fabricated from aggregate Gold metrics.

### Evidence presentation boundary

The Company Researcher still receives the full controlled `EvidenceRecord`, while
the Supervisor/report contracts continue to pass only evidence IDs. The Databricks
App runtime observes the already-filtered/ranked retrieval records separately for
presentation, captures them per request, and keeps only records cited by the final
validated report.

The presentation DTO deliberately excludes:

- retrieved `chunk_text`;
- Alpaca/Benzinga article body text;
- news headlines/titles.

The private app may link to the original source URL and display non-sensitive
provenance metadata. This keeps evidence useful to a human reviewer without turning
the portfolio screenshot into a redistribution surface for licensed news content.
SEC filing section labels and official SEC source links remain displayable under the
project's documented publication boundary.

## Implementation slices

1. App selection contract + static Dash shell.
2. Application service connecting controlled data and the existing Supervisor graph.
3. Overview/market/fundamental presentation adapters and charts.
4. Validated report + evidence rendering.
5. Session-bound follow-up chat.
6. Logging/monitoring/feedback and Databricks App deployment verification.
