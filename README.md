# WiseFood Data API

<!-- Badges -->
[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Elasticsearch](https://img.shields.io/badge/Elasticsearch-8.14-005571.svg?logo=elasticsearch&logoColor=white)](https://www.elastic.co/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Client](https://img.shields.io/badge/client-wisefood--client-181717.svg?logo=github&logoColor=white)](https://github.com/wisefood/wisefood-client)
[![WiseFood EU](https://img.shields.io/badge/WiseFood-EU%20Project-2e7d32.svg)](https://wisefood-project.eu/)

The **WiseFood Data API** is the catalog and metadata service used to organize, govern, search, and retrieve core knowledge assets in the WiseFood EU project.

It provides a single backend for:

- national dietary guides and their structured guideline entries
- scientific articles and related AI-enrichment workflows
- food composition tables
- textbooks and their passages
- recipe collections
- organizations
- attached source documents and files stored as artifacts

The service is built with FastAPI and uses Elasticsearch as its primary document store and search engine, MinIO for file storage, Redis for caching and asynchronous job coordination, and Keycloak for authentication and authorization.

> **New here?** Jump to [API Consumer Guide](#api-consumer-guide) to start calling the service, or [Data Catalog Reference](#data-catalog-reference) to understand the entities and their fields.

## Documentation & Client

- **Python client & documentation — `wisefood-client`:** the official client library and its documentation live in the **[`wisefood-client`](https://github.com/wisefood/wisefood-client)** repository. It wraps this API with typed helpers for catalog operations, search, and artifact upload, so downstream tools don't hand-roll HTTP calls. The API retains backward compatibility with the legacy flat-kwarg shape that `wisefood-client` sends (see `src/schemas/schemas.py`).
- **Interactive API reference (OpenAPI / Swagger UI):** available on any running instance at **`/docs`** (and the raw spec at `/openapi.json`).

  ```bash
  pip install wisefood-client
  ```

  ```python
  from wisefood import WiseFoodClient

  client = WiseFoodClient(base_url="https://demo.wisefood-project.eu/api", token=TOKEN)
  results = client.articles.search(q="avocado health", limit=10)
  ```

  See the [`wisefood-client`](https://github.com/wisefood/wisefood-client) repository for the authoritative client reference and version compatibility matrix.

## Why This Repository Exists

Within WiseFood EU, this repository acts as the metadata and retrieval layer for curated nutrition-related resources. Its role is not only to store records, but to make them governable and usable across downstream applications:

- editorial tools for data entry and review
- public-facing data access for approved resources
- internal workflows for expert verification and publishing
- semantic enrichment and retrieval workflows for article content
- attachment and provenance tracking through linked artifacts

In practice, this means the repository supports both catalog operations and governance operations:

- create and maintain structured catalog entries
- attach source PDFs and other files
- search and filter across metadata-rich records
- enforce review and publication workflows
- support controlled visibility for internal vs public resources
- prepare text embeddings and RAG-friendly chunks for article content

## How This Fits Into WiseFood EU

This repository is best thought of as the **structured knowledge backbone** for WiseFood's curated data assets. It gives the project a shared place to:

- register and describe authoritative resources
- connect metadata to source files
- govern what is internal versus public
- support expert review workflows
- expose a searchable API to frontend and platform components
- prepare article content for AI-assisted retrieval and enrichment

As the WiseFood platform grows, this service provides a stable contract between curation workflows, public data access, file storage, and semantic retrieval infrastructure.

---

## Data Catalog Reference

This section describes the catalog **data model** — the entity types, how they are identified and related, where they live in Elasticsearch, and the fields they carry. It is the reference for anyone modelling against the catalog or building integrations.

### Identity & common metadata

Every first-class catalog record is identified by a **stable URN** and an internal **UUID**:

- **URN** — human-meaningful, stable identifier, e.g. `urn:article:...`, `urn:guide:nutrition-basics-gr`. URNs are how records are fetched, linked, and referenced across entities.
- **`id`** — internal UUID, assigned by the system.

Most catalog records share a common metadata envelope (`BaseSchema`):

| Field | Type | Notes |
|-------|------|-------|
| `urn` | string | Stable URN identifier |
| `id` | UUID | Internal identifier |
| `title` | string | Human-readable title (required, non-empty) |
| `description` | string? | Summary/abstract (≤ 2000 chars) |
| `tags` | string[] | Topic tags (0–25, unique case-insensitive) |
| `status` | enum | Lifecycle: `draft` · `active` · `archived` · `deleted` |
| `creator` | string? | Contact email of the creator/owner |
| `created_at` / `updated_at` | datetime | UTC timestamps |
| `url` | URL? | Canonical public URL |
| `license` | enum? | License identifier |
| `language` | ISO 639-1? | e.g. `en` |
| `version` | SemVer? | Resource version |

Schemas are strict (`extra="forbid"`): unknown fields are rejected, strings are whitespace-stripped, and enums are normalized. The authoritative definitions live in `src/schemas/schemas.py` and `src/schemas/fct.py`.

### Entity types & collections

Each entity type maps to a dedicated Elasticsearch index ("collection"), created automatically at startup. Index mappings are defined in `src/es_schema.py`.

| Entity | URN prefix | ES collection | Search | Artifacts | Versioned |
|--------|-----------|---------------|:------:|:---------:|:---------:|
| Guide | `urn:guide:` | `guides` | ✅ | ✅ | ✅ |
| Guideline | linked via `guide_urn` | `guidelines` | ✅ | via parent guide | — |
| Article | `urn:article:` | `articles` | ✅ | ✅ | — |
| Textbook | `urn:textbook:` | `textbooks` | ✅ | ✅ | ✅ |
| Textbook passage | linked via `textbook_urn` | `textbook_passages` | ✅ | via parent textbook | — |
| Recipe collection | `urn:rcollection:` | `rcollections` | ✅ | ✅ | — |
| Food composition table | `urn:fctable:` | `fctables` | ✅ | ✅ | — |
| Organization | `urn:organization:` | `organizations` | ✅ | — | — |
| Artifact | linked via `parent_urn` | `artifacts` | — | n/a (is the file) | — |

> URN prefixes are the canonical forms the system emits (e.g. `urn:guide:` is prepended internally on create). The underlying URN format is a generic pattern, so dependent records are primarily located through their parent link field shown above.

Supporting indices also exist: `persons` and `rag_chunks` (semantic-retrieval chunks linked back to a base entity via `base_urn`).

#### Guides

Top-level records representing country/region-specific guidance documents. A guide can include bibliographic and descriptive metadata, review and publication workflow state, revision lineage, identifiers such as DOI or ISBN, linked artifacts, and linked guideline IDs.

#### Guidelines

Dependent records stored in a separate collection and linked to a parent guide via `guide_urn`. They model the individual recommendations inside a dietary guide: rule text, order within the guide, originating PDF page number, action type, target populations, frequency, quantitative recommendations, food groups, and page-level source references back to artifacts.

When creating guidelines through the API, the backend can normalize lightweight draft payloads by deriving `title` from `rule_text`, `sequence_no` from the next available slot within the parent guide, `action_type` from the rule text (with a safe fallback), and `status` as `draft` unless the caller sets otherwise.

#### Articles

Scientific or technical content with structured metadata. Articles additionally support AI enhancement events, semantic embeddings, optional RAG chunk generation, and linked artifacts.

#### Textbooks & Textbook Passages

Textbooks model longer-form educational content with a structured node tree; passages are dependent, individually addressable sections of a textbook supporting bulk import/replace.

#### Recipe Collections

Curated collections of recipes with source-type and data-completeness metadata.

#### Food Composition Tables

Metadata about nutrient databases and reference datasets: compiling institution, classification/standardization schemes, nutrient coverage, data formats, number of entries, and linked artifacts. (Fine-grained food-record modelling lives in `src/schemas/fct.py`.)

#### Organizations

Institutions that publish, maintain, or own resources in the WiseFood catalog.

#### Artifacts

File-backed dependent resources linked to a parent entity via `parent_urn`: PDF documents, uploaded files stored in MinIO, and provenance documents supporting guides, articles, textbooks, or food composition tables. Guidelines do not own artifacts directly — they point to pages/sections inside artifacts attached to their parent guide.

### Relationships at a glance

```text
Guide ──┬── guideline_urns ──▶ Guideline ──▶ (source page refs) ──▶ Artifact (of parent Guide)
        └── artifacts ─────────────────────────────────────────────▶ Artifact

Article ──┬── artifacts ──▶ Artifact
          └── embeddings / RAG chunks ──▶ rag_chunks

Textbook ──┬── passages ──▶ Textbook passage
           └── artifacts ─▶ Artifact

Any parent entity ◀── parent_urn ── Artifact
```

---

## API Consumer Guide

This section is aimed at frontend and integration developers calling the service directly. For typed access, prefer the [`wisefood-client`](#documentation--client) library.

### Base URL & versioning

All routes are mounted under `/api/v1`. A deployment is typically reached as, e.g., `https://demo.wisefood-project.eu/api/v1/...`.

### Authentication

The API uses **Keycloak-issued bearer tokens**. Send them in the `Authorization` header:

```http
Authorization: Bearer <access_token>
```

Token verification and role extraction happen in `src/auth.py`. You can obtain a token via Keycloak directly, through `POST /api/v1/system/login`, or — for service-to-service callers — `POST /api/v1/system/mtm` (machine-to-machine).

Editorial roles of particular importance: `admin`, `expert`, `agent`.

### Response envelope

Every successful response is wrapped in a consistent envelope:

```json
{
  "help": "https://.../api/v1/articles/search",
  "success": true,
  "result": { "...": "endpoint-specific payload" }
}
```

Errors use a uniform shape (note `success: false` and the structured `error` object):

```json
{
  "success": false,
  "error": {
    "title": "InvalidPagination",
    "detail": "Search pagination exceeds Elasticsearch's maximum result window of 10000. Received offset=9996, limit=6, window=10002.",
    "code": "request/invalid"
  },
  "help": "https://.../api/v1/articles/search"
}
```

Validation failures carry `title: "RequestValidationError"` plus a `error.errors` array with per-field details. Error handling is installed centrally in `src/routers/generic.py`.

### The search model

Most searchable entities accept a common `SearchSchema` body (typically via `POST /api/v1/<entity>/search`):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string? | `null` | Full-text query. Multiple words are matched with **AND** — every term must appear, so more words narrow (not widen) the result set. |
| `limit` | int (1–1000) | 10 | Page size |
| `offset` | int (≥ 0) | 0 | Results to skip |
| `fq` | string[]? | `null` | Filter queries, e.g. `region:IE`, `status:active`, `publication_year:[2018 TO 2023]` |
| `sort` | string? | `null` | ES-style sort, e.g. `publication_year desc`, `score desc` |
| `fl` | string[]? | `null` | Fields to return. Supports `original:alias` renaming |
| `fields` | string[]? | `null` | Facet fields to aggregate |
| `facet_limit` | int (1–1000) | 50 | Max facet buckets per field |
| `highlight` | bool | false | Return highlighted snippets |
| `highlight_fields` | string[]? | `null` | Fields to highlight (defaults to `fl`, else all) |
| `highlight_pre_tag` / `highlight_post_tag` | string | `<em>` / `</em>` | Highlight wrappers |

A search response returns:

```json
{
  "result": {
    "results": [ { "...": "documents" } ],
    "facets": { "category": [ { "value": "...", "count": 42 } ] },
    "total": 1234,
    "max_result_window": 10000
  }
}
```

- **`total`** is the exact number of matching documents (the backend tracks total hits precisely rather than capping the count).
- **`max_result_window`** is the largest `offset + limit` the backend will serve — see below.

### Pagination & the result window

Elasticsearch enforces a **maximum result window**: `offset + limit` may not exceed `max_result_window` (10,000 by default). Requesting a deeper page returns an `InvalidPagination` error.

To paginate safely:

1. Read `max_result_window` from the search response.
2. Cap the highest navigable page to `floor(max_result_window / limit)` — i.e. only offer offsets where `offset + limit ≤ max_result_window`.
3. Still display the real `total`, and prompt the user to refine their query to reach results beyond the window rather than exposing unreachable pages.

> Counts and offsets must agree: a UI that shows `total` page buttons but lets the user click past the window will surface `InvalidPagination` on the final pages. Drive the pager off the clamped, navigable total and show the true `total` separately.

### Endpoint reference

OpenAPI docs at `/docs` are authoritative; this is the route-group summary.

| Group | Prefix | Highlights |
|-------|--------|------------|
| System | `/api/v1/system` | `GET /ping`, `GET /info`, `POST /login`, `POST /mtm` |
| Guides | `/api/v1/guides` | list · `autocomplete` · `fetch` · `search` · `GET/POST/PATCH/DELETE /{urn}` |
| Guidelines | `/api/v1/guidelines` | list · `autocomplete` · `fetch` · `search` · guide-scoped search · bulk import · `GET/POST/PATCH/DELETE /{urn}` |
| Articles | `/api/v1/articles` | list · `autocomplete` · `fetch` · `search` · `GET/POST/PATCH/DELETE /{urn}` · `PATCH /{urn}/enhance` |
| Textbooks | `/api/v1/textbooks` | list · `autocomplete` · `fetch` · `search` · `GET/POST/PATCH/DELETE /{urn}` |
| Textbook passages | `/api/v1/textbook-passages` | search · bulk replace · `GET/POST/PATCH/DELETE /{urn}` |
| Recipe collections | `/api/v1/rcollections` | list · `autocomplete` · `fetch` · `search` · `GET/POST/PATCH/DELETE /{urn}` |
| Organizations | `/api/v1/organizations` | list · `autocomplete` · `search` · `GET/POST/PATCH /{urn}` |
| Food composition tables | `/api/v1/fctables` | list · `autocomplete` · `fetch` · `search` · `GET/POST/PATCH/DELETE /{urn}` |
| Artifacts | `/api/v1/artifacts` | create · upload · `GET /{urn}` · download · S3 presign · `PATCH/DELETE /{urn}` |

### Worked example: searching articles

```http
POST /api/v1/articles/search
Authorization: Bearer <token>
Content-Type: application/json

{
  "q": "avocado health",
  "limit": 6,
  "offset": 0,
  "sort": "score desc",
  "fl": ["urn", "title", "authors", "venue", "publication_year"],
  "fields": ["category", "publication_year"]
}
```

To page through results, increment `offset` by `limit`, but never let `offset + limit` exceed the `max_result_window` returned in the response.

---

## Key Functional Capabilities

### 1. Catalog Operations and Search

The API exposes create/read/update/search operations across the main catalog entities, plus delete where supported, using the common [search model](#the-search-model) built on Elasticsearch. It supports both broad text search and structured filtering, faceting, sorting, field selection, and highlighting.

### 2. Editorial Governance for Guides and Guidelines

The guide/guideline model includes workflow-aware metadata so records can move through internal curation before becoming publicly visible. Important concepts:

- `status` — lifecycle state such as `draft`, `active`, `archived`, or `deleted`
- `review_status` — editorial state such as `unreviewed`, `pending_review`, `in_review`, `verified`, `changes_requested`, or `rejected`
- `visibility` — whether a record is `internal` or `public`
- `applicability_status` — domain-level state such as `current`, `expired`, `superseded`, `withdrawn`, or `unknown`
- `verifier_user_id` — the reviewer identity recorded when a guide or guideline is verified

The API also enforces domain rules:

- a guide cannot become active unless it is verified
- a guide cannot become active while it still contains guidelines that are not active and verified
- a public active guide also requires its linked guidelines to be public
- guideline visibility is managed on each guideline and is not cascaded from the parent guide
- guideline text is locked while the guideline is active and the parent guide is published
- modifying published guideline text requires unpublishing the parent guide first

### 3. Visibility and Access Control

The API distinguishes between privileged reviewers and general authenticated users.

For guides, guidelines, and guide-linked artifacts:

- users with `admin` or `expert` roles can view unapproved content
- other authenticated users only see records that are verified or active
- hidden records behave as not found on direct reads
- guide artifacts inherit visibility from the parent guide

On the write side:

- guide and guideline create/update/delete endpoints require `admin` or `expert`
- artifact create/upload/update/delete endpoints require `admin` or `expert`
- article create/update/delete/enhance endpoints allow `admin`, `expert`, or `agent`

### 4. File Handling Through Artifacts

Artifacts connect file storage to structured catalog resources. The service supports metadata-only artifact creation, file upload to MinIO, artifact download, presigned-URL generation for S3-backed files, and linking artifacts to guides, articles, textbooks, and food composition tables.

### 5. Semantic Enrichment for Articles

Articles support semantic enrichment through a Redis-backed queue and a background worker started with the FastAPI application. The pipeline supports entity-level embeddings for article documents, optional RAG chunk generation for article content, and enhancement-event auditing for AI-generated fields. The worker uses `sentence-transformers/all-MiniLM-L6-v2` by default and writes vectors back to Elasticsearch.

## High-Level Architecture

The active runtime is centered around the following layers:

- `src/main.py` — FastAPI app setup, configuration, CORS, router registration, and worker lifecycle
- `src/routers/` — HTTP route definitions
- `src/entities/` — domain-specific business logic and data orchestration
- `src/schemas/` — Pydantic models and validation rules
- `src/backend/` — infrastructure adapters for Elasticsearch, Redis, MinIO, Keycloak, and PostgreSQL
- `src/workers/` — long-running background worker logic

### Runtime Dependencies

- **FastAPI** — HTTP API layer and OpenAPI docs
- **Elasticsearch** — primary document database, search engine, and facet backend
- **Redis** — optional cache plus background job queue/status storage
- **MinIO** — object storage for artifact files
- **Keycloak** — JWT verification and role-based access control
- **Sentence Transformers** — embedding generation for semantic search and RAG preparation

### Data Flow Overview

1. FastAPI route receives the request
2. `auth()` verifies the bearer token and exposes claims to the route
3. Router calls the corresponding entity class
4. Entity validates input with the appropriate Pydantic schema
5. Entity applies domain logic, workflow rules, and visibility checks
6. Backend adapter reads from or writes to Elasticsearch, MinIO, or Redis
7. Response is wrapped in a consistent success envelope by `src/routers/generic.py`

## Repository Structure

```text
.
├── README.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── src/
│   ├── main.py
│   ├── auth.py
│   ├── entity.py
│   ├── catalog_access.py
│   ├── es_schema.py
│   ├── exceptions.py
│   ├── kutils.py
│   ├── routers/
│   │   ├── core.py
│   │   ├── generic.py
│   │   ├── guides.py
│   │   ├── guidelines.py
│   │   ├── articles.py
│   │   ├── artifacts.py
│   │   ├── organizations.py
│   │   ├── fctables.py
│   │   ├── textbooks.py
│   │   ├── textbook_passages.py
│   │   └── rcollections.py
│   ├── entities/
│   │   ├── guides.py
│   │   ├── guidelines.py
│   │   ├── articles.py
│   │   ├── artifacts.py
│   │   ├── organizations.py
│   │   ├── fctables.py
│   │   ├── textbooks.py
│   │   ├── textbook_passages.py
│   │   └── rcollections.py
│   ├── backend/
│   │   ├── elastic.py
│   │   ├── redis.py
│   │   ├── minio.py
│   │   ├── keycloak.py
│   │   ├── embedding_queue.py
│   │   └── postgres.py
│   ├── workers/
│   │   └── embedding_worker.py
│   └── schemas/
│       ├── schemas.py
│       ├── fct.py
│       └── README.md
└── src/sql/
    └── 10_init_tables.sql
```

## Running the Service

### Option 1: Docker Compose

The repository includes a lightweight Docker Compose setup for the API, Elasticsearch, and Redis.

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Update the values in `.env` for your environment.

3. Start the stack:

   ```bash
   docker compose up --build
   ```

By default, this Compose file starts the FastAPI service, Elasticsearch, and Redis.

> **Important:** MinIO and Keycloak are **not** provisioned by the provided `docker-compose.yml`. The API expects working endpoints for both, either from the wider WiseFood platform or from services you run separately.

### Option 2: Local Python Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd src
uvicorn main:api --reload --host 0.0.0.0 --port 8000
```

You will still need reachable Elasticsearch, Redis, MinIO, and Keycloak services configured via environment variables.

## Environment Variables

The main configuration lives in `src/main.py` and is populated from environment variables. Important settings include:

- `HOST`, `PORT`, `DEBUG`
- `CONTEXT_PATH`, `APP_EXT_DOMAIN`
- `ELASTIC_HOST`, `ES_DIM`, `ELASTIC_MAX_RESULT_WINDOW`
- `EMBEDDING_MODEL`
- `MINIO_ENDPOINT`, `MINIO_ROOT`, `MINIO_ROOT_PASSWORD`, `MINIO_BUCKET`
- `MINIO_EXT_URL_API`, `MINIO_EXT_URL_CONSOLE`
- `KEYCLOAK_URL`, `KEYCLOAK_EXT_URL`, `KEYCLOAK_ISSUER_URL`
- `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`
- `CACHE_ENABLED`
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_QUEUE_DB`
- optional PostgreSQL settings for SQLAlchemy-backed components

See `.env.example` for a minimal starting point.

## Development Notes

### Index Bootstrap

Elasticsearch indices are created automatically at startup through `src/backend/elastic.py`. The mappings are defined in `src/es_schema.py`.

### Background Worker

The embedding worker is started as part of the FastAPI app lifespan. It consumes jobs from Redis and writes vectors or chunked records back to Elasticsearch.

### Caching

Entity caching is available through Redis and can be turned on with `CACHE_ENABLED=true`. Reads use a real-time get-by-id, and mutations write with `refresh="wait_for"`, so caches repopulate with fresh data after a patch.

### Validation Style

The repository relies heavily on Pydantic schemas and model validators for field-level normalization, workflow constraints, visibility-related invariants, and cross-field publication validation.

### Implementation Status Notes

A few areas are intentionally still evolving:

- artifact `PATCH` and `DELETE` routes are present as API placeholders but are not fully implemented yet
- some auxiliary modules are exploratory or legacy, while the active runtime path is centered on `src/main.py`, `src/routers/`, `src/entities/`, `src/schemas/`, and `src/backend/`

### Current Testing State

Automated test coverage is still lightweight. In practice, much of the recent verification has been done through schema validation, targeted `py_compile` checks, endpoint-level manual testing, and Elasticsearch-backed integration checks during development.

## What Reviewers Should Pay Attention To

For reviewers or collaborators new to the project, the most important parts of the active runtime are:

- `src/main.py` — application entrypoint
- `src/routers/` — public API contract
- `src/entities/` — business rules and orchestration
- `src/schemas/schemas.py` — data contracts and validation
- `src/backend/elastic.py` — search, indexing, and query behavior
- `src/catalog_access.py` — viewer role and visibility logic

If you are specifically reviewing the guide/guideline governance model, start with `src/entities/guides.py`, `src/entities/guidelines.py`, `src/schemas/schemas.py`, and `src/catalog_access.py`.

## License

This repository is distributed under the terms of the included [Apache License 2.0](LICENSE).
