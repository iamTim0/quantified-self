# Agent Progress Roadmap

This roadmap tracks the Codex Cloud implementation. Set each item to `in_progress` before work begins and to `completed` only after implementation and verification. Record blockers, risks, decisions, test results and unavailable external prerequisites.

## Working Principles

- Inventory the repository, architecture, UI, authentication, importers and documentation before implementing.
- Follow AGENTS.md strictly: Core owns the database, importers use NATS, and Analysis uses Core exclusively through gRPC.
- Keep every change tenant-safe, idempotent, request-correlated and free of plaintext secrets.
- Extend Fizzbee specifications and invariant-referencing tests when new distributed behavior is introduced.
- Use Sub-Agents for independent importer, integration, test and documentation reviews when available; the main agent must validate their results.

## Roadmap

- [ ] **1. Inventory and detailed design** — inspect services, importers, UI, authentication, API keys, maps, docs, tests and existing invariants.
- [ ] **2. Adaptive import windows** — derive connector-specific overlap windows from polling frequency, measurement intervals and history.
- [ ] **3. Data gaps and backfill recommendations** — detect expected missing data and prefill exact tenant-scoped recovery periods in the UI.
- [ ] **4. Smart duplicate detection** — use range/block checks and interval or binary search; safely fall back for irregular or non-contiguous data; implement Smart and Force modes.
- [ ] **5. Analysis dashboard** — organize analyses and add interactive correlations, trends, anomalies, data quality, comparisons and personal baselines with non-causal wording.
- [ ] **6. Additional analyses** — evaluate lagged correlations, routines, daily/weekly patterns and anomaly detection only when data quality is sufficient.
- [ ] **7. Importer audit** — review all importers, including credentials, feeds/APIs, pagination, rate limits, time zones, sync, errors, NATS, Gateway/Core, Docker and health checks.
- [ ] **8. Calendar/ICS integration** — support valid Outlook/Office ICS URLs without an unrelated API key and distinguish ICS, private tokenized feeds and OAuth/API integrations.
- [ ] **9. Importer and end-to-end tests** — cover credentials, periods, time zones, duplicates, gaps, idempotency, NATS, Gateway/Core and tenant isolation.
- [ ] **10. Logout** — invalidate cookies, storage, access/refresh tokens, sessions and caches; refresh after logout must remain unauthenticated.
- [ ] **11. OIDC providers** — add Google and generic OIDC with Authorization Code + PKCE, state/nonce/issuer/audience validation and safe account linking.
- [ ] **12. Bearer-token tenant mapping** — use only `Authorization: Bearer <token>` and derive tenant identity from validated claims or trusted service-token mapping.
- [ ] **13. Tenant-bound inbound API keys** — hash, rotate, revoke and scope generated keys for Apple Health, Streak and other inbound sources; never require a separate tenant header.
- [ ] **14. Vector-first geodata** — remove the initial dependency on OpenStreetMap tiles, render vectors first, and provide an optional provider with a vector fallback.
- [ ] **15. Hosted documentation** — build a standalone MkDocs Material site with search, navigation, CI build, link validation and complete operational/user documentation.
- [ ] **16. Contextual UI links** — link analyses, import configuration, data gaps, duplicate detection, settings, login, registration and footer to relevant docs pages.
- [ ] **17. Privacy policy and imprint** — add plain German template pages, use placeholders for unknown legal data, reflect actual processing, and require legal review before production.
- [ ] **18. Final verification** — run linting, type checking, unit/integration/E2E tests and the documentation build; document all results and open risks.

## Verification Requirements

- Tests are self-contained and do not depend on pre-existing data.
- Queries filter by `tenant_id`; events include `tenant_id`, deterministic `idempotency_key` and `X-Request-ID`.
- No secrets appear in logs, NATS payloads, responses or unencrypted files.
- Tests reference relevant Fizzbee invariants.
- Legal pages, OIDC and API-key behavior must match the actual implementation.

## Progress Log

### Decisions

_No decisions recorded yet._

### Blockers and Missing Prerequisites

_No blockers recorded yet._

### Test Results

_No tests run yet._

### Final Summary

_To be completed with changed files, successful tests, unavailable external tests, remaining risks and follow-up work._
