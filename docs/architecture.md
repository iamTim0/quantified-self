# Architektur und Datenfluss

## Überblick

Die Plattform besteht aus unabhängig deploybaren Diensten mit einer strikten
Zuständigkeitsverteilung. Die wichtigste Regel: **nur `services/core/` besitzt die
Datenbank.** Kein anderer Dienst importiert einen Datenbanktreiber.

```text
                    ┌──────────────┐
   Browser ────────►│  API Gateway │  JWT prüfen, X-Request-ID setzen
                    └──────┬───────┘
                           │ HTTP (Authorization + X-Tenant-ID)
                    ┌──────▼───────┐
                    │     Core     │──► PostgreSQL (TimescaleDB, pgvector, PostGIS)
                    └──┬────────┬──┘
        qs.task.sync.* │        │ qs.ingest.*
                    ┌──▼────────┴──┐
                    │ NATS JetStream│
                    └──┬────────▲──┘
                       │        │
                  ┌────▼────────┴────┐
                  │    Importer      │  8 Dienste, zustandslos
                  └──────────────────┘
```

## Dienste

| Dienst | Aufgabe | Datenbankzugriff |
| --- | --- | --- |
| `services/api-gateway/` | Einstiegspunkt, JWT-Prüfung, Header-Injektion, Reverse Proxy | nein |
| `services/core/` | REST-API, Ingest-Consumer, Analysen, Importplanung | **ja, exklusiv** |
| `services/importers/*` | Abruf bzw. Empfang externer Daten | nein |
| `services/analysis/` | Platzhalter, siehe Einschränkungen | nein |
| `apps/dashboard/` | Next.js-Oberfläche | nein |

## Datenfluss beim Import

1. Die Nutzerin löst einen Import aus, oder ein Connector wird konfiguriert.
2. **Core berechnet das Zeitfenster** aus Abfrageintervall und Importhistorie
   (siehe [Smart- und Force-Import](features/smart-import.md)) und legt einen
   `SyncRun` an.
3. Core veröffentlicht `qs.task.sync.<source>` mit `tenant_id`, `request_id`,
   `sync_run_id`, `mode`, `window_start` und `window_end`.
4. Der Importer holt seine Zugangsdaten über
   `GET /api/v1/internal/data/sources/<source>/token` — er speichert selbst keine.
5. Der Importer ruft die Anbieter-API für genau dieses Fenster ab.
6. Für jeden Datenpunkt wird ein deterministischer `idempotency_key` gebildet und
   ein Event auf `qs.ingest.<source>` veröffentlicht.
7. Cores Consumer schreibt mit `INSERT … ON CONFLICT DO NOTHING` und zählt
   angenommene und doppelte Punkte auf den `SyncRun`.
8. Der Importer meldet das Ergebnis; nur ein erfolgreicher Lauf verschiebt den
   Wiederaufsetzpunkt.

Bei Push-Quellen (Apple Health, Streak) entfallen die Schritte 1–5: der externe
Dienst sendet direkt an den Importer, der den Tenant aus dem API-Key auflöst.

## Idempotenz

```text
idempotency_key = SHA256(tenant_id + ":" + source_id + ":" + metric_type + ":" + timestamp)
```

Die Eindeutigkeit in der Datenbank ist
`UNIQUE (tenant_id, idempotency_key, timestamp)`. Der Zeitstempel gehört dazu, weil
TimescaleDB die Partitionierungsspalte in jedem eindeutigen Index verlangt.

!!! warning "Folge dieser Einschränkung"
    Derselbe `idempotency_key` mit einem *anderen* Zeitstempel legt eine zweite
    Zeile an. Transformer müssen Zeitstempel deshalb normalisieren und dürfen
    niemals auf `now()` zurückfallen — genau dieser Fehler erzeugte früher bei
    jedem Sync neue Duplikate.

## Tenant-Isolation

- Jede Abfrage filtert nach `tenant_id`.
- Der Tenant wird ausschließlich aus dem geprüften Bearer-Token abgeleitet.
- Ein `X-Tenant-ID`-Header darf mit dem Claim übereinstimmen, ihn aber nie
  überschreiben; Widerspruch ergibt `403`.
- Interne Endpunkte (`/api/v1/internal/*`) sind vom Gateway nicht nach außen
  erreichbar.

Details: [Authentifizierung & Sessions](features/authentication.md).

## Korrelation

Jede Anfrage trägt eine `X-Request-ID`. Sie wird über Gateway, Core, das
NATS-Event und den Importer propagiert und erscheint in allen Logs als
`[req_id=…]`.

## Datenmodell (Auszug)

| Tabelle | Zweck |
| --- | --- |
| `tenants`, `users` | Arbeitsbereich und Identitäten getrennt |
| `data_sources` | Ein Connector pro (tenant, source_type) |
| `data_points` | Zeitreihe, TimescaleDB-Hypertable |
| `sync_runs` | Import-/Auditprotokoll, Grundlage adaptiver Fenster |
| `api_keys` | Tenant-gebundene eingehende Schlüssel, nur als Hash |
| `refresh_tokens`, `revoked_access_tokens` | Sitzungen und Widerruf |
| `tenant_shares` | Freigaben zwischen Arbeitsbereichen |
| `explorer_views` | Gespeicherte Abfragen |

Migrationen laufen ausschließlich über Alembic in `services/core/alembic/` und
müssen ein funktionierendes `downgrade()` enthalten. Die CI prüft das, indem sie
nach dem Upgrade einen Rollback und ein erneutes Upgrade ausführt.

## Bekannte Einschränkungen

- **`services/analysis/` ist ein Platzhalter.** Es enthält keinen gRPC-Client, in
  keiner Compose-Datei ist es eingetragen, und Cores gRPC-Server ist ein Stub.
  Die Analysen laufen derzeit in Core (`core/insights.py`) und werden per REST
  ausgeliefert.
- **Es gibt keinen Scheduler.** Syncs werden ausgelöst, wenn ein Connector
  konfiguriert wird oder jemand einen Import startet. `poll_interval_hours` steuert
  die Fenstergröße, nicht eine automatische Ausführung.
