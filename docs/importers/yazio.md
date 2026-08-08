# Yazio Importer

## Ziel

Der Yazio-Importer normalisiert Rohdaten in tenant-scoped Quantified-Self-Metriken und veröffentlicht sie über NATS JetStream. Core übernimmt Speicherung, Deduplizierung und spätere API-Abfragen.

## Datenzugang

- Quelle: Yazio OAuth/API Token aus der App-Integration.
- Credentials werden im Dashboard konfiguriert und in Core verschlüsselt gespeichert.
- Der Importer fragt Credentials dynamisch über Core ab und bleibt ohne gültige Konfiguration idle.

!!! note "Der OAuth-Client ist nicht unser Geheimnis"
    Die Anmeldung bei Yazio verwendet deren Mobil-App-Client. Dessen `client_id`
    und `client_secret` stecken in einer ausgelieferten App, sind damit öffentlich
    und lassen sich von uns auch nicht wechseln. Sie standen fest verdrahtet in
    `client.py`, was wie ein geleaktes Geheimnis aussah, und liegen jetzt als
    `YAZIO_CLIENT_ID` / `YAZIO_CLIENT_SECRET` in der Konfiguration — mit denselben
    Werten als Default, ersetzbar für eine Installation mit eigenem Client.

    Die Zugangsdaten der Nutzerin sind davon unberührt: die kommen aus dem
    Dashboard und werden verschlüsselt aus Core geladen.

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
