# Yazio Importer

## Ziel

Der Yazio-Importer normalisiert Rohdaten in tenant-scoped Quantified-Self-Metriken und veröffentlicht sie über NATS JetStream. Core übernimmt Speicherung, Deduplizierung und spätere API-Abfragen.

## Datenzugang

- Quelle: Yazio OAuth/API Token aus der App-Integration.
- Credentials werden im Dashboard konfiguriert und in Core verschlüsselt gespeichert.
- Der Importer fragt Credentials dynamisch über Core ab und bleibt ohne gültige Konfiguration idle.

## Einrichtung

1. Im Dashboard unter **Connectors** die Datenquelle öffnen.
2. Zugangsdaten oder Export-Konfiguration eintragen.
3. Speichern; Core verschlüsselt die Credentials mit Fernet AES-256.
4. Bei aktiven Importern **Jetzt Sync** klicken oder den Worker zyklisch laufen lassen.

## Datenfluss

```text
Externe Quelle -> Importer -> qs.ingest.yazio -> Core -> data_points
```

## Wichtige Metriken

- `nutrition_calories_kcal`
- `nutrition_protein_g`
- `nutrition_carbs_g`
- `nutrition_fat_g`

## Daten abrufen

```http
GET /api/v1/data/metrics?metric_type=nutrition_calories_kcal&start_time=<iso>&end_time=<iso>&limit=1000
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

Filtere optional nach weiteren `metric_type` Werten aus dem Transformer.
