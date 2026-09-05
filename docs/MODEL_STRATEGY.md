# Model Strategy

This document records the model choices, model roles, relevant capabilities,
and evaluation gates for the AI layer of the multi-agent equity research
system.

It complements `docs/AI_RESEARCH_CONTRACT.md`:

- the AI research contract defines required behavior and safety boundaries;
- this document records implementation-level model choices and why they were
  selected;
- model choices may change after measured quality, latency, and cost
  evaluation without changing the behavioral contract.

## 1. Initial model architecture

The initial model allocation is:

```text
validated research_chunks
        |
        v
databricks-gte-large-en
        |
        v
1024-dimensional embeddings
        |
        v
vector index
        |
        v
controlled retrieval tool
        |
        +-------------------------------+
        |                               |
        v                               v
Company Researcher              Market Analyst
GPT OSS 20B                     GPT OSS 20B
RAG evidence                    controlled Gold tools
        |                               |
        +---------------+---------------+
                        |
                        v
                   Supervisor
                  GPT OSS 120B
                        |
                        v
             grounded final research report
```

This is the **initial baseline to evaluate**, not a claim that the selected
models are permanently optimal.

## 2. Model-role matrix

| Task | Initial model | Endpoint | Important characteristics | Why this model |
|---|---|---|---|---|
| Document and query embeddings | GTE Large (En) | `databricks-gte-large-en` | English; 8192-token embedding window; 1024-dimensional vectors; embeddings are not normalized by the endpoint | Databricks-native retrieval model with a long input window and direct fit for English financial/news RAG |
| Company Researcher | GPT OSS 20B | `databricks-gpt-oss-20b` | Text; 128K-token context; lightweight reasoning; up to 25K output tokens under current Databricks limits | Lower-cost/faster worker-agent baseline for retrieval-grounded synthesis and structured outputs |
| Market Analyst | GPT OSS 20B | `databricks-gpt-oss-20b` | Text; 128K-token context; lightweight reasoning; up to 25K output tokens under current Databricks limits | Numerical values remain controlled by Gold/SQL tools, so the worker model mainly interprets tool results rather than calculating authoritative metrics itself |
| Supervisor and final report synthesis | GPT OSS 120B | `databricks-gpt-oss-120b` | Text; 128K-token context; stronger reasoning; adjustable reasoning effort; up to 25K output tokens under current Databricks limits | Stronger reasoning model for cross-agent synthesis, conflict handling, citation checks, and final report assembly |
| Reranking | None in v1 | — | Initial retrieval uses embedding similarity plus metadata filters | Avoid adding another model before baseline retrieval quality is measured |
| GenAI quality evaluation | MLflow 3 built-in judges + code-based scorers | `mlflow.genai.evaluate()` | Retrieval relevance/groundedness/sufficiency, correctness, answer relevance, safety, guidelines, plus deterministic retrieval/tool metrics | Use LLM judges for semantic quality and code-based scorers for exact correctness; judge-model choice remains independently configurable |

## 3. Embedding model: GTE Large (En)

### Selected endpoint

```text
databricks-gte-large-en
```

The endpoint serves the English GTE v1.5 large embedding model.

Relevant characteristics:

| Property | Value |
|---|---|
| Task | Text embeddings |
| Language | English |
| Embedding dimension | 1024 |
| Maximum embedding window | 8192 tokens |
| Typical use | Retrieval, semantic search, clustering, classification, RAG |
| Endpoint output normalization | Not normalized |
| Project role | Embed `research_chunks` and retrieval queries |

The current project corpus is English-language Alpaca news and SEC filing text,
so an English-specialized embedding model is appropriate for the MVP.

The 8192-token model window is substantially larger than the planned chunk
sizes. This gives the pipeline room for metadata-aware embedding input while
still avoiding accidental truncation.

The vector-search implementation must explicitly account for the fact that the
Databricks GTE endpoint does **not** return normalized embeddings. Similarity
configuration must therefore be validated rather than assuming unit-length
vectors.

## 4. Initial chunking strategy and model relationship

The first chunking baseline to evaluate is:

```text
algorithm_version = structure-aware-char-v1
target_chars      = 2400
max_chars         = 3200
overlap_chars     = 300
```

These values are deliberately expressed in source characters rather than
pretending that characters and model tokens are equivalent.

The current Silver corpus measurement showed approximately:

| Source | Current observed size |
|---|---:|
| News median | 6,223 characters |
| News p95 | 10,182 characters |
| News maximum | 18,965 characters |
| Filing Item 1 | 16,001 to 41,146 characters |
| Filing Item 1A | 68,022 to 81,155 characters |

This means:

- most usable news articles will become a small number of retrieval chunks;
- long SEC filing sections must be chunked to avoid broad, diluted whole-section
  embeddings;
- the 3200-character maximum is intentionally far below GTE's 8192-token
  model limit;
- the 300-character overlap is intended to retain limited cross-boundary
  context without creating excessive duplicate retrieval content.

The exact values are **baseline parameters**, not universal constants.
Retrieval evaluation should compare alternative strategies.

Example candidate experiments:

```text
v1  target=2400  max=3200  overlap=300
v2  target=1600  max=2200  overlap=200
v3  target=3200  max=4200  overlap=400
```

A change to any boundary-affecting parameter produces a different
`chunking_strategy_version` and therefore different deterministic `chunk_id`
values.

Before live embedding, the implementation should also perform an actual
token-count safety check using the tokenizer or endpoint-compatible token
counting logic. Character length alone is not a token-limit guarantee.

## 5. Worker-agent model: GPT OSS 20B

### Selected initial role

```text
databricks-gpt-oss-20b
```

GPT OSS 20B is the initial worker-agent model for both the Market Analyst and
Company Researcher.

Relevant characteristics:

| Property | Value |
|---|---|
| Task | Chat / reasoning |
| Inputs | Text |
| Context window | 128K tokens |
| Current Databricks output-token limit | 25,000 |
| Character | Lightweight reasoning model; optimized for real-time copilots and batch inference |
| Project role | Worker-agent reasoning, controlled tool use, structured intermediate outputs |

### Company Researcher

The Company Researcher receives:

- the user's scoped company/research request;
- controlled RAG retrieval results;
- citation identifiers and source metadata;
- explicit instructions that retrieved source text is untrusted evidence.

It must synthesize only from retrieved evidence and must not treat source text
as instructions.

### Market Analyst

The Market Analyst receives controlled structured outputs from Gold-data
tools.

The authoritative calculations remain in SQL/Python data logic. The model is
responsible for interpretation and explanation, not for inventing or silently
recalculating authoritative financial metrics.

Using the same worker model for both agents reduces implementation variables
during the first evaluation cycle.

## 6. Supervisor model: GPT OSS 120B

### Selected initial role

```text
databricks-gpt-oss-120b
```

Relevant characteristics:

| Property | Value |
|---|---|
| Task | Chat / reasoning |
| Inputs | Text |
| Context window | 128K tokens |
| Current Databricks output-token limit | 25,000 |
| Character | Higher-capacity reasoning model with adjustable reasoning effort |
| Project role | Supervisor routing, cross-agent reconciliation, citation-aware final report synthesis |

The Supervisor is assigned the stronger model because it performs the most
cross-cutting reasoning:

- validate request scope;
- route work to specialized agents/tools;
- combine structured market/fundamental analysis with cited research evidence;
- detect missing or conflicting evidence;
- enforce report structure;
- ensure claims are supported by the correct source class;
- assemble the final cited report.

The stronger Supervisor model must still obey deterministic tool and citation
contracts. Model capacity is not a substitute for source validation.

## 7. Why not use the strongest model for every task?

Using one large model everywhere would simplify model naming but would blur
important engineering tradeoffs.

The initial architecture deliberately separates:

```text
cheap/faster repeated worker reasoning
        -> GPT OSS 20B

higher-value final synthesis and coordination
        -> GPT OSS 120B
```

This gives the project an explicit quality/latency/cost routing strategy that
can be evaluated with MLflow.

If evaluation shows that GPT OSS 20B is sufficient for final synthesis, the
Supervisor can later use the smaller model. If worker quality is insufficient,
individual tasks can be promoted to the stronger model.

The routing decision is therefore measurable rather than ideological.

## 8. Candidate alternatives available in the current workspace

The current workspace exposes additional Databricks-hosted endpoints that can
be useful for controlled comparisons.

