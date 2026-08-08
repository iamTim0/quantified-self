# Streak Importer

## Ziel

Der Streak-Importer normalisiert Rohdaten in tenant-scoped Quantified-Self-Metriken und veröffentlicht sie über NATS JetStream. Core übernimmt Speicherung, Deduplizierung und spätere API-Abfragen.

## Datenzugang

- Quelle: Streak Export oder Webhook-Konfiguration.
- Credentials werden im Dashboard konfiguriert und in Core verschlüsselt gespeichert.
- Der Importer fragt Credentials dynamisch über Core ab und bleibt ohne gültige Konfiguration idle.

## Einrichtung

1. Im Dashboard unter **Connectors** die Datenquelle öffnen.
2. Zugangsdaten oder Export-Konfiguration eintragen.
3. Speichern; Core verschlüsselt die Credentials mit Fernet AES-256.
4. Bei aktiven Importern **Jetzt Sync** klicken oder den Worker zyklisch laufen lassen.

## Datenfluss

```text
Externe Quelle -> Importer -> qs.ingest.streak -> Core -> data_points
```

## Wichtige Metriken

- `workout_set_weight_kg_*`
- `workout_set_reps_*`
- `workout_total_volume`
- `workout_total_sets`

## Daten abrufen

```http
GET /api/v1/data/metrics?metric_type=strength_set_weight&start_time=<iso>&end_time=<iso>&limit=1000
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

Filtere optional nach weiteren `metric_type` Werten:

| `metric_type` | Bedeutung | Einheit |
| --- | --- | --- |
| `strength_set_weight` | Gewicht eines Satzes | `kg` |
| `strength_set_reps` | Wiederholungen eines Satzes | `count` |
| `strength_set_volume` | Gewicht x Wiederholungen | `kg` |
| `strength_set_heart_rate_max` | Maximalpuls im Satz | `bpm` |
| `strength_session_volume` | Volumen der gesamten Einheit | `kg` |
| `strength_session_sets` | Anzahl Sätze der Einheit | `count` |

Das Präfix ist `strength_` und nicht `workout_`: Unter `workout_*` liegen die
Aggregate ganzer Ausdauereinheiten von Apple Health und WHOOP.
`strength_set_heart_rate_max` ist der Spitzenpuls **eines Satzes**,
`workout_heart_rate_max` der einer ganzen Einheit - zwei verschiedene Größen, die
unter einem gemeinsamen Präfix wie Varianten voneinander aussahen.

Die vollständige Definition jeder Metrik - Einheit, Aggregation und die alten Namen, die noch darauf zeigen - steht in [Metriken](../metrics.md).
