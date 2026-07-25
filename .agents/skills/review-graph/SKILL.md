---
name: review-graph
description: Graph-aware code and architectural impact review. Traces dependency graphs, import chains, breaking contract changes, multi-tenant isolation, and service boundary violations across microservices.
---

# Review-Graph Skill

The `review-graph` skill performs deep, structural code reviews by mapping the dependency graph and architectural boundaries of modified code.

## 1. Trigger Conditions
Activate this skill when:
- Performing code reviews on multi-file pull requests or large refactors.
- Modifying shared protobuf definitions (`packages/proto`), database schemas (`services/core`), or inter-service contracts.
- Reviewing changes to ensure strict multi-tenant isolation and security boundary enforcement.

## 2. Review Checklist & Graph Analysis

### A. Dependency & Import Graph
- **Service Boundaries**: Verify that no service imports forbidden drivers or libraries (e.g., only `services/core/` may import SQLAlchemy/asyncpg; Importers & Analysis must NOT talk directly to DB).
- **Communication Protocols**: Ensure Importers publish to NATS (`qs.ingest.<type>`) and Analysis queries Core via gRPC.
- **Shared Packages**: Check that common data structures are imported from `packages/shared-schemas` or generated protobufs, not duplicated.

### B. Tenant Isolation & Data Safety
- **WHERE Clauses**: Verify all SQL/TimescaleDB queries filter by `tenant_id`.
- **Event Metadata**: Ensure all NATS event payloads contain explicit `tenant_id` and deterministic `idempotency_key`.
- **gRPC Context**: Ensure gRPC calls pass `tenant_id` in metadata/request headers.

### C. Contract & Breaking Change Analysis
- **Protobuf Changes**: Check if fields in `packages/proto/` were deleted or renumbered without backward compatibility.
- **API Endpoints**: Verify that signature updates in Core/Analysis have corresponding updates across all client call sites.

## 3. Output Format
Present review results using standard markdown alerts:

> [!IMPORTANT]
> **Graph & Service Boundary Audit**
> Summary of dependency impact across microservices.

> [!WARNING]
> **Tenant Isolation / Invariant Warning**
> Highlights any missing `tenant_id` check or idempotency key omission.
