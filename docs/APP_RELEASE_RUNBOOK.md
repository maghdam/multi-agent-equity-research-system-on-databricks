# Databricks App Release and Reproduction Runbook

## Purpose

This runbook records the known-good release path for the private Databricks
**Equity Research Workspace** and the bounded checks required before treating a
deployment as portfolio-ready.

The application is private and personal. The public portfolio surface is the GitHub
repository plus reviewed screenshots, documentation, tests, CI evidence, and
non-sensitive evaluation evidence.

Live deployment URL: [Equity Research Workspace](https://equity-research-dev-7474654299884940.aws.databricksapps.com/)

The URL is intentionally documented for authorized reviewers and reproducibility. It is not an anonymous public endpoint; Databricks authentication and app permissions are required.

## 1. Release prerequisites

Use the repository root with the project Python environment active.

The verified development deployment uses:

- bundle target: `dev`;
- Databricks CLI profile: `free-edition-us-east-2`;
- bundle app resource: `equity_research`;
- deployed app name: `equity-research-dev`;
- SQL warehouse binding: `app_sql_warehouse_id`;
- Databricks Apps unified authentication at runtime.

The live 2026-09-07 release verification used Databricks CLI 1.15.0. A newer
compatible CLI may also work, but any CLI/resource-schema change should be validated
with `bundle validate` and `bundle plan` before deployment.

The app runtime does **not** require a developer PAT or local CLI profile. Its
service principal receives only the bound resources declared in
`resources/equity_research.app.yml`:

- SQL warehouse — `CAN_USE`;
- Gold `market_metrics` — `SELECT`;
- Gold `fundamental_metrics` — `SELECT`;
- Silver `daily_prices` — `SELECT`;
- managed research index — `SELECT`.

## 2. Credential-free pre-release gates

Compile the app-facing modules:

```powershell
python -m py_compile `
  app.py `
  src/equity_research/app_contracts.py `
  src/equity_research/app_service.py `
  src/equity_research/app_presenters.py `
  src/equity_research/app_market_history.py `
  src/equity_research/app_followup.py `
  src/equity_research/app_observability.py `
  src/equity_research/databricks_app_runtime.py `
  src/equity_research/publication_audit.py
```

Run the complete app-focused suite:

```powershell
python -m unittest discover -s tests -p 'test_app_*.py'
```

Run the publication-boundary tests and audit:

```powershell
python -m unittest discover -s tests -p 'test_publication_audit.py'
python scripts/audit_publication_boundary.py
```

Expected publication result:

```text
PUBLICATION_BOUNDARY_AUDIT=PASSED
```

Run repository lint and whitespace checks:

```powershell
ruff check .
git diff --check
```

Pull-request CI repeats the publication audit and the complete credential-free
repository test suite.

## 3. Bundle validation and change review

Validate the development bundle:

```powershell
databricks bundle validate -t dev
```

Inspect the proposed infrastructure change before deploying:

```powershell
databricks bundle plan -t dev
```

A no-op release should converge to zero add/change/delete. A deliberate app-resource
change should be understood before continuing. Do not treat an unexpected resource
replacement or permission expansion as routine.

## 4. Deploy bundle source and resources

Deploy the validated bundle:

```powershell
databricks bundle deploy -t dev
```

This uploads source files and applies declared resource changes. It does not by itself
prove that the new application snapshot can start and serve research.

## 5. Deploy/start the app snapshot

Deploy the current bundle source to the app:

```powershell
databricks bundle run equity_research -t dev
```

The successful terminal gate ends with:

```text
App started successfully
```

Inspect app state without printing credentials:

```powershell
databricks apps get equity-research-dev --output json
```

Expected state:

- app status `RUNNING`;
- compute status `ACTIVE`;
- active deployment status `SUCCEEDED`;
- the five least-privilege resource bindings listed above.

The private app URL returned by Databricks is an operational convenience, not a public
portfolio endpoint.

## 6. Startup and HTTP health evidence

Inspect application logs:

```powershell
databricks apps logs equity-research-dev `
  --tail-lines 200 `
  --source APP `
  --profile free-edition-us-east-2
```

A healthy Dash startup shows the process listening on `0.0.0.0:8000`. Browser
navigation should produce successful HTTP requests such as `GET / ... 200`,
`GET /_dash-layout ... 200`, and `GET /_dash-dependencies ... 200`.

The Flask development-server warning is expected for this current Dash command inside
Databricks Apps and is not, by itself, a failed app-health signal.

## 7. End-to-end research gate

Exercise both supported request shapes in the private app.

### Single company

Use:

- primary: AAPL;
- comparison: none;
- market window: 60 trading sessions.

A successful live result should:

- complete with `status=ready` when current controlled data/evidence are available;
- render Overview, Market, Fundamentals, Research Report, and Evidence;
- show the normalized Silver daily-price chart;
- expose only publication-safe evidence metadata/links, not retrieved article/chunk
  bodies.

The 2026-09-07 live gate completed AAPL research with a model-produced ready report.

### Comparison

Use:

- primary: AAPL;
- comparison: MSFT;
- market window: 60 trading sessions.

A successful comparison should:

- retain one aligned market window;
- render both companies' structured snapshots;
- show the normalized cross-company market-history chart;
- contain the comparison report section;
- preserve per-company evidence provenance.

The final 2026-09-07 operations verification completed a ready AAPL/MSFT comparison
with `synthesis_mode=model` and 14 final citations.

## 8. Session-bound follow-up gate

After a successful live research run, ask one factual question grounded in the active
session, for example:

```text
What was Apple's 60-session return?
```

Then ask one source/provenance question, for example:

```text
Which source supports the Apple leasing development and when was it published?
```

The follow-up path must reuse only the signed active research context. It must not
become a general unrestricted assistant.

Also exercise one out-of-scope request. The verified live gate refused an NVDA
investment-recommendation request because NVDA was outside the active AAPL/MSFT
research context.

## 9. Operational telemetry gate

Inspect bounded application events:

```powershell
databricks apps logs equity-research-dev `
  --tail-lines 1000 `
  --source APP `
  --profile free-edition-us-east-2 |
  Select-String "APP_EVENT"
```

The verified 2026-09-07 operations lane emitted:

- `research_completed` for AAPL/MSFT comparison research;
- `followup_completed` for a grounded follow-up;
- `feedback_submitted` after selecting `Helpful`.

The event payload contained only bounded scope/status/count/latency metadata and the
fixed feedback category. Question/answer text, provider text, exception messages, and
credentials were not emitted.

## 10. Publication gate before portfolio capture

Run:

```powershell
python scripts/audit_publication_boundary.py
```

Then review every intended screenshot manually according to
`docs/DATA_USAGE_PERMISSIONS.md`.

Do not publish screenshots containing:

- credentials or tokens;
- raw Alpaca responses;
- substantial Benzinga/Alpaca article text;
- retrieved real-news chunk bodies;
- private workspace tokens or secret values.

Screenshots committed to Git must live under `docs/screenshots/` or
`docs/images/`.

## 11. Known-good rollback / redeploy

The repository is the release source of truth.

To redeploy a known-good Git commit:

```powershell
git status
git switch feature/application-delivery
git pull --ff-only
git log --oneline -n 10
```

Identify the known-good commit, then create a temporary rollback branch instead of
rewriting shared branch history:

```powershell
git switch -c rollback/app-known-good <known-good-commit>
```

Run the credential-free gates and publication audit again, then:

```powershell
databricks bundle validate -t dev
databricks bundle plan -t dev
databricks bundle deploy -t dev
databricks bundle run equity_research -t dev
```

Verify app state, HTTP startup, one research request, and bounded `APP_EVENT` logs
before treating the rollback as successful.

Do not use `git reset --hard` or force-push merely to redeploy an older application
snapshot.

## 12. Final release evidence

A portfolio-ready release has all of the following:

1. credential-free app/publication tests passing;
2. Ruff and `git diff --check` clean;
3. bundle validation successful;
4. planned resource changes understood;
5. bundle deployment successful;
6. app deployment `SUCCEEDED`, app `RUNNING`, compute `ACTIVE`;
7. browser startup/HTTP requests successful;
8. single-company and comparison research exercised;
9. grounded follow-up and out-of-scope refusal exercised;
10. privacy-safe `APP_EVENT` lines observed;
11. publication audit passed;
12. final screenshots manually reviewed.

Chronological live-run evidence remains in `PLAN.md`; this runbook records the stable
procedure.
