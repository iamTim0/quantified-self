# System Prompt & Rules for AI Agents

## Project Identity

You are working on the **Quantified Self Platform**, a SaaS-ready, microservice-based personal data analytics platform.

**Architecture Summary**: This is a multi-tenant Python (FastAPI/asyncio) monorepo. It features strict separation of concerns: Importers poll external APIs and publish to NATS JetStream. A central Core service consumes these events and uniquely owns a PostgreSQL (TimescaleDB + pgvector) database. An Analysis service performs data science tasks, querying the Core service synchronously via gRPC. All services are deployed independently and share schema definitions via Protobuf and shared Pydantic packages.

---

## Absolute Rules (MUST FOLLOW)

These rules are non-negotiable. Breaking them will result in immediate rejection of code.

1. **Database Ownership**: Only `services/core/` may contain database connection code or SQL queries. No other service may import `SQLAlchemy`, `asyncpg`, or any database driver. The Analysis Service queries Core via gRPC ONLY. Importers do not talk to the database.
2. **Tenant Isolation**: Every database query MUST filter by `tenant_id` in the `WHERE` clause. Every NATS event MUST include a `tenant_id`. Every API endpoint MUST validate `tenant_id` from the authentication context. There are ZERO exceptions for multi-tenant data safety.
3. **Inter-Service Communication**: Importers communicate with Core EXCLUSIVELY via NATS JetStream (subject pattern: `qs.ingest.<source_type>`). Analysis communicates with Core EXCLUSIVELY via gRPC. Do not introduce direct HTTP calls between internal services for primary data flow.
4. **Idempotency**: Every data ingestion event MUST include an `idempotency_key`. The key must be a deterministic hash of `(tenant_id, source_id, metric_type, timestamp)`. Core MUST use `INSERT ... ON CONFLICT (tenant_id, idempotency_key) DO NOTHING` to guarantee exact-once storage semantics.
5. **Fizzbee First**: Before implementing any new distributed interaction pattern, a Fizzbee specification MUST be written in `specs/` and verified. Implementation tests MUST reference the specific Fizzbee invariant they verify in their docstrings.
6. **No Shared State**: Services do NOT share database connections, in-memory state, Redis instances, or file systems. Each service must be independently deployable.
7. **Schema Changes & Mandatory Rollbacks**: Database migrations go through `services/core/` exclusively using Alembic (`services/core/alembic/`). Every migration script MUST define both `upgrade()` AND a fully functional `downgrade()` (rollback) function. Empty or non-functional `downgrade()` functions are strictly forbidden. Protobuf contract changes go through `packages/proto/` using `generate.py`.
8. **Stateless Importers & Connector Credentials**: Importers MUST NOT store access tokens in `.env` files or hardcoded configuration. Importers query Core Data Service dynamically (`GET /api/v1/internal/data/sources/{source_type}/token`) for encrypted credentials configured by users in the Dashboard UI. If no credentials exist, importers MUST remain idle without generating fake data.
9. **NEVER Auto-Seed Data**: Microservices and importers MUST NEVER automatically generate mock seed data on startup or missing configuration. Seed data generation must be executed explicitly via dedicated CLI commands (`python -m importer.seed`).
10. **Stateless & Independent Tests (No Assumed Data)**: Tests MUST NEVER assume pre-existing database state, pre-seeded rows, or dirty environment data. Tests must be completely self-contained, creating their required fixtures during setup and cleaning up afterwards.
11. **Tenant & User Separation**: Tenants represent workspace/organization containers (`tenants` table). Users represent individual accounts (`users` table with `email`, `password_hash`, `tenant_id`, `role`). JWT claims MUST contain `user_id`, `tenant_id`, and `role`.
12. **Zero Plaintext Secrets in Broker or Logs**: Access tokens/secrets MUST NEVER be sent in plaintext over NATS Message Broker events, logged to stdout/stderr, or stored unencrypted. All secrets are encrypted at rest with Fernet AES-256 using a shared secret `ENCRYPTION_KEY` (with a deterministic `DEFAULT_DEV_KEY` fallback for local dev).
13. **End-to-End Correlation ID (`X-Request-ID`)**: Every HTTP request originating at Gateway or client MUST be tagged with a unique `X-Request-ID`. All downstream microservices (Core, Importers, Analysis) MUST propagate `X-Request-ID` in HTTP headers, NATS events, and log outputs (`[req_id=...]`).
14. **No Personal or Environment-Specific Information in the Repository**: This repository is intended to be published. Nothing committed to it may identify the person who runs it, the machine it was written on, or where it is deployed. Specifically forbidden anywhere in tracked files — source, tests, fixtures, documentation, compose files, commit messages, planning notes:
    - **Real email addresses.** Use `@example.com` or `@example.test`. Copyright notices are the exception, because a notice with the name taken out is not a notice: the author line in `LICENSE`, and the third-party licence texts this project is obliged to redistribute (`apps/dashboard/THIRD-PARTY-NOTICES.txt`, `apps/dashboard/licenses/`). Both are listed explicitly in `.agents/scripts/check_private_info.py` — an allowance is a decision that gets written down, not a pattern that quietly stops matching. See [Licensing](docs/licensing.md).
    - **Real password hashes**, even "just a dev account". `infra/db/init.sql` once seeded an owner with a committed bcrypt hash for a real address; every clone carried the credentials for that account.
    - **Deployment hostnames and public URLs.** These come from `PUBLIC_HOST` / `PUBLIC_BASE_URL` at deploy time. A hostname in the source tells a reader of the public repository exactly what to point their tools at.
    - **Absolute local filesystem paths** (`C:\Users\…`, `/home/…`, `/Users/…`). Use repository-relative paths.
    - **Real personal data of any kind** — names in placeholders, actual health data, actual location traces, screenshots containing either.
    - **Agent working state.** Per-run scratch directories and AI planning artifacts are not project documentation and MUST NOT be committed, least of all wired into the published documentation nav. Durable outputs belong in `specs/` (specifications), `docs/` (behaviour and operation) or a commit message (why a change was made) — under their own names, in the form the project already uses. A running log of what an agent did is not one of those: it duplicates the git history in a shape nothing verifies.

    Development *defaults* for secrets (`JWT_SECRET`, `ENCRYPTION_KEY`, …) are a deliberate exception: they are published on purpose so local development needs no configuration, and production refuses to start on them. Everything above is not that — it is information about a particular person and a particular deployment, and no mechanism downstream can undo committing it.
