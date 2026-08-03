# Apple Health Importer Service (Health Auto Export JSON)

Quantified Self microservice for importing Apple Health data exported via the Health Auto Export app (https://www.healthyapps.dev/).

## Ingestion Modes

1. **HTTP Webhook (Push Ingestion)**:
   - Endpoint: `POST /ingest` (or `POST /api/v1/ingest/apple-health`)
   - Header: `X-Tenant-ID: <tenant_uuid>` or `X-Api-Key: <api_key>`
   - Payload: Health Auto Export JSON body (`data.metrics`, `data.workouts`)

2. **CLI Import (File Ingestion)**:
   ```bash
   python -m apple_health_importer.cli --file path/to/export.json --tenant-id <UUID>
   ```

## NATS Event Destination
Publishes standardized `IngestEvent` payloads to JetStream subject `qs.ingest.apple_health`.