| Model | Potential use | Not chosen as initial baseline because |
|---|---|---|
| `databricks-qwen3-embedding-0-6b` | Multilingual or longer-context embedding experiments; supports long-context embeddings and configurable dimensions up to 1024 | The MVP corpus is English and GTE provides a simpler established English baseline |
| `databricks-bge-large-en` | English embedding benchmark comparison | GTE provides a substantially larger embedding window for the initial baseline |
| `databricks-qwen3-next-80b-a3b-instruct` | RAG-heavy agent or Supervisor comparison | Current Databricks documentation marks this model Public Preview; avoid making a preview model the initial production-oriented baseline |
| `databricks-gemma-3-12b` | Smaller multimodal/chat comparison | The MVP is text-first and GPT OSS 20B is a more direct reasoning-agent baseline |
| `databricks-meta-llama-3-3-70b-instruct` | Alternative larger open model for synthesis | Adds another model family before the initial GPT OSS routing baseline is evaluated |
| `databricks-llama-4-maverick` | Multimodal/large-model experiment | Multimodality is outside the current MVP and some serving modes remain preview-limited |

Availability alone does not make a model part of the architecture. A candidate
becomes a baseline only after a bounded capability and evaluation step.

## 9. Model selection gates

Before a model is treated as an implemented production-style dependency, verify
all of the following.

### Embedding gate

- endpoint is available and ready in the target workspace;
- actual input token counts remain below the selected model limit;
- embedding dimension matches the vector-index schema;
- query and document embeddings use the same model/version and formatting;
- similarity behavior is validated, including normalization assumptions;
- indexing/model-processing permissions are confirmed for real provider text;
- retrieval relevance is evaluated on the representative RAG cases.

### Chat-agent gate

- endpoint is available and ready;
- structured-output behavior is verified;
- controlled tool invocation/routing works as expected;
- prompt-injection fixtures cannot override system/tool policy;
- unsupported symbols fail explicitly;
- missing/stale evidence behavior matches the AI research contract;
- citation identifiers survive generation without fabrication;
- latency and token usage are recorded.

### Supervisor gate

- worker outputs can be combined without losing source attribution;
- conflicting evidence is surfaced rather than silently resolved;
- unsupported numerical claims are rejected;
- final citations resolve to actual controlled retrieval/tool outputs;
- report structure is deterministic enough for evaluation;
- stronger-model quality gains justify its additional latency/cost.

## 10. Testing versus GenAI evaluation

The project uses different evaluation mechanisms for different failure modes.
A single test suite cannot adequately measure deterministic software
correctness, retrieval quality, and free-form LLM answer quality.

The evaluation stack is:

```text
deterministic unit/data tests
        |
        v
component + integration checks
        |
        v
retrieval evaluation
        |
        v
agent/report evaluation with MLflow GenAI
        |
        v
Milestone 3 multi-turn application evaluation
```

### 10.1 Deterministic tests

The existing Python test suite remains the first quality gate.

It covers properties that should have exactly reproducible answers, including:

- configuration and supported-symbol validation;
- Bronze/Silver/Gold transformation correctness;
- exact financial formulas and rounding;
- document identity and versioning;
- chunk boundaries, offsets, hashes, and replay;
- citation-ID existence and lineage;
- required report-schema fields;
- tool input validation;
- explicit missing/stale-data behavior.

These checks should **not** be delegated to an LLM judge when exact programmatic
validation is available.

For example, whether a reported market return equals the controlled Gold value
is a deterministic comparison, not a subjective model-quality judgment.

### 10.2 Component and integration checks

Integration checks verify that independently tested components work together.

Examples include:

- embedding endpoint availability and input-token safety;
- expected embedding dimensionality;
- vector-index synchronization;
- query and document embeddings using the same embedding configuration;
- metadata filters respecting configured symbols;
- retrieval results resolving to current `chunk_id` values;
- LangGraph routing to controlled tools;
- agent structured-output parsing;
- MLflow tracing capturing retriever, tool, agent, and Supervisor spans.

These checks may call live Databricks services but remain primarily
programmatic pass/fail checks.

### 10.3 Retrieval and embedding evaluation

Retrieval quality must be evaluated separately from final answer quality.

A curated evaluation case should contain, when feasible:

```text
query
configured symbol(s)
expected relevant document/chunk IDs
expected source type(s)
optional expected facts
```

This allows deterministic retrieval metrics such as:

| Metric | Purpose |
|---|---|
| `precision@k` | Fraction of top-k retrieved chunks that are labelled relevant |
| `recall@k` | Fraction of labelled relevant chunks recovered in top-k |
| `hit_rate@k` | Whether at least one expected relevant chunk appears |
| `MRR` | How early the first relevant chunk is ranked |
| duplicate rate | Whether overlapping or duplicated evidence crowds out useful results |
| source coverage | Whether required news/filing source classes are represented when expected |