15. **One Metric, One Name, One Unit**: Metric names are not a service's to invent. Every `metric_type` written anywhere MUST be a canonical key from the registry in `packages/shared-schemas/src/shared_schemas/metrics.py`, and every value MUST be in the unit that registry declares for it — importers convert on the way in via `convert()`. Two sources reporting the same quantity write the same name; the name states what was measured, never who measured it and never in which unit. Providers whose metric set depends on the user's own installation emit under a registered dynamic namespace (`home_assistant_`, `apple_health_`, `custom_`) instead of bare names.

    Resolve the name with `canonical_metric_type()` **before** deriving the `idempotency_key`, because the name is part of that hash (rule 4). Aliases may be read but never written: Core rejects them on the NATS path for exactly this reason, and rewrites them only on the manual-import path, where the key is derived after validation.

    After changing the registry run `task metrics:generate` — the dashboard's TypeScript catalog and the table in `docs/metrics.md` are generated from it, and `task test:packages` fails if either is stale.

16. **One Language in the Repository**: Everything committed here is written in **English** — code, identifiers, comments, docstrings, documentation, log lines, commit messages, test names, and every string a service returns. There are exactly two deliberate exceptions, both of them content rather than code, and both listed here because an allowance is a decision that gets written down (rule 14):
    - `apps/dashboard/src/app/lib/i18n/catalog-de.ts`, the German half of the interface catalogue.
    - The German half of the two legal documents, `ImprintDe` and `PrivacyDe` in `apps/dashboard/src/app/legal/`. They are drafted against German statutes (§ 5 DDG, § 18 Abs. 2 MStV, § 25 TDDDG, the GDPR as applied in Germany) and the German wording is **binding**; the English half is a courtesy translation and says so through `legal.translationNote`. Both halves describe the same processing and change in the same commit — a privacy policy that is current in one language and stale in the other is worse than one language alone, because each reader believes theirs is the accurate one.

    A German sentence anywhere else is a defect, including in a comment you are only passing through. The identifiers around those documents are English even where the route is not: `/legal/impressum` and `/legal/datenschutz` keep their paths because they are what the footer, the documentation and any external reference already point at, and a legal notice that moves is a link that rots.

    The dashboard is bilingual, and that is a property of the catalogue, not of the components: **no user-visible literal may appear in a component.** Every label, placeholder, `title`, `aria-label`, confirm text and error message goes through `t("area.thing")`. The two catalogues cannot drift, because `catalog-de.ts` is typed `Record<MessageKey, string>` — a key missing from either side fails the type check rather than rendering an empty element. Dates and numbers come from `useI18n()` (`formatDate`, `formatDateTime`, `formatNumber`); a hardcoded locale such as `toLocaleString("de-DE")` shows one language's formatting to the other language's reader and is forbidden.

