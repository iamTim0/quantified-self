# Importer-Überblick

Alle Importer folgen demselben Muster: konfigurierte Datenquelle im Dashboard anlegen, verschlüsselte Zugangsdaten in Core speichern, importer-spezifischen Worker starten und tenant-scoped Events nach NATS JetStream veröffentlichen.

| Importer | Typ | Datenzugang | NATS Subject | Wichtige Metriken |
| --- | --- | --- | --- | --- |
| Yazio | aktiv | Yazio API/OAuth-Token | `qs.ingest.yazio` | Kalorien, Makros, Mahlzeiten |
| WHOOP | aktiv | WHOOP API/OAuth | `qs.ingest.whoop` | Schlaf, Recovery, Strain, Workouts |
| Apple Health | passiv | Health Auto Export JSON/Webhook | `qs.ingest.apple_health` | Schritte, Herzfrequenz, Schlaf, Energie |
| Dawarich | aktiv | Dawarich API-Key | `qs.ingest.dawarich` | GPS-Punkte, Latitude, Longitude |
| Streak | passiv | Export/Webhook | `qs.ingest.streak` | Sets, Reps, Gewichte, Volumen |
| Home Assistant | aktiv | REST API + Long-lived Token | `qs.ingest.home_assistant` | Sensorwerte, Temperatur, Luftfeuchte |
| Wetter | aktiv | Open-Meteo-kompatible HTTP API | `qs.ingest.weather` | Temperatur, Druck, Niederschlag, UV |
| Kalender | aktiv | ICS/iCalendar Feed URL | `qs.ingest.calendar` | Events, Busy Hours, Meetingdauer |

## Daten abrufen

Importierte Daten liegen nicht in den Importern, sondern in Core. Über Gateway/Core werden Daten tenant-scoped abgefragt, z. B.:

```http
GET /api/v1/data/metrics?metric_type=weather_temperature_c&start_time=2026-08-01T00:00:00Z&end_time=2026-08-04T23:59:59Z
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

Die Antwort enthält `data_points`; jedes Element beschreibt eine normalisierte Messung mit `metric_type`, Zeitstempel, Wert, Quelle und Metadaten.
