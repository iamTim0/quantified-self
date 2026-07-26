# Quantified Self Platform: Importer Architecture Standard

This document defines the architectural standard and developer blueprint for building data importers in the Quantified Self Platform. All new and existing importers must adhere to these guidelines.

## 1. Core Architectural Mandate

**Request-Driven Execution:**
Importers MUST NOT use background interval timers (e.g., cron jobs, `apscheduler`) for polling data. All sync executions must be purely request/task-driven.

Tasks are triggered via NATS JetStream using the subject pattern:
`qs.task.sync.<source_type>`

Importers must listen to these subjects and execute sync tasks only when a message is explicitly received.

## 2. Dynamic Credentials & Configuration

**Stateless Importers:**
Importers MUST NEVER store API tokens, OAuth credentials, or configuration in `.env` files or local databases. Importers have **zero database access**.

Credentials and custom `config` dictionaries must be fetched dynamically over internal HTTP at the start of a sync task:
`GET /api/v1/internal/data/sources/<source_type>/token`
This request must include the `X-Tenant-ID` header.

**Security Constraints:**
- Zero plaintext secrets in `.env` files.
- Zero plaintext secrets published in NATS messages.
- All credentials are encrypted at rest by the Core Data Service.

## 3. In-Flight Concurrency Control

To prevent redundant and overlapping syncs for the same tenant, importers must implement an in-flight concurrency lock.

Importers must maintain an `active_syncs: set[str]` lock containing the `tenant_id` of actively syncing tenants. If a sync task arrives for a `tenant_id` currently in the `active_syncs` set, the task MUST be skipped to avoid duplicate work and API rate limits.

## 4. Standardization Contract

### File Layout
All importers must follow a standard file layout:
- `main.py`: Application entry point, NATS JetStream subscription, task lifecycle, and lock management.
- `client.py`: API client for interacting with the external data source (fetching data).
- `transformer.py`: Data transformation logic mapping source payload data to internal metric formats.
- `config.py`: Environment variable definitions (excluding secrets).

### Metric Event Subject
Once data is transformed into internal metric formats, events MUST be published to NATS using the subject pattern:
`qs.ingest.<source_type>`

### Idempotency
All ingestion events require a deterministic `idempotency_key` to ensure duplicate events are safely ignored downstream. The key must be generated as follows:
`idempotency_key = SHA256(tenant_id + source_id + metric_type + timestamp)`

### Testing Requirements
- Unit tests must mock external API calls in `client.py`.
- Ensure deterministic output in `transformer.py` tests.
- Verify concurrency lock behavior (`active_syncs`) in `main.py`.
- Mock NATS JetStream publishing.