17. **Localize at the Edge, Never on the Server**: Services answer in English. Anything a client must be able to present in another language travels as a **stable machine-readable `code`**, plus a `params` object when the wording contains a value — see `Warning_` in `core/deployment_warnings.py`, which the dashboard renders through `warning.<code>.*` and falls back to the server's own text for a code it does not know. Do not add `Accept-Language` handling to a service to solve a presentation problem.

    The corollary is the part that actually breaks: **a field a client compares against is an identifier, not prose.** `direction`, `status`, `severity` and their kind are English, stable, and lowercase. When one changes, both sides change in the same commit — `AnalysisTab` compared `direction === "steigend"` against a German value from `insights.py`, and translating only one side would have left the trend badge silently colourless forever. A client must never branch on a sentence.

18. **Defaults Are What a Local Checkout Has**: A default in `config.py` is what a developer gets with no configuration at all, so it names **loopback and the port the service actually binds** — never a container hostname. Container names are set explicitly in `infra/docker-compose.yml` *and* `docker-compose.prod.yml`, where they are true. Three defaults broke this rule at once and each failed differently: `DASHBOARD_URL=http://dashboard:3000` cost a DNS failure plus a 10 s connect timeout on **every** proxied request (measured: 12.7 s per page, for a page rendered in 50 ms), `CORE_GRPC_URL=core-service:50051` named a host that exists nowhere, and `ANALYSIS_SERVICE_URL` pointed at port 8002 while the service binds 8010.

    Where a fallback list is genuinely needed, it MUST remember which candidate answered and try that one first. Rebuilding the list per request means paying for every wrong entry forever, and a cost that is paid identically on every request looks like slowness rather than like a bug.

19. **A Value That Arrived Is Either Stored or Named**: A field a provider sent has exactly three permitted fates, and "ignored" is not among them. It becomes a data point; or it is carried in the `metadata` of one; or the `FieldReportCollector` names it, so the Data Quality Center can say *this arrives and we do not keep it*. What is forbidden is the fourth outcome — a field that is read, understood by nobody, and gone without a trace. Every one of those found so far was a provider rename: `heartRate` replacing `avgHeartRate` cost every workout's heart rate, `totalSleep` replacing `asleep` cost every night's total while all four stages stored fine.

    **A shape you did not expect is not a reason to drop a quantity — work out which number it means.** An array of per-interval energy, summed, *is* the session's energy: the identical figure the scalar field states when the payload happens to carry one. A series of samples has an average and a maximum. So derive it, and record that you did: `derived_from` (which fields it came from), `derived_by` (the operation — `sum`, `average`, `max`, `product`, `count`) and `sample_count` (how many values it stands on) go in the metadata, because a derived number that looks like a measured one is a number nobody can later audit. This applies to a figure an importer computes as much as to one it aggregates: `strength_session_volume` is a sum of sets and Yazio's daily macros are either the provider's own summary or our accumulation over the day's items, and which of the two it was is not something to leave to guesswork. **What the provider stated outright always beats what we derived**, and a fallback never overwrites a statement.

    **The one hard limit on that**: never write a derived or per-sample value into a metric whose aggregation then counts it twice. `steps` and `distance` are `Aggregation.SUM` and the day's own total already arrives from the provider, so adding a workout's forty per-minute samples on top makes that day read about a third high — in the dashboard, in the analyses, in every export. **A wrong number is worse than a missing one, because nothing distinguishes it from a right one**, whereas a missing one is visible in the report and can be asked about. Where per-sample resolution is genuinely wanted, it gets its own key in the registry first (rule 15).

    **Raw provenance travels with every point**: `metadata.provider_value` is the number exactly as the provider stated it, before any unit conversion, and `metadata.units` is the unit it stated. That is what answers "why does this differ from the number in my Health app" without a re-import, and it is the reason a conversion bug is recoverable rather than destructive.

    **Whole raw payloads are deliberately not stored.** Not for storage cost — because this platform deliberately does not store special-category data (ECG traces, cycle tracking, medications, State of Mind), and a stored raw payload would keep all of it anyway, invisibly, in a column nothing declares. Whether that data is held is the operator's decision and it changes what the privacy policy must say; it is not something an importer does as a side effect of being careful. Per-value provenance, yes, always. Per-payload archives, no.

