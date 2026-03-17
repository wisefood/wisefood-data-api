# WiseFood Data API

The WiseFood Data API is the catalog and metadata service used to organize, govern, search, and retrieve core knowledge assets in the WiseFood EU project.

It provides a single backend for:

- national dietary guides and their structured guideline entries
- scientific articles and related AI-enrichment workflows
- food composition tables
- organizations
- attached source documents and files stored as artifacts

The service is built with FastAPI and uses Elasticsearch as its primary document store and search engine, MinIO for file storage, Redis for caching and asynchronous job coordination, and Keycloak for authentication and authorization.

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

## Core Domain Model

The current API revolves around a small set of first-class entity types.

### Guides

Dietary guides are top-level records representing country or region-specific guidance documents. A guide can include:

- bibliographic and descriptive metadata
- review and publication workflow state
- revision lineage
- identifiers such as DOI or ISBN
- linked artifacts
- linked guideline IDs

### Guidelines

Guidelines are dependent records stored in a separate collection and linked to a parent guide via `guide_urn`. They model the individual recommendations or rules contained inside a dietary guide, including:

- rule text
- order within the guide
- originating PDF page number
- action type
- target populations
- frequency
- quantitative recommendations
- food groups
- page-level source references back to artifacts

When creating guidelines through the API, the backend can now normalize lightweight draft payloads by deriving:

- `title` from `rule_text`
- `sequence_no` from the next available slot within the parent guide
- `action_type` from the rule text, with a safe fallback
- `status` as `draft` unless the caller explicitly sets something else

### Articles

Articles store scientific or technical content together with structured metadata. They also support:

- AI enhancement events
- semantic embeddings
- optional RAG chunk generation for downstream retrieval workflows
- linked artifacts

### Artifacts

Artifacts are file-backed dependent resources linked to a parent entity via `parent_urn`. They are used for:

- PDF documents
- uploaded files stored in MinIO
- provenance documents supporting guides, articles, or food composition tables

### Food Composition Tables

Food composition table records capture metadata about nutrient databases and reference datasets, including:

- compiling institution
- classification and standardization schemes
- nutrient coverage
- data formats
- number of entries
- linked artifacts

### Organizations

Organizations represent institutions that publish, maintain, or own resources in the WiseFood catalog.

## Key Functional Capabilities

### 1. Catalog Operations and Search

The API exposes create/read/update/search operations across the main catalog entities, plus delete where supported, and provides a common search shape based on:

- `q` for full-text search
- `fq` for filter queries
- `sort` for explicit ordering
- `fl` for field selection
- `fields` for faceting
- `highlight` options for highlighted snippets

The search implementation is built on Elasticsearch and supports both broad text search and structured filtering.

### 2. Editorial Governance for Guides and Guidelines

The guide/guideline model includes workflow-aware metadata so records can move through internal curation before becoming publicly visible.

Important concepts include:

- `status`
  Lifecycle state such as `draft`, `active`, `archived`, or `deleted`
- `review_status`
  Editorial state such as `unreviewed`, `pending_review`, `in_review`, `verified`, `changes_requested`, or `rejected`
- `visibility`
  Whether a record is `internal` or `public`
- `applicability_status`
  Domain-level state such as `current`, `expired`, `superseded`, `withdrawn`, or `unknown`
- `verifier_user_id`
  The reviewer identity recorded when a guide or guideline is verified

The API also enforces a number of domain rules:

- a guide cannot become active unless it is verified
- a guide cannot become active while it still contains unverified guidelines
- active guidelines follow the publication state of their parent guide
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

Artifacts connect file storage to structured catalog resources. The service supports:

- metadata-only artifact creation
- file upload to MinIO
- artifact download
- artifact presigned URL generation for S3-backed files
- linking artifacts to guides, articles, and food composition tables

Guidelines themselves do not own artifacts directly; instead, they point to pages or sections inside artifacts attached to their parent guide.

### 5. Semantic Enrichment for Articles

Articles support semantic enrichment through a Redis-backed queue and a background worker started with the FastAPI application.

This pipeline currently supports:

- entity-level embeddings for article documents
- optional RAG chunk generation for article content
- enhancement-event auditing for AI-generated fields

The worker uses `sentence-transformers/all-MiniLM-L6-v2` by default and writes vectors back to Elasticsearch.

## High-Level Architecture

The active runtime is centered around the following layers:

- `src/main.py`
  FastAPI app setup, configuration, CORS, router registration, and worker lifecycle
- `src/routers/`
  HTTP route definitions
- `src/entities/`
  Domain-specific business logic and data orchestration
- `src/schemas/`
  Pydantic models and validation rules
- `src/backend/`
  Infrastructure adapters for Elasticsearch, Redis, MinIO, Keycloak, and PostgreSQL
- `src/workers/`
  Long-running background worker logic

### Runtime Dependencies

- FastAPI
  HTTP API layer and OpenAPI docs
- Elasticsearch
  Primary document database, search engine, and facet backend
- Redis
  Optional cache plus background job queue/status storage
- MinIO
  Object storage for artifact files
- Keycloak
  JWT verification and role-based access control
- Sentence Transformers
  Embedding generation for semantic search and RAG preparation

### Data Flow Overview

At a high level, a request flows through the system like this:

1. FastAPI route receives the request
2. `auth()` verifies the bearer token and exposes claims to the route
3. Router calls the corresponding entity class
4. Entity validates input with the appropriate Pydantic schema
5. Entity applies domain logic, workflow rules, and visibility checks
6. Backend adapter reads from or writes to Elasticsearch, MinIO, or Redis
7. Response is wrapped in a consistent success envelope by `routers/generic.py`

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
│   │   ├── guides.py
│   │   ├── guidelines.py
│   │   ├── articles.py
│   │   ├── artifacts.py
│   │   ├── organizations.py
│   │   └── fctables.py
│   ├── entities/
│   │   ├── guides.py
│   │   ├── guidelines.py
│   │   ├── articles.py
│   │   ├── artifacts.py
│   │   ├── organizations.py
│   │   └── fctables.py
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

## API Surface

The application exposes the following route groups:

- `/api/v1/system`
  Service info, login, machine-to-machine token support, ping
- `/api/v1/guides`
  Dietary guide CRUD and search
- `/api/v1/guidelines`
  Guideline CRUD, search, fetch-by-guide, and guide-scoped search with facets
- `/api/v1/articles`
  Article CRUD, search, and AI enhancement
- `/api/v1/artifacts`
  Artifact creation, upload, get, download, and S3 presign
- `/api/v1/organizations`
  Organization create/read/update/search
- `/api/v1/fctables`
  Food composition table CRUD and search

OpenAPI documentation is available at:

- `/docs`

System endpoints include:

- `GET /api/v1/system/ping`
- `GET /api/v1/system/info`
- `POST /api/v1/system/login`
- `POST /api/v1/system/mtm`

## Search Model

Most searchable entities accept a `SearchSchema` payload with fields such as:

- `q`
  full-text query string
- `limit`, `offset`
  pagination
- `fq`
  filter queries such as `region:IE` or `status:active`
- `sort`
  Elasticsearch-style sort string, for example `publication_year desc`
- `fl`
  fields to include in the result set
- `fields`
  facet field selection
- `highlight`, `highlight_fields`
  optional highlight support

This design gives frontend and data-curation tools a consistent way to search across different resource types.

## Authentication and Authorization

The API uses Keycloak-issued bearer tokens. Token verification is handled in `src/auth.py` and roles are extracted from JWT claims.

Patterns used in the codebase include:

- authenticated read access on most endpoints
- route-level role checks through `Depends(auth(...))`
- role-aware visibility filtering for guides, guidelines, and guide artifacts

Current editorial roles of particular importance are:

- `admin`
- `expert`
- `agent`

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

By default, this Compose file starts:

- the FastAPI service
- Elasticsearch
- Redis

Important: MinIO and Keycloak are not provisioned by the provided `docker-compose.yml`. The API expects working endpoints for both, either from the wider WiseFood platform or from services you run separately.

### Option 2: Local Python Run

If you prefer to run the API outside Docker:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd src
uvicorn main:api --reload --host 0.0.0.0 --port 8000
```

You will still need reachable Elasticsearch, Redis, MinIO, and Keycloak services configured via environment variables.

## Environment Variables

The main configuration lives in `src/main.py` and is populated from environment variables.

Important settings include:

- `HOST`, `PORT`, `DEBUG`
- `CONTEXT_PATH`, `APP_EXT_DOMAIN`
- `ELASTIC_HOST`, `ES_DIM`
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

Entity caching is available through Redis and can be turned on with `CACHE_ENABLED=true`.

### Validation Style

The repository relies heavily on Pydantic schemas and model validators for:

- field-level normalization
- workflow constraints
- visibility-related invariants
- cross-field publication validation

### Implementation Status Notes

A few areas are intentionally still evolving:

- artifact `PATCH` and `DELETE` routes are currently present as API placeholders but are not fully implemented yet
- some auxiliary modules in the repository are exploratory or legacy, while the active runtime path is centered on `src/main.py`, `src/routers/`, `src/entities/`, `src/schemas/`, and `src/backend/`

### Current Testing State

At the moment, the repository does not include a dedicated automated test suite under a `tests/` directory. In practice, much of the recent verification has been done through:

- schema validation
- targeted `py_compile` checks
- endpoint-level manual testing
- Elasticsearch-backed integration checks during development

## What Reviewers Should Pay Attention To

For reviewers or collaborators new to the project, the most important parts of the active runtime are:

- `src/main.py`
  application entrypoint
- `src/routers/`
  public API contract
- `src/entities/`
  business rules and orchestration
- `src/schemas/schemas.py`
  data contracts and validation
- `src/backend/elastic.py`
  search, indexing, and query behavior
- `src/catalog_access.py`
  viewer role and visibility logic

If you are specifically reviewing the guide/guideline governance model, start with:

- `src/entities/guides.py`
- `src/entities/guidelines.py`
- `src/schemas/schemas.py`
- `src/catalog_access.py`

## How This Fits Into WiseFood EU

This repository is best thought of as the structured knowledge backbone for WiseFood’s curated data assets. It gives the project a shared place to:

- register and describe authoritative resources
- connect metadata to source files
- govern what is internal versus public
- support expert review workflows
- expose a searchable API to frontend and platform components
- prepare article content for AI-assisted retrieval and enrichment

As the WiseFood platform grows, this service provides a stable contract between curation workflows, public data access, file storage, and semantic retrieval infrastructure.

## License

This repository is distributed under the terms of the included [LICENSE](LICENSE).
