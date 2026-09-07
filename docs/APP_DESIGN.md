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

Uses the active research session: selected symbols/window, Supervisor state, final
validated report, structured references, evidence IDs, and bounded conversation
history.

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

## Implementation slices

1. App selection contract + static Dash shell.
2. Application service connecting controlled data and the existing Supervisor graph.
3. Overview/market/fundamental presentation adapters and charts.
4. Validated report + evidence rendering.
5. Session-bound follow-up chat.
6. Logging/monitoring/feedback and Databricks App deployment verification.