20. **Health Checks Are Part of Every First-Party Runtime Service**: Every long-running first-party service image MUST declare a Docker `HEALTHCHECK`, and every long-running first-party service in `docker-compose.prod.yml` plus the public Traefik ingress MUST have a healthcheck that Coolify can observe. HTTP services expose an unauthenticated, cheap local liveness endpoint (`/health` for APIs/importers, or the service's documented local endpoint); the check MUST NOT require tenant credentials, provider credentials, or a live external provider. NATS-only workers check the configured broker connection and remain healthy when no connector is configured. Third-party infrastructure is covered by a native or Compose healthcheck when supported. One-shot jobs such as migrations and volume initializers are explicitly exempt and MUST NOT be made unhealthy merely because they exit successfully. New importers MUST follow this contract in both their Dockerfile and production Compose entry.

---

## Code Conventions

- **Python**: Version 3.12+. Use `async/await` heavily.
- **Typing**: Type hints are strictly required everywhere.
- **Validation**: Use Pydantic V2 for all data validation and parsing.
- **Dependencies**: Use `uv` for dependency management. Each service has its own isolated `pyproject.toml`.
- **Shared Code**: Code reused across services (like base models) lives in `packages/shared-schemas/`.
- **Protobuf**: Definitions live in `packages/proto/quantified_self/v1/`.

---

## Data Flow Patterns

- **Ingestion**: Importer -> NATS (`qs.ingest.<type>`) -> Core (Consumer) -> PostgreSQL DB.
- **Query**: External Client -> Gateway (JWT auth, header injection) -> Core (via gRPC from Analysis, or REST from Gateway) -> Client Response.
- **Connector Config**: Dashboard UI -> Gateway -> Core Service (`POST /api/v1/data/sources/configure` -> Fernet AES-256 Encrypted DB) -> Importer dynamic fetch.
- **Tracing**: Request -> Gateway (injects `X-Request-ID`) -> Core (`X-Request-ID` in headers & logs `[req_id=...]`) -> Importers/NATS (`X-Request-ID`).

---

## Testing Requirements

- **Location**: Every service must have a dedicated `tests/` directory.
- **Unit Tests**: Use `pytest`. Mock all external dependencies (NATS, external APIs, gRPC clients).
- **Integration Tests**: Must use `docker compose` to spin up actual backing services (PostgreSQL, NATS) for tests.
- **Self-Contained Fixtures**: Every integration test must create its required tenant/user/data rows explicitly and teardown afterwards. Never assume pre-existing database records.
- **Traceability**: Invariant mapping in test docstrings (e.g., `"""Verifies Fizzbee Invariant: NoDuplicateRecords"""`).

---

## When Adding a New Importer

If the user asks to add an integration for a new data source:

1. Create a new directory: `services/importers/<name>/`
2. Implement four core modules: `config.py`, `client.py`, `transformer.py`, `main.py`.
3. Configure the importer to fetch connector credentials dynamically from Core Data Service DB (`GET /api/v1/internal/data/sources/<name>/token`).
4. Configure the importer to publish to the NATS subject `qs.ingest.<name>`.
5. Register every metric it emits in `packages/shared-schemas/src/shared_schemas/metrics.py`,
   run `task metrics:generate`, and have the transformer resolve names through
   `canonical_metric_type()` and convert values with `convert()`. An importer does not
   invent metric names — see rule 15 and [Metrics](docs/metrics.md).
6. Ensure the `idempotency_key` is generated correctly in the transformer, from the
   *canonical* metric name.
7. Add a `Dockerfile` for the new service and add it to **three** places: `infra/docker-compose.yml` (development, builds from source), `docker-compose.prod.yml` (production, pulls the published image) and the `IMAGES` manifest in `tools/build_images.py`. The manifest is what the release workflow builds; a Dockerfile missing from it is an image that is simply never published, which is why CI fails on it rather than letting it pass silently. Build from the **repository root**, because the path dependency on `packages/shared-schemas` cannot resolve from a narrower context.
8. Add a Docker `HEALTHCHECK` to the new image and a matching `healthcheck:` block to its production Compose service. Use the local `/health` endpoint for HTTP importers; use a broker-connectivity check for NATS-only workers. Do not make health depend on credentials or provider availability.
9. Write a Fizzbee spec extension ONLY IF new distributed patterns are introduced.
10. Add comprehensive test coverage, including the healthcheck contract.

---

## When Adding Text a User Will Read

Every string in the dashboard exists twice, and the type system is what keeps it that way.

1. Add the key to **`catalog-en.ts`** under the section for that screen, named `area.thing`.
   English is the source: it defines `MessageKey`, so this file decides what exists.
2. Add the same key to **`catalog-de.ts`**. Not optional — omitting it is a type error, which
   is the point.
3. Use it as `t("area.thing")`. Values interpolate as `{name}`: `t("auth.signInWith", { provider })`.
   Where a count changes the wording, add `*_one` / `*_other` and pick with
   `plural(n, "…_one", "…_other")`.
4. A string held in state stores the **key**, not the rendered sentence — a rendered sentence
   stays in the language it was rendered in when the reader switches. See the OIDC callback
   page, whose `status` is a `MessageKey`.
5. Format dates and numbers with `useI18n()`, never with a literal locale.
6. For text a **service** produces, do not add a key: the service answers in English and, if the
   dashboard needs to say it in German, the payload carries a `code` (rule 17).

`bun tsc --noEmit` in `apps/dashboard` is the check for all of this, and it runs in CI.

---

## Anti-Patterns to Reject

If you see these patterns, you MUST fix them or refuse to write them:

- ❌ Direct database access from API Gateway, Analysis, or Importers.
- ❌ Missing `tenant_id` filters in `SELECT`, `UPDATE`, or `DELETE` statements.
- ❌ Synchronous HTTP calls from Importers to Core for data ingestion (MUST use NATS).
- ❌ Hardcoded tenant IDs or API secrets in `.env` or source code.
- ❌ Plaintext API tokens in NATS events or log outputs.
- ❌ Un-correlated requests missing `X-Request-ID` headers or log prefixes `[req_id=...]`.
- ❌ Automatic generation of fake/seed data on service startup or fallback.
- ❌ Tests that depend on pre-existing database state or pre-run seed commands.
- ❌ Skipping Fizzbee specifications for new, complex distributed coordination.
- ❌ Sharing mutable state between microservices.
- ❌ A real email address, deployment hostname, absolute local path or personal name anywhere in a tracked file (rule 14).
- ❌ A `metric_type` that is not in the metric registry, or a value stored in a unit other than the one the registry declares for that metric (rule 15).
- ❌ A metric name that carries its unit (`*_kg`, `*_minutes`, `*_percentage`) or its source (`whoop_*` for a quantity another source also reports).
- ❌ Committing agent scratch directories or AI planning documents, and never into the published docs nav.
- ❌ Self-registration enabled by default. `ALLOW_REGISTRATION` is `False`; the first account is created with `python -m core.create_owner`.
- ❌ A non-English string outside the two exceptions rule 16 names (the German catalogue, and the German half of the legal documents) — a German comment counts.
- ❌ A user-visible literal in a component instead of a `t("area.thing")` key, or a key added to one catalogue only.
- ❌ A hardcoded locale in the dashboard (`toLocaleString("de-DE")`, `new Intl.DateTimeFormat("de-DE")`) instead of `useI18n()`.
- ❌ A service that localizes its own output, or a client that branches on server prose instead of on a `code` (rule 17).
- ❌ Renaming a value a client compares against (`direction`, `status`) without changing the client in the same commit.
- ❌ A code default that names a container (`http://dashboard:3000`, `core-service:50051`) or a port the service does not bind (rule 18).
- ❌ A candidate/fallback list that re-pays for its failing entries on every request instead of remembering what answered.
- ❌ A test that asserts on a fragment of prose which the next wording change would silently defeat — assert on the `code`, the status, or the structure.
- ❌ A provider field that is neither stored, nor carried in metadata, nor named in the field report (rule 19) — least of all one skipped merely for arriving as an array or an object.
- ❌ A derived value that does not say it was derived (`derived_from`, `derived_by`, `sample_count`), or one that overwrites a figure the provider stated outright.
- ❌ Per-sample values written into a `SUM` metric whose daily total the provider already sends — that is double counting, and it is worse than the gap it fills.
- ❌ A data point without `metadata.provider_value` and `metadata.units`, or an importer that stores whole raw payloads instead (rule 19).
- ❌ A long-running service or new importer without a Dockerfile `HEALTHCHECK` and a production Compose `healthcheck:` (rule 20), or a healthcheck that requires secrets, tenant state, or provider availability.

## Documentation Requirements for New Features

Every new user-facing or operational feature MUST include code-to-documentation updates in the MkDocs site under `docs/`. Feature documentation must explain:

1. What the feature does and why it exists.
2. How data flows through the platform while preserving service boundaries.
3. How users or operators configure and use it.
4. How imported or derived data can be retrieved through tenant-scoped Core/Gateway APIs.
5. Expected recommendations, interpretation guidance, and known limitations.

Importer changes MUST update `docs/importers/` and link to external API setup references when relevant. Analysis, data-quality, and visualization features MUST update `docs/features/`. The documentation site is built with MkDocs/Material and served separately from the product UI under `/docs`.
