# Apple-Health-Importer

Der Apple-Health-Importer übernimmt Gesundheits- und Aktivitätsdaten aus Apple Health in die Quantified-Self-Plattform. Die Rohdaten werden in ein einheitliches Metrikformat übersetzt und tenant-getrennt an den Core-Service übergeben.

## Voraussetzungen

- Apple Health ist auf dem iPhone eingerichtet.
- Für den Export ist **Health Auto Export** oder eine kompatible JSON-/Webhook-Quelle konfiguriert.
- Die Datenquelle ist im Dashboard für den richtigen Workspace (Tenant) eingerichtet.
- Der Importer läuft und kann den Core-Service erreichen.

Der Importer erzeugt keine Demo- oder Ersatzdaten. Ohne gültige Konfiguration bleibt er idle.

## Einrichtung

### 1. Apple-Health-Export vorbereiten

1. Öffne auf dem iPhone die Export-App beziehungsweise die für Apple Health eingerichtete Integration.
2. Erteile nur die Leseberechtigungen für die Gesundheitskategorien, die importiert werden sollen.
3. Aktiviere den JSON-Export oder den Webhook der Integration.
4. Übernimm die von der Integration benötigten Verbindungsdaten für die Connector-Konfiguration.

Die konkreten Menünamen und verfügbaren Gesundheitskategorien hängen von der verwendeten Export-App und deren Version ab.

### 2. Connector im Dashboard konfigurieren

1. Öffne im Dashboard **Connectors**.
2. Wähle **Apple Health**.
3. Hinterlege die Export-Konfiguration beziehungsweise die Zugangsdaten der Quelle.
4. Speichere die Konfiguration.
5. Starte anschließend **Jetzt Sync**, falls diese Aktion angeboten wird. Alternativ übernimmt der laufende Worker den nächsten geplanten Abruf.

Die Zugangsdaten werden vom Core-Service verschlüsselt gespeichert. Der Importer liest sie dynamisch aus dem Core-Service; sie gehören weder in eine `.env`-Datei noch in ein NATS-Event.

## Datenfluss

```text
Apple Health / Export-App -> Apple-Health-Importer
  -> NATS: qs.ingest.apple_health -> Core-Service -> data_points
```

Der Importer schreibt nicht direkt in die Datenbank. Der Core-Service ist der einzige Besitzer der Datenbank und dedupliziert anhand des `idempotency_key`. Jeder Import bleibt dem konfigurierten `tenant_id` zugeordnet.

## Importierte Metriken

| `metric_type` | Bedeutung | Einheit |
| --- | --- | --- |
| `steps` | Anzahl der Schritte | `count` |
| `distance` | Zurückgelegte Distanz | `km` |
| `energy_active` | Aktive Energie | `kcal` |
| `energy_resting` | Grundumsatz | `kcal` |
| `heart_rate` | Puls | `bpm` |
| `heart_rate_resting` | Ruhepuls | `bpm` |
| `hrv_sdnn` | Herzratenvariabilität (SDNN) | `ms` |
| `blood_oxygen` | Sauerstoffsättigung | `%` |
| `sleep_duration` | Schlafdauer | `min` |
| `sleep_duration_deep` / `_rem` / `_light` / `_awake` / `_in_bed` | Schlafphasen | `min` |
| `body_weight` | Körpergewicht | `kg` |
| `workout_duration`, `workout_distance`, `workout_energy`, `workout_heart_rate_average`, `workout_heart_rate_max` | Trainingseinheiten | `min`, `km`, `kcal`, `bpm` |

Health Auto Export liefert zu jeder Metrik die Einheit mit, und die richtet sich nach
dem Gebietsschema des Telefons - Meilen oder Kilometer, Stunden oder Minuten. Der
Importer liest diese Angabe und rechnet auf die Einheit der Registry um; der
ursprüngliche Wert bleibt in `metadata.provider_value`, die gemeldete Einheit in
`metadata.units`.

HealthKit-Typen, die der Katalog nicht kennt, landen unter dem Präfix
`apple_health_` (zum Beispiel `apple_health_dietary_water`). Sie gehen also nicht
verloren, belegen aber auch keinen kanonischen Namen.

Für Abfragen ist immer der exakte `metric_type`-Wert zu verwenden.

## Daten abrufen

Die Messwerte werden über die tenant-geschützte Core/Gateway-API abgefragt:

```http
GET /api/v1/data/metrics?metric_type=steps&start_time=2026-01-01T00:00:00Z&end_time=2026-01-08T00:00:00Z&limit=1000
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

Der JWT muss zum Workspace gehören, der im `X-Tenant-ID`-Header angegeben ist. `X-Request-ID` dient der Nachverfolgung eines Imports über API, Importer und NATS hinweg.

Für andere Messwerte wird nur der Query-Parameter ersetzt, zum Beispiel `active_energy_kcal`, `resting_heart_rate_bpm` oder `sleep_duration_hours`.

## Kontrolle und Fehlerbehebung

### Es erscheinen keine Werte

Prüfe in dieser Reihenfolge:

1. Ist der Apple-Health-Export aktiv und enthält er tatsächlich Daten?
2. Ist der Connector im richtigen Tenant gespeichert?
3. Ist die Konfiguration vollständig und gültig?
4. Wurde ein manueller Sync gestartet oder läuft der Worker?
5. Wird der erwartete `metric_type` abgefragt und liegt der Zeitraum in `start_time`/`end_time`?
6. Gibt es im Importer- oder Core-Log Einträge mit derselben `X-Request-ID`?

Ohne Connector-Konfiguration ist ein leerer Datenbestand erwartetes Verhalten. Der Importer erzeugt in diesem Fall keine Testdaten.

### Werte scheinen doppelt zu sein

Der Core-Service dedupliziert anhand des deterministisch gebildeten `idempotency_key`. Prüfe zunächst, ob tatsächlich derselbe Messwert mehrfach mit unterschiedlichen Zeitstempeln oder unterschiedlichen `metric_type`-Werten geliefert wurde.

## Datenschutz und Grenzen

Apple-Health-Daten sind besonders schützenswert. Konfiguriere nur die benötigten Kategorien und gewähre Zugriff ausschließlich dem vorgesehenen Tenant. Zugangsdaten werden verschlüsselt abgelegt und dürfen nicht in Logs, Broker-Nachrichten oder Quellcode auftauchen.

Die verfügbaren Daten hängen von Apple Health, den aktivierten Berechtigungen und der verwendeten Export-App ab. Ein erfolgreicher Connector-Sync garantiert daher nicht, dass für jeden Zeitraum Werte vorhanden sind. Die API liefert normalisierte Plattformmetriken; die ursprünglichen Apple-Health-Rohobjekte sind nicht das primäre Abfrageformat.

Die vollständige Definition jeder Metrik - Einheit, Aggregation und die alten Namen, die noch darauf zeigen - steht in [Metriken](../metrics.md).
