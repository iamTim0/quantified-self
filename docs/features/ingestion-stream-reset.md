# Ingestion stream reset

The ingestion stream is a bounded delivery buffer. It uses JetStream `WORK_QUEUE`
retention so an event leaves the broker after Core stores and acknowledges it. A
stream created with the older `limits` policy keeps acknowledged events until its
age or byte limit expires and can eventually reject every importer publish.

Owners can repair that retention mismatch from the dashboard. The action is served
by `core-ingest`, the process that owns the JetStream consumer. The API Gateway
routes only this management operation to that private process; ordinary tenant
data requests still go to the Core API role.

## Safety sequence

Core does not delete the stream merely because the first status check is empty:

1. The authenticated caller must have the `owner` role.
2. Core reads both `num_pending` and `num_ack_pending` from the durable consumer.
3. A nonzero counter returns a stable error code and both counts. The stream is
   left intact.
4. Core temporarily changes the stream subject to an internal gate. Importer
   publishes to the normal subject are then rejected by JetStream and can retry.
5. Core checks both counters again. A message accepted before the gate is therefore
   still protected by the final check.
6. Core deletes and recreates the stream with the configured `WORK_QUEUE` policy,
   then closes the old connection so the consumer supervisor resubscribes.
7. The request succeeds only after the new stream and consumer are active.

The operation does not delete PostgreSQL rows and does not bypass tenant-scoped
Core/Gateway query APIs. It is shared infrastructure, so the reset is intentionally
not a tenant data mutation. In a multi-workspace deployment, treat workspace-owner
access as an operator trust boundary and do not expose the dashboard to untrusted
workspace owners without adding a separate platform-operator capability.

## Configuration and recovery

The retention mismatch appears in the dashboard's system warnings. The warning
includes the actual and expected policy and offers the reset action to the owner.
The dashboard localizes its text from stable warning and error codes; services
continue to answer in English.

If the consumer is unavailable, or a reset fails after the safety gate, no success
is reported. Use the operator fallback in [Operations — rebuilding a workspace
from scratch](../operations.md#rebuilding-a-workspace-from-scratch), inspect the
two consumer counters, and only delete the stream when both are zero. Do not skip
that assertion: an unacknowledged event may not yet exist in PostgreSQL.

After recovery, re-import through the tenant's configured connectors. Imported
points remain available through the normal tenant-scoped Core/Gateway APIs and
retain their usual idempotency and provenance behavior.
