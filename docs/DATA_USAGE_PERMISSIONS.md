# Data Usage and AI Processing Permission Gate

This document records the engineering data-use boundary for the
Multi-Agent Equity Research System on Databricks.

It is an implementation decision for this private portfolio project, not legal
advice. The project uses a conservative interpretation when a provider's terms
do not clearly authorize redistribution or third-party access.

## 1. Project scope

The runtime project is:

```text
private
personal
non-commercial
used only by the project owner
```

The employer-facing portfolio is separate:

```text
public GitHub repository
    code
    tests
    architecture
    contracts
    screenshots
    evaluation evidence

not a public interactive application
not a redistributed market/news dataset
```

This distinction controls the permission gate below.

## 2. Gate outcomes

| Source / service | Private storage / transformation | Private embedding / vector indexing | Private LLM processing | Public raw-text redistribution | Current engineering decision |
|---|---|---|---|---|---|
| SEC EDGAR public filing content | Yes | Yes | Yes | Reuse permitted by SEC | **GREEN** |
| Alpaca News / Benzinga content | Yes for this personal, non-commercial project | Yes for this private prototype | Yes for this private prototype | No public redistribution without applicable permission | **CONDITIONAL GREEN for private processing** |
| Databricks Free Edition | Suitable for personal/non-commercial learning and experimentation | Technically available | Technically available | N/A | **ACCEPTED for this private prototype; revisit before broader use** |

The distinction is:

```text
private personal processing
        !=
public redistribution
```

## 3. SEC EDGAR

The SEC states in its Webmaster FAQ that Government-created content on
sec.gov and EDGAR public filing content are free to access and reuse.

For this project, the selected public 10-K filing sections may therefore
follow the full RAG path:

```text
SEC EDGAR
   -> Bronze filing_documents
   -> Silver filing_sections
   -> research_documents
   -> research_chunks
   -> embeddings
   -> vector index
   -> controlled retrieval
   -> Company Researcher
```

### Engineering decision

Real SEC public filing text may be:

- stored in the private project workspace;
- cleaned and deterministically chunked;
- embedded;
- stored in a vector index;
- supplied as retrieved evidence to the project LLMs;
- cited in private research reports;
- referenced in portfolio screenshots and documentation;
- reused in a public portfolio demonstration where appropriate.

The project should preserve filing URL, accession number, form, filing date,
section identity, and provenance so each claim remains traceable to the
official filing.

Official source:

https://www.sec.gov/about/webmaster-frequently-asked-questions

## 4. Alpaca News / Benzinga

Alpaca's News API documentation identifies Benzinga as the news provider and
documents analytical/model-oriented use cases for news data.

The project owner has an Alpaca account and uses the News API as part of the
services available to that account.

For this project, the relevant usage is:

```text
personal
non-commercial
private
not offered as a service to other users
```

That is materially different from redistributing Alpaca/Benzinga content or
making a public application through which third parties consume the source
data.

### Engineering decision

For this private prototype, real Alpaca/Benzinga news may be:

- ingested into the private Databricks workspace;
- cleaned and normalized;
- transformed into `research_documents`;
- deterministically chunked into `research_chunks`;
- embedded;
- indexed for semantic retrieval;
- supplied as retrieved evidence to privately used Databricks-hosted LLMs;
- evaluated with MLflow.

This is the project's current **conditional-green private-processing decision**.

### What remains restricted

The public portfolio repository must not contain:

- raw Alpaca news API payloads;
- full article bodies;
- stored real-news chunks;
- reusable embedding datasets derived from article bodies;
- credentials or API keys.

The project also does not plan to expose a public interactive application that
allows other people to consume Alpaca/Benzinga source content.

Alpaca's redistribution restrictions therefore remain relevant to the
portfolio boundary even though they do not block the private personal RAG
runtime.

Official sources:

https://files.alpaca.markets/disclosures/library/TermsAndConditions.pdf

