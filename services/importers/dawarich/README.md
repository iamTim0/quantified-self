# Dawarich Location Importer Service

Microservice that polls self-hosted Dawarich location history API, transforms GPS points into standard DataPoints with SHA256 idempotency keys, and publishes to NATS JetStream subject `qs.ingest.dawarich`.