These metrics require labelled expected evidence. They are code-based metrics
and should be logged to MLflow evaluation runs.

MLflow 3 built-in semantic judges complement, rather than replace, those exact
retrieval metrics:

- `RetrievalRelevance` assesses whether retrieved documents are relevant to the
  query;
- `RetrievalGroundedness` assesses whether the generated response is supported
  by retrieved evidence;
- `RetrievalSufficiency` assesses whether retrieved context is sufficient to
  answer the request.

If deeper RAG metrics are useful later, MLflow can also host third-party
scorers such as RAGAS for context precision, context recall, utilization, and
noise-sensitivity experiments. Third-party metrics are optional extensions,
not required for the initial baseline.

### 10.4 Agent and report evaluation with MLflow 3

The main semantic evaluation harness is:

```text
mlflow.genai.evaluate()
```

Each evaluation run should preserve traces, scorer feedback, aggregate
metrics, model/chunk/retrieval configuration, and run metadata.

Initial built-in judges should include, where applicable:

| Judge | Project use |
|---|---|
| `RelevanceToQuery` | Does the final answer directly address the research request? |
| `RetrievalRelevance` | Are the retrieved chunks relevant to that request? |
| `RetrievalGroundedness` | Are generated narrative claims grounded in retrieved evidence? |
| `RetrievalSufficiency` | Was enough relevant evidence retrieved to support the answer? |
| `Correctness` | Does the response agree with expected facts/answers in labelled cases? |
| `Safety` | Does the response satisfy baseline safety requirements? |
| `Guidelines` / `ExpectationsGuidelines` | Does the answer obey project-specific behavioral requirements? |

Project-specific requirements should use either Guidelines judges, custom
judges, or code-based scorers depending on whether the criterion is semantic or
exact.

Initial project-specific evaluation criteria include:

```text
Citation support
    Every material narrative claim must resolve to supplied evidence.

Structured numerical grounding
    Market/fundamental numerical claims must match controlled tool outputs.

Evidence conflict handling
    Conflicting sources must be surfaced rather than silently reconciled.

Research scope
    Unsupported symbols must not enter the analysis.

Prompt-injection resistance
    Instructions found inside retrieved news/filing text remain untrusted data.

Missing/stale evidence behavior
    The report must state limitations instead of fabricating fresh evidence.
```

Citation resolution and numerical equality should preferably be implemented as
code-based scorers. Semantic support, conflict handling, and guideline
adherence can additionally use LLM judges.

### 10.5 Evaluation dataset

The initial evaluation dataset begins with the representative cases already
defined in `docs/AI_RESEARCH_CONTRACT.md`:

```text
E1  single-company grounded report
E2  two-company comparison
E3  unsupported NVDA request
E4  missing/stale structured input
E5  no sufficiently relevant evidence
E6  prompt injection inside retrieved evidence
```

Those cases should be expanded with expected facts, expected evidence IDs,
expected failure behavior, and per-case guidelines as implementation reaches
the corresponding layer.

The dataset should remain small enough to run frequently while covering the
highest-value failure modes. Additional production-like cases can be added
from traced usage and human review later.

### 10.6 Comparing embeddings, chunking, and retrieval settings

MLflow evaluation runs provide the comparison framework for alternatives such
as:

```text
embedding_model
chunking_strategy_version
retrieval_top_k
metadata_filtering
similarity configuration
optional reranker
```

For example, the initial chunk baseline:

```text
target=2400 / max=3200 / overlap=300
```

can be compared with smaller and larger chunk strategies using the same
evaluation queries and expected evidence.

A newer model or chunk configuration should not replace the current baseline
merely because it is newer. It should improve relevant metrics without
unacceptable regressions in latency, cost, or groundedness.

### 10.7 Human review

Automated evaluation is necessary but not sufficient for the final research
experience.

Representative reports should also receive bounded human review for:

- usefulness to an equity-research reader;
- clarity and organization;
- whether citations actually support the intended claim;
- whether caveats are appropriately prominent;
- whether comparisons are balanced rather than mechanically symmetric.

Human feedback can be attached to MLflow traces and used to refine evaluation
criteria or calibrate judges.

## 11. Milestone 3 app-facing chat model

Milestone 3 adds the interactive research application.

The app does **not** initially introduce a separate fourth LLM between the user
and the agent graph. The LangGraph Supervisor is the user-facing chat/research
model.

The initial application path is:

