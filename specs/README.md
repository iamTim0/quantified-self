# Formal Specifications

This directory contains formal specifications for the Quantified Self platform using [Fizzbee](https://fizzbee.io/).

## What is Fizzbee?

Fizzbee is a formal specification language designed for distributed systems. It allows us to model our system's states, actions (like network partitions or concurrent requests), and invariants (safety properties). By simulating all possible state transitions, Fizzbee helps us catch race conditions, data loss, and isolation breaches before we write a single line of production code.

## Installation and Usage

To install Fizzbee:
```bash
brew install fizzbee
```
Alternatively, download the binary directly from the Fizzbee website.

To run the specs:
```bash
fizzbee run specs/distributed_ingestion.fizz
fizzbee run specs/tenant_isolation.fizz
```

## Spec to Test Mapping

We use Fizzbee to model the logic, and we map these invariants to real integration tests in our test suite.

| Fizzbee Invariant | Implementation Test | Service |
| ----------------- | ------------------- | ------- |
| `TenantIsolation` | `test_tenant_id_always_present` | Core Data Service |
| `NoDuplicateData` | `test_deduplication_via_idempotency_key` | Core Data Service |
| `DataIntegrity` | `test_concurrent_duplicate_messages` | Core Data Service |
| `EventualConsistency` | `test_network_partition_recovery` | NATS / Importers |
| `NoUnauthorizedAccess` | `test_query_returns_only_own_data` | Core Data Service (Queries) |
| `ShareRevocationImmediate` | `test_share_revocation_blocks_access` | Core Data Service (Queries) |

## Adding New Specs

When introducing new distributed features (like background sync, external API webhooks, or multi-region replication):
1. Create a new `.fizz` file in this directory.
2. Define the initial state and mock out the actions (happy path + failure modes like crashes/partitions).
3. Define `always assertion` for safety invariants and `eventually assertion` for liveness properties.
4. Run Fizzbee to verify your model.
5. Add the corresponding Python placeholder tests in `specs/tests/` to track implementation progress.
6. Update the mapping table in this README.
