# Streak 2.0 Gym Log Importer Service

Quantified Self microservice for importing gym workout data and exercise sets exported via the Streak 2.0 app (https://github.com/iamTim0/Streak-2.0).

## Ingestion Modes

1. **REST Push / Webhook Ingestion**:
   - Endpoint: `POST /ingest` (or `POST /api/v1/ingest/streak`)
   - Server Reachability Check: Supports `HEAD` and `GET /ingest`
   - Headers: `X-Tenant-ID: <tenant_uuid>` or `X-Api-Key: <api_key>`
   - Payload: Streak 2.0 JSON export (`schemaVersion`, `exportedAt`, `workouts`)

2. **CLI Import (File Ingestion)**:
   ```bash
   python -m streak_importer.cli --file path/to/streak_export.json --tenant-id <UUID>
   ```

## NATS Event Destination
Publishes standardized `IngestEvent` payloads to JetStream subject `qs.ingest.streak`.
