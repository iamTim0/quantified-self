# WHOOP Importer

## Ziel

Der WHOOP-Importer normalisiert Rohdaten in tenant-scoped Quantified-Self-Metriken und veröffentlicht sie über NATS JetStream. Core übernimmt Speicherung, Deduplizierung und spätere API-Abfragen.

## Datenzugang

- Quelle: WHOOP OAuth Access Token.
- Credentials werden im Dashboard konfiguriert und in Core verschlüsselt gespeichert.
- Der Importer fragt Credentials dynamisch über Core ab und bleibt ohne gültige Konfiguration idle.

### Token-Erneuerung

WHOOP-Access-Tokens laufen nach etwa einer Stunde ab, das Abfrageintervall liegt
aber typischerweise bei sechs. Ohne Erneuerung funktionierte der Connector also
genau eine Stunde, danach kamen nur noch `401`-Antworten, bis jemand von Hand ein
neues Token einsetzte.

Core erneuert das Token deshalb selbst, **bevor** es abläuft (fünf Minuten
Vorlauf). Auf ein `401` zu reagieren hieße, jeden Import mit einem sicher
fehlschlagenden Request zu beginnen.

Dafür werden neben dem Access Token gebraucht:

| Feld | Zweck |
| --- | --- |
| `refresh_token` | wird verschlüsselt gespeichert, verlässt Core nie |
| `client_id` | OAuth-Client der WHOOP-Anwendung |
| `client_secret` | wird verschlüsselt gespeichert |
| `expires_in` | Laufzeit des Access Tokens in Sekunden |

WHOOP tauscht bei jeder Erneuerung auch den Refresh Token aus und entwertet den
vorherigen; der neue wird gespeichert. Kommt in der Antwort keiner mit, bleibt der
bisherige erhalten — ihn zu löschen würde einen noch gültigen Connector
unerneuerbar machen.

Wird der Refresh Token abgelehnt (Zugriff widerrufen), antwortet Core mit `409`
und der Hinweis, den Connector neu zu verbinden. Ein bereits abgelaufenes Token
zurückzugeben würde den Fehler nur verschieben.

Der Importer bekommt ausschließlich das kurzlebige Access Token. Refresh Token und
Client Secret überqueren die Dienstgrenze nicht.

## Einrichtung

1. Im Dashboard unter **Connectors** die Datenquelle öffnen.
2. Zugangsdaten oder Export-Konfiguration eintragen.
3. Speichern; Core verschlüsselt die Credentials mit Fernet AES-256.
4. Bei aktiven Importern **Jetzt Sync** klicken oder den Worker zyklisch laufen lassen.

## Datenfluss

```text
Externe Quelle -> Importer -> qs.ingest.whoop -> Core -> data_points
```

## Wichtige Metriken

- `whoop_recovery_score`
- `whoop_sleep_performance_percent`
- `whoop_strain_score`
- `whoop_workout_duration_minutes`

## Daten abrufen

```http
GET /api/v1/data/metrics?metric_type=whoop_recovery_score&start_time=<iso>&end_time=<iso>&limit=1000
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

Filtere optional nach weiteren `metric_type` Werten aus dem Transformer.
