# Evaluation Execution Boundary

The project uses two deliberately separate evaluation lanes.

## 1. Credential-free CI

GitHub Actions runs only deterministic, offline checks. CI must not require
Databricks credentials, invoke Foundation Model APIs, query the SQL warehouse,
or call the managed Vector Search index.

The dedicated AI-evaluation CI gate covers:

- controlled tool-access request construction and validation;
- structured-data readiness and scope behavior;
- frozen retrieval metric calculations and fixture loading;
- the live-retrieval runner boundary without executing a live query;
- controlled E4-E6 behavioral fixtures;
- MLflow evaluation/scorer configuration and privacy-safe assessment summaries;
- MLflow runtime span and tracing helpers.

The full repository unit/contract suite then runs as a separate final CI step.

## 2. Credentialed live evaluation

Live Databricks evaluation is intentionally run separately from pull-request CI.
It is used when a change materially affects retrieval, worker/model behavior,
Supervisor synthesis, tracing, or semantic evaluation.

### Retrieval component evaluation

Run the frozen human-labelled retrieval holdout against the managed index only
when retrieval behavior changes:

```powershell
python scripts/run_live_retrieval_evaluation.py `
  --profile free-edition-us-east-2 `
  --index-name workspace.dev_mohammad_m_aghdam_equity_research_ai.research_chunks_index `
  --query-type HYBRID `
  --num-results 10
```

Keep the frozen labels unchanged after observing results.

### Supervisor managed evaluation

Use repository-owned E1/E2 cases for live one-company/comparison regression:

```powershell
python scripts/run_supervisor_evaluation.py `
  --warehouse-id 43ebc7727b6328ed `
  --profile free-edition-us-east-2 `
  --gold-schema dev_mohammad_m_aghdam_equity_research_gold `
  --index-name workspace.dev_mohammad_m_aghdam_equity_research_ai.research_chunks_index `
  --case E1 E2 `
  --mlflow-experiment /Shared/equity-research-genai-evaluation `
  --include-llm-judges `
  --skip-trace-validation `
  --eval-max-workers 1 `
  --eval-max-scorer-workers 2
```

The low concurrency is intentional: these are controlled live-model checks, not
a high-throughput benchmark.

Controlled E3-E6 cases should be run only when their corresponding failure or
security behavior changes.

### Privacy-safe inspection

Inspect managed runs through the repository inspector rather than printing raw
trace payloads:

```powershell
python scripts/inspect_mlflow_evaluation_run.py `
  --run-id <RUN_ID> `
  --profile free-edition-us-east-2 `
  --show-span-summary
```

Semantic/LLM-judge free-text rationales are suppressed from terminal output.
Only bounded deterministic rationales intended for safe diagnostics are shown.

## 3. Live application production monitoring

The repository contains live-app MLflow tracing and production-scorer support for
`research_request` and `followup_question` interactions. The bundle-managed
production trace experiment is intentionally separate from the controlled offline
evaluation experiment and from the curated `supervisor_evaluation_dataset`.

In a workspace that supports complete production trace persistence, bind that
experiment to the app and register automatic built-in MLflow production scorers
against its experiment ID:

```powershell
python scripts/configure_app_production_monitoring.py `
  --profile free-edition-us-east-2 `
  --experiment-id <APP_PRODUCTION_TRACE_EXPERIMENT_ID>
```

The production monitoring baseline scores every successful app interaction for
Safety and RelevanceToQuery. RetrievalRelevance and RetrievalGroundedness are
restricted to `interaction_type=research_request`, because follow-up turns use
the already signed research context rather than running a new retrieval route.

Production scoring is asynchronous. Databricks attaches scorer feedback to
matching future traces; it does not require or automatically grow the curated
offline evaluation dataset. Keep interesting production failures as traces first,
then deliberately promote sanitized cases into the regression dataset when they
are valuable as permanent test cases.

### Free Edition production-tracing limitation

The Free Edition deployment can create MLflow trace metadata from the Databricks
App, but the app runtime currently cannot persist the experiment-backed span
artifact because outbound access to the workspace storage endpoint is refused.
This leaves visible trace rows with missing span data, which prevents production
scorers from evaluating those traces.

Unity Catalog trace storage is the preferred production architecture, but current
Databricks limitations prevent traces from being written to a default-storage
catalog. Free Edition does not support custom workspace storage locations, so the
project cannot provision the non-default managed storage required for UC-backed
trace tables in this workspace.

Treat automatic live production scoring as implemented but environment-blocked in
Free Edition. The Free Edition app intentionally keeps the production experiment
binding enabled so live research and follow-up requests remain visible as MLflow
trace rows for observability, even though their span payload cannot be persisted in
this workspace. Keep production scorers paused at sample rate 0 here because scorer
assessments require complete trace data and therefore will not appear as score
columns for these incomplete traces. Controlled MLflow evaluation remains fully
verifiable through the offline/live evaluation experiment. In a paid workspace
with supported managed storage, create the production experiment with a Unity
Catalog trace location from the outset, grant the app MODIFY and SELECT on the four
OTel tables, persist the monitoring SQL warehouse ID, and then enable production
scorers.

## Policy

Do not add Databricks credentials to the normal PR CI path merely to automate
live evaluations. Live model, SQL, and Vector Search checks remain explicit,
credentialed release/development gates with controlled usage. If a future
deployment workflow needs automated credentialed evaluation, it should be a
separate protected workflow with its own permissions, usage limits, and review
gate rather than an extension of credential-free PR CI.
