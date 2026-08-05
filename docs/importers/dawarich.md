# Dawarich Importer

## Ziel

Der Dawarich-Importer normalisiert Rohdaten in tenant-scoped Quantified-Self-Metriken und veröffentlicht sie über NATS JetStream. Core übernimmt Speicherung, Deduplizierung und spätere API-Abfragen.

## Datenzugang

- Quelle: Dawarich API-Key und Base URL.
- Credentials werden im Dashboard konfiguriert und in Core verschlüsselt gespeichert.
- Der Importer fragt Credentials dynamisch über Core ab und bleibt ohne gültige Konfiguration idle.

## Einrichtung

1. Im Dashboard unter **Connectors** die Datenquelle öffnen.
2. Zugangsdaten oder Export-Konfiguration eintragen.
3. Speichern; Core verschlüsselt die Credentials mit Fernet AES-256.
4. Bei aktiven Importern **Jetzt Sync** klicken oder den Worker zyklisch laufen lassen.

## Datenfluss

```text
Externe Quelle -> Importer -> qs.ingest.dawarich -> Core -> data_points
```

## Wichtige Metriken

- `location_point`
- `location_latitude`
- `location_longitude`

## Daten abrufen

```http
GET /api/v1/data/metrics?metric_type=location_point&start_time=<iso>&end_time=<iso>&limit=1000
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

Filtere optional nach weiteren `metric_type` Werten aus dem Transformer.
