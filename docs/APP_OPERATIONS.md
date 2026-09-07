# Databricks App Operations

## Purpose

Milestone 3 uses two complementary observability lanes:

1. **Application operations:** bounded `APP_EVENT` JSON lines in Databricks App logs.
2. **AI tracing/evaluation:** the existing MLflow tracing and evaluation stack from
   Milestone 2 when explicitly configured or run through the controlled evaluation
   workflow.

The application lane is intentionally lightweight and privacy-safe. It is designed to
answer operational questions such as whether research/follow-up requests complete,
how long they take, which bounded scope was active, whether the final report was
ready/degraded, and whether a user marked the active session helpful.

It does not log prompts, follow-up questions, answers, article text, filing chunks,
raw provider responses, credentials, or free-text feedback.

## Structured event schema

`src/equity_research/app_observability.py` owns the allowlisted schema.

Every event is emitted as one log line with the stable prefix:

```text
APP_EVENT {"event_type":"research_completed",...}
```

Supported event types:

| Event | Purpose |
| --- | --- |
| `research_completed` | Successful live research lifecycle result |
| `research_failed` | Safe live research failure |
| `followup_completed` | Successful signed follow-up turn |
| `followup_failed` | Safe follow-up/session/input failure |
| `feedback_submitted` | Fixed-category session feedback |

Approved fields are bounded scalars only:

- request mode (`single_company` / `comparison`);
- one/two configured symbols;
- selected market window;
- report status and synthesis mode;
- final evidence count;
- callback duration in milliseconds;
- exception type only, never exception message;
- follow-up question length, turn count, cited-source count, and whether a limitation
  was returned;
- feedback category (`helpful` / `needs_work`).

No arbitrary text field exists in the telemetry dataclass.

## Feedback

The deployed app shows an optional session-level feedback control after a signed live
research session exists:

- **Helpful**
- **Needs work**

The feedback callback verifies the signed active session before accepting a rating.
It records only the fixed rating plus the already-bounded research metadata. There is
no free-text feedback box in the MVP.

Feedback is collected in Databricks App logs rather than a new writable Unity Catalog
table. This avoids adding write permissions or another credential path merely for the
portfolio MVP.

## Inspecting live operations

Inspect recent app events:

```powershell
databricks apps logs equity-research-dev `
  --tail-lines 500 `
  --source APP `
  --profile free-edition-us-east-2 |
  Select-String "APP_EVENT"
```

Inspect research lifecycle only:

```powershell
databricks apps logs equity-research-dev `
  --tail-lines 500 `
  --source APP `
  --profile free-edition-us-east-2 |
  Select-String '"event_type":"research_'
```

Inspect follow-up lifecycle only:

```powershell
databricks apps logs equity-research-dev `
  --tail-lines 500 `
  --source APP `
  --profile free-edition-us-east-2 |
  Select-String '"event_type":"followup_'
```

Inspect submitted feedback:

```powershell
databricks apps logs equity-research-dev `
  --tail-lines 500 `
  --source APP `
  --profile free-edition-us-east-2 |
  Select-String '"event_type":"feedback_submitted"'
```

## Secure runtime boundary

The deployed app uses Databricks Apps unified authentication through
`WorkspaceClient()` and bound resources. It does not require a developer PAT or local
CLI profile at runtime.

The App resource grants remain least-privilege and read-only for research data:

- SQL warehouse: `CAN_USE`;
- Gold market metrics: `SELECT`;
- Gold fundamental metrics: `SELECT`;
- Silver daily prices: `SELECT`;
- managed research index: `SELECT`.

The follow-up HMAC key is generated in process memory with `secrets.token_bytes(32)`.
It is never placed in a Dash store, environment variable, repository file, telemetry
event, or rendered response. A process restart can invalidate an existing browser
session by design; rerunning research creates a fresh signed context.

## Relationship to MLflow

`APP_EVENT` telemetry is not a replacement for MLflow.

MLflow remains the detailed AI-engineering lane for controlled TOOL / RETRIEVER /
CHAT_MODEL / AGENT spans, evaluation scorers, and release-quality behavioral evidence.
See `docs/EVALUATION_RUNBOOK.md`.

The application telemetry lane stays deliberately smaller so routine operational
monitoring cannot accidentally become a second store of prompts, source content, or
model responses.