```text
User
  |
  v
Chat application
  |
  v
LangGraph Supervisor
GPT OSS 120B
  |
  +-----------------------+
  |                       |
  v                       v
Market Analyst       Company Researcher
GPT OSS 20B          GPT OSS 20B
  |                       |
Gold tools              RAG
```

Therefore the initial Milestone 3 app-facing model is:

```text
databricks-gpt-oss-120b
```

The choice remains an evaluation baseline rather than a permanent requirement.

The first meaningful model-routing experiment should compare:

```text
Configuration A
Supervisor     = GPT OSS 120B
Worker agents  = GPT OSS 20B

Configuration B
Supervisor     = GPT OSS 20B
Worker agents  = GPT OSS 20B
```

Compare at least:

- final-report groundedness;
- correctness;
- citation support;
- conflict handling;
- routing/tool-call success;
- latency;
- input/output token usage;
- serving cost when cost data are available.

The larger Supervisor is retained only if its quality gain justifies the
additional latency/cost.

### 11.1 Multi-turn application evaluation

Milestone 3 must also test conversational behavior that single-turn unit tests
cannot establish.

Representative conversations should cover follow-ups such as:

```text
User:
Compare Apple and Microsoft.

User:
Now focus only on Microsoft's risks.

User:
Which of those risks came from the filing rather than news?

User:
What reporting period did the financial numbers use?
```

Evaluation should verify that the app:

- retains the intended company and comparison context;
- does not silently broaden the configured universe;
- preserves source attribution across turns;
- routes follow-up questions to the appropriate tools/retriever;
- does not rely on conversational memory for facts that should be re-read from
  controlled sources;
- exposes stale or missing evidence clearly;
- keeps citations valid after follow-up synthesis.

Multi-turn evaluation may use MLflow-supported judges/scorers and compatible
third-party scorers when they add a needed metric. Deterministic state/tool
checks remain preferable whenever exact validation is possible.


## 12. Evaluation and versioning

Every model-dependent component must expose enough configuration for MLflow
tracing and reproducibility.

At minimum record:

```text
endpoint_name
model_role
model_or_endpoint_version when exposed
chunking_strategy_version
cleaning_strategy_version
embedding_input_format_version
retrieval_parameters
temperature / reasoning configuration where applicable
request token count
response token count
latency
```

Model changes are evaluated against the same representative cases rather than
being accepted because a newer or larger model exists.

The project should distinguish three kinds of evaluation:

1. **Deterministic correctness**
   - symbol scope;
   - SQL/numerical correctness;
   - document/chunk lineage;
   - citation resolution;
   - unsupported/missing-data behavior.

2. **Retrieval quality**
   - relevant-chunk recall;
   - source diversity;
   - duplicate retrieval rate;
   - citation support;
   - sensitivity to chunking parameters.

3. **Generation quality**
   - groundedness;
   - completeness;
   - conflict handling;
   - report usefulness;
   - latency and cost.

## 13. Current status

As of the initial RAG foundation implementation:

```text
research_documents                    implemented + offline tested + live persisted
research_chunks                       implemented + offline tested + live persisted
chunking production baseline          live verified at 2400 / 3200 / 300; evaluation still pending
GTE embedding endpoint                available in workspace
GPT OSS 20B endpoint                  available in workspace
GPT OSS 120B endpoint                 available in workspace
real-text embeddings                  blocked by permission gate
vector index                          not yet implemented
controlled retrieval tool             not yet implemented
Market Analyst                        not yet implemented
Company Researcher                    not yet implemented
LangGraph Supervisor                  not yet implemented
MLflow agent/RAG evaluation           designed; implementation pending
Milestone 3 app-facing chat model      GPT OSS 120B baseline selected for later evaluation
multi-turn app evaluation              designed; implementation pending
```

This status must be updated as each slice is implemented and live-verified.

## References

- Databricks Foundation Model APIs supported models:
  https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/supported-models
- Databricks Foundation Model API limits:
  https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/limits
- Databricks Model Serving foundation-model overview:
  https://docs.databricks.com/aws/en/machine-learning/model-serving/foundation-model-overview
- MLflow 3 built-in LLM judges:
  https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/concepts/judges/
- MLflow 3 scorers and LLM judges:
  https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/concepts/scorers
- MLflow 3 evaluation harness:
  https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/concepts/eval-harness
- MLflow 3 third-party scorers:
  https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/third-party-scorers/
- GTE Large (En) model family:
  https://huggingface.co/Alibaba-NLP/gte-large-en-v1.5
