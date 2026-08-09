# Formal Specifications

This directory contains formal specifications for the Quantified Self platform using [Fizzbee](https://fizzbee.io/).

## What is Fizzbee?

Fizzbee is a formal specification language designed for distributed systems. It allows us to model our system's states, actions (like network partitions or concurrent requests), and invariants (safety properties). By simulating all possible state transitions, Fizzbee helps us catch race conditions, data loss, and isolation breaches before we write a single line of production code.

## Installation and Usage

```bash
task fizz:check                      # model-check every spec
task fizz:one SPEC=tenant_isolation  # just one
```

Both call `.agents/scripts/verify_specs.py`, which uses a `fizz` binary from
`PATH` when there is one and otherwise builds and runs
`infra/fizzbee.Dockerfile`. CI runs the same script.

### Installing the binary directly

Fizzbee publishes Linux and macOS archives at
[github.com/fizzbee-io/fizzbee/releases](https://github.com/fizzbee-io/fizzbee/releases).
Extract one and put its directory on `PATH`; the executable is `fizz`.

Two things to know before trying:

- **There is no Windows build.** Use the container (the default fallback above)
  or WSL.
- **The checker needs glibc 2.34+.** Ubuntu 20.04 ships 2.31, so a WSL install on
  that release parses a spec and then fails with
  `version 'GLIBC_2.34' not found`. Use WSL with 22.04 or newer, or the
  container.

The archive is ~340 MB: it bundles a complete Python runtime for the parser.

### Bounding the state space

`fizz.yaml` in this directory caps exploration at 6 actions. The Fizzbee default
of 100 does not terminate for these models — `tenant_isolation` was still
enumerating past 160,000 states after 70 seconds.

Keep new specs small enough to check in seconds. The usual causes of an
explosion are an unbounded counter (add a `require` guard), carrying a whole
collection in state where a decision would do, and more entities in a set than
the property actually needs — two tenants are enough to express "B must not read
A's rows".

> An unbounded spec is not merely slow. The checker holds its state graph in
> memory; under Docker Desktop one of these exhausted the Linux VM and took the
> developer's Postgres and NATS containers down with it. `verify_specs.py`
> therefore caps container memory.

### Deadlock detection is off

`fizz.yaml` sets `deadlock_detection: false`. Most specs here model a workflow
that finishes — plan an import, log in and log out, upload a CSV — and once the
terminal state is reached no action is enabled. Fizzbee reports that as
`DEADLOCK detected`; for a terminating model it is the intended end.

The cost is that the check is also off for the genuinely concurrent models, where
a state with no enabled action *would* be a defect. Fizzbee reads one `fizz.yaml`
per directory, so the setting cannot be narrowed to a single spec. A spec that
needs the check back should move into its own subdirectory with its own
`fizz.yaml`.

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
| `IdempotencyKeyDeterministic` | `test_oura_idempotency_key_deterministic` | Oura Importer |
| `TokenRefreshEnforced` | `test_oura_token_refresh_on_401` | Oura Importer |
| `UniqueKeyMapping` | `test_oura_transformer_schema_mapping` | Oura Importer |
| `UnauthenticatedRequestsBlocked` | `test_unauthenticated_requests_blocked` | API Gateway |
| `TenantHeaderAlwaysInjected` | `test_tenant_header_always_injected` | API Gateway |
| `SecretsAlwaysEncryptedAtRest` | `test_secrets_always_encrypted_at_rest` | Core Data Service |
| `SecretMaskedInReadResponse` | `test_secret_masked_in_read_response` | Core Data Service |
| `InstanceNamesUniquePerTenantType` | `test_two_connectors_may_not_share_a_name` | Core Data Service |
| `UploadNoDuplicateData` | `test_the_archive_is_published_then_deleted` | Apple Health Importer |
| `UploadTenantIsolation` | `test_a_connector_belonging_to_somebody_else_is_a_404` | Apple Health / WHOOP Importer |
| `AcceptedUploadIsVisible` | `test_an_upload_is_accepted_and_opens_a_run` | Apple Health / WHOOP Importer |
| `ArchiveIsNotRetained` | `test_the_archive_is_published_then_deleted` | Apple Health Importer |
| `NoEmptyDataWhenReady` | `test_no_empty_data_when_ready` | Next.js Dashboard |
| `ModalStateValid` | `test_modal_state_valid` | Next.js Dashboard |

## Adding New Specs

When introducing new distributed features (like background sync, external API webhooks, or multi-region replication):

1. Create a new `.fizz` file in this directory.
2. Declare **mutable state inside `action Init`**. A top-level assignment is a
   frozen constant, and appending to one fails at check time with
   `cannot append to frozen list`. Keep `UPPER_CASE` constants at the top level.
3. Mock out the actions (happy path plus failure modes like crashes and
   partitions). Use `x = oneof(COLLECTION)` for a non-deterministic choice;
   `any` is deprecated in that position and `exists` is a reserved keyword, so
   neither works as a variable name.
4. Define `always assertion` for safety invariants and `eventually assertion` for
   liveness properties. An assertion whose body is `return True` cannot fail and
   verifies nothing — `ShareRevocationImmediate` was written that way and was
   caught only once the checker actually ran.
5. Run `task fizz:one SPEC=<name>` and fix what it reports.
6. Add the corresponding Python tests in `specs/tests/` referencing the invariant
   by name in the docstring.
7. Update the mapping table in this README.