https://alpaca.markets/support/redistribute-alpaca-api

https://docs.alpaca.markets/us/docs/historical-news-data

## 5. Databricks Free Edition

The project currently runs on Databricks Free Edition.

Free Edition is intended for personal, learning, and non-commercial use, which
matches this project.

Databricks also states that it reserves the right to train on data placed in
Free Edition. That creates a data-governance caveat for third-party licensed
content.

For this project, that caveat is recorded but is **not treated as a blocker**
to private Alpaca/Benzinga RAG processing because:

- the runtime is personal and non-commercial;
- the data is not redistributed through the project;
- the application is not made available to third-party users;
- the public GitHub repository excludes provider article bodies and payloads.

This is an engineering risk decision rather than a claim that all third-party
licenses necessarily grant every downstream data right.

If the project later becomes public, collaborative, commercial, or moves to a
different serving environment, this gate must be reviewed again.

Official Databricks sources:

https://docs.databricks.com/aws/en/getting-started/free-trial-vs-free-edition

https://docs.databricks.com/aws/en/machine-learning/model-serving

## 6. Live RAG implementation decision

The private live RAG implementation may use both real validated source
families:

```text
Silver news_articles -------------------+
                                         |
                                         v
Silver filing_sections ----------> research_documents
                                         |
                                         v
                                  research_chunks
                                         |
                                         v
                              databricks-gte-large-en
                                         |
                                         v
                                    vector index
                                         |
                                         v
                               controlled retrieval
                                         |
                                         v
                               Company Researcher
```

This is the intended Milestone 2 runtime architecture.

Synthetic fixtures remain useful for:

- unit tests;
- CI;
- public repository examples;
- deterministic prompt-injection tests;
- regression cases that should not depend on provider data.

## 7. Public GitHub / employer showcase boundary

An employer reviewing the project sees the engineering work, not the private
source dataset.

### Public portfolio content

The GitHub repository may contain:

- application and pipeline source code;
- tests and CI configuration;
- data contracts;
- RAG and agent architecture;
- model strategy;
- MLflow evaluation code;
- synthetic fixtures;
- screenshots of the private application;
- screenshots of Databricks jobs, traces, and evaluation results;
- aggregate counts, metrics, and non-sensitive derived outputs;
- reproduction instructions that require the reviewer's own credentials/data
  access where appropriate.

### Content excluded from the public repository

Do not commit:

- Alpaca credentials;
- raw Alpaca API responses;
- full Benzinga/Alpaca article bodies;
- real-news chunk tables or exports;
- reusable real-news embedding files;
- secrets from Databricks;
- private workspace tokens.

### Screenshots

Screenshots may demonstrate the private application, RAG workflow, citations,
retrieval counts, traces, evaluation scores, and project-authored analysis.

Avoid screenshots that reproduce substantial portions of licensed news
articles or expose credentials/raw payloads.

## 8. Application deployment boundary

Milestone 3 is a **private personal Databricks application**.

It is not intended to be:

- a public SaaS product;
- a multi-user research service;
- a commercial application;
- a public API;
- a public redistribution channel for Alpaca/Benzinga content.

The employer-facing artifact is the GitHub portfolio plus screenshots and
documentation.

## 9. Re-evaluation triggers

Revisit this gate if any of the following changes:

1. the application is opened to third-party users;
2. the project becomes commercial;
3. Alpaca/Benzinga provider terms materially change;
4. the project moves to a shared or organizational Databricks environment;
5. a different news provider is introduced;
6. real provider data is proposed for public download or redistribution.

Until one of those conditions occurs, the project decision is:

```text
SEC EDGAR
    private processing      GREEN
    public reuse            GREEN subject to normal citation/provenance

Alpaca/Benzinga
    private personal RAG    CONDITIONAL GREEN
    public redistribution   BLOCKED

Application
    private personal use    IN SCOPE
    public multi-user app   OUT OF SCOPE
```
