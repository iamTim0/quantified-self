# Tenant-gebundene API-Keys

## Wofür

Manche Datenquellen senden Daten aktiv an die Plattform, statt abgefragt zu werden —
derzeit **Apple Health** (Health Auto Export) und **Streak**. Diese Dienste
authentifizieren sich mit einem API-Key, den du im Dashboard erzeugst.

## Ein Header genügt

Der externe Dienst sendet ausschließlich:

```http
POST /api/v1/ingest/apple-health
Authorization: Bearer <api-key>
Content-Type: application/json
```

Ein separater `X-Tenant-ID`-Header ist **nicht** erforderlich und wird auch nicht
akzeptiert, wenn er einem anderen Tenant zugeordnet ist als der Key. Der Tenant wird
serverseitig aus dem Key ermittelt.

Aus Kompatibilitätsgründen wird weiterhin auch `X-Api-Key: <api-key>` akzeptiert,
weil bestehende Health-Auto-Export- und Streak-Konfigurationen diesen Header
verwenden.

## Wie die Zuordnung funktioniert

1. Der Importer bildet lokal den SHA-256-Hash des präsentierten Keys.
2. Er fragt Core nach dem **Hash** — der Key selbst verlässt den Randdienst nie.
3. Core sucht den Hash, prüft Status, Ablaufdatum und erlaubte Datenquelle und
   liefert die zugehörige `tenant_id` zurück.
4. Jedes daraus erzeugte Event trägt diese `tenant_id`, einen deterministischen
   `idempotency_key` und die `X-Request-ID`.

Schlägt irgendein Schritt fehl — unbekannter Key, widerrufener Key, abgelaufener Key,
Key für eine andere Datenquelle, oder Core nicht erreichbar — wird der Request
abgelehnt. Es gibt keinen Pfad, auf dem unauthentifizierte Daten angenommen werden.

## Was gespeichert wird

| Feld | Zweck |
| --- | --- |
| `key_prefix` | die ersten 12 Zeichen, zur Wiedererkennung in UI und Logs |
| `key_hash` | SHA-256 des Keys; das Einzige, woraus der Tenant abgeleitet wird |
| `tenant_id` | Besitzer |
| `source_type` | erlaubte Datenquelle |
| `scopes` | Berechtigungen, standardmäßig nur `ingest` |
| `status` | `active` oder `revoked` |
| `expires_at` | optionales Ablaufdatum |
| `last_used_at` | letzte erfolgreiche Verwendung |
| `created_at`, `created_by_user_id` | Herkunft |

Der vollständige Key wird **nur einmal** bei der Erzeugung angezeigt und danach nie
wieder — weder in der Liste, noch in Logs, Fehlermeldungen oder Events.

## Rotation ohne Unterbrechung

Beim Rotieren wird ein zweiter Key erzeugt, während der alte aktiv bleibt:

1. `POST /api/v1/data/api-keys/{id}/rotate` → neuer Key wird einmalig angezeigt.
2. Externen Dienst auf den neuen Key umstellen.
3. `POST /api/v1/data/api-keys/{id}/revoke` für den alten Key.

Mehrere aktive Keys pro Tenant sind ausdrücklich vorgesehen. Erst der Widerruf
beendet die Gültigkeit des alten Keys — sofort und ohne Cache.

## API

| Methode | Pfad | Rolle | Zweck |
| --- | --- | --- | --- |
| `POST` | `/api/v1/data/api-keys` | owner, admin | Key erzeugen (zeigt Key einmalig) |
| `GET` | `/api/v1/data/api-keys` | alle | Keys auflisten (ohne Key-Material) |
| `POST` | `/api/v1/data/api-keys/{id}/rotate` | owner, admin | Nachfolger erzeugen |
| `POST` | `/api/v1/data/api-keys/{id}/revoke` | owner, admin | Sofort ungültig machen |

```http
POST /api/v1/data/api-keys
Authorization: Bearer <jwt>

{ "name": "iPhone Health Auto Export", "source_type": "apple_health", "expires_in_days": 365 }
```

## Sicherheitseigenschaften

- Ein Key für `apple_health` funktioniert nicht am Streak-Endpunkt (`403`).
- Ein Key eines anderen Tenants ist unsichtbar und nicht widerrufbar (`404`).
- Ein widersprüchlicher `X-Tenant-ID`-Header führt zu `403`, nicht zu stiller
  Korrektur.
- Fehlender oder ungültiger Key: `401`. Fehlende Berechtigung: `403`.

## Grenzen

- Keys sind derzeit nur für Push-Quellen (`apple_health`, `streak`) vorgesehen.
- Es gibt noch kein automatisches Ablauf-Reminder oder Nutzungs-Reporting über
  `last_used_at` hinaus.
