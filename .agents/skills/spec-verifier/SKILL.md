---
name: spec-verifier
description: Formally verifies system implementation against Fizzbee specifications in specs/ and ensures docstrings link tests to target invariants.
---

# Spec-Verifier Skill

The `spec-verifier` skill ensures code implementations match formal specifications (such as Fizzbee specs) and maintain strict distributed systems invariants.

## 1. Responsibilities
- Parse and analyze Fizzbee specifications located in `specs/`.
- Run model checking verification (`fizzbee check specs/`).
- Verify that unit and integration tests include docstring annotations linking them to Fizzbee invariants (e.g., `"""Verifies Fizzbee Invariant: NoDuplicateRecords"""`).

## 2. Invariant Verification Checklist
- [ ] **Exact-once Processing**: `idempotency_key` is generated via deterministic hash `(tenant_id, source_id, metric_type, timestamp)`.
- [ ] **Core DB Ingestion**: `INSERT ... ON CONFLICT (tenant_id, idempotency_key) DO NOTHING`.
- [ ] **No Direct Shared State**: Services operate independently without shared memory or DB instances.
- [ ] **Test Traceability**: Every distributed interaction test explicitly cites its corresponding spec invariant.
