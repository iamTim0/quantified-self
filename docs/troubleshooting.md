# Fehlerbehebung

## Import

### Ein Import meldet „übersprungen", obwohl Daten fehlen

Der Smart-Modus überspringt nur Bereiche, die er als vollständig erkennt. Prüfe
zuerst die Abdeckung:

```http
GET /api/v1/data/coverage?start=<iso>&end=<iso>&source_type=whoop
Authorization: Bearer <jwt>
```

Stimmt die Einschätzung nicht, importiere den Zeitraum mit **Alles erzwingen**
erneut. Idempotenz verhindert doppelte Zeilen. Siehe
[Smart- und Force-Import](features/smart-import.md).

### Ein Sync bleibt auf „queued" stehen

Der Task wurde veröffentlicht, aber kein Importer hat ihn abgeschlossen.

1. Läuft der Importer? `docker compose ps`
2. Erreicht er NATS? Im Log steht `Subscribed to NATS subject 'qs.task.sync.…'`.
3. Hat der Importer die Zugangsdaten bekommen? Bei fehlender Konfiguration
   protokolliert er „staying idle" und tut absichtlich nichts.
4. Prüfe den Lauf: `GET /api/v1/data/sources/{type}/sync-runs`.

### Es kommen Daten an, aber keine neuen

Normal, wenn der Zeitraum bereits importiert war: die Idempotenzprüfung verwirft
Duplikate. `points_accepted` gegen `points_duplicate` in der Importhistorie
vergleichen. Sind alle Punkte Duplikate, ist nichts kaputt.

### Ein Connector meldet dauerhaft „Auth Fehler (401)"

Der gespeicherte Token ist abgelaufen oder wurde widerrufen. Zugangsdaten im
Connector-Dialog neu hinterlegen. Für WHOOP gibt es keinen automatischen
Refresh-Flow — ein abgelaufener OAuth-Token muss ersetzt werden.

## Kalender

| Meldung | Ursache | Lösung |
| --- | --- | --- |
| „returned an HTML page instead of a calendar" | Login-Wall oder zurückgezogene Geheimadresse | Feed-URL im Kalenderprodukt neu erzeugen |
| „not found (404)" | Adresse widerrufen | Link neu erzeugen |
| „not iCalendar data" | URL zeigt auf die Web-Ansicht | ICS-Link statt Kalender-Weblink verwenden |
| Keine Termine | Alle Termine außerhalb des Fensters | Zeitraum erweitern |

Ein `.ics`-Link braucht **keinen** API Key. Wird trotzdem einer verlangt, ist die
URL vermutlich keine Feed-URL. Siehe [Kalender](importers/calendar.md).

## Anmeldung

### Nach dem Logout bin ich wieder angemeldet

Das war ein Fehler und ist behoben. Trat er erneut auf, wäre eine veraltete
Dashboard-Version im Browser-Cache die wahrscheinlichste Ursache — hart neu laden.

### Alle Anfragen liefern 401

- Ist das Zugriffstoken älter als seine Laufzeit (Standard 12 Stunden)? Das
  Dashboard erneuert automatisch, sofern ein Erneuerungstoken vorliegt.
- Wurde das Passwort geändert? Das beendet **alle** Sitzungen.
- Wurde ein verbrauchtes Erneuerungstoken erneut vorgelegt? Das gilt als
  möglicher Diebstahl und beendet ebenfalls alle Sitzungen. Neu anmelden.

### 403 statt 401

Authentifizierung war erfolgreich, die Berechtigung fehlt. Häufigste Fälle: ein
`X-Tenant-ID`-Header widerspricht dem Token, oder die Rolle darf keine API-Keys
verwalten (nur `owner` und `admin`).

## Eingehende Daten (Apple Health, Streak)

| Antwort | Bedeutung |
| --- | --- |
| `401` | Kein oder unbekannter Schlüssel, widerrufen oder abgelaufen |
| `403` | Schlüssel gehört zu einem anderen Connector oder der Tenant-Header widerspricht ihm |
| `503` | Core nicht erreichbar — bewusst kein „durchwinken"; das Gerät soll erneut senden |

Der vollständige Schlüssel ist nach der Erstellung nicht mehr abrufbar. Ist er
verloren, rotiere ihn und trage den neuen in der App ein.

## Karte

Die Karte zeigt standardmäßig eine reine Vektor-Route und lädt **absichtlich**
keine Kacheln. Über „Karte laden" lassen sich Kacheln anfordern. Bleibt die Karte
danach leer, blockiert die CSP vermutlich die Kachel-Hosts — `MAP_TILE_HOSTS`
prüfen.

## Analysen

### Eine Metrik taucht nicht auf

Analysen laufen nur bei ausreichender Datenbasis: mindestens zehn Tage und über
50 % Abdeckung im gewählten Fenster. Der Reiter **Datenqualität** zeigt pro Metrik,
woran es liegt. Das ist Absicht — eine Korrelation über vier Tage ist Rauschen mit
einer Zahl daran.

### Ein Zusammenhang wirkt unplausibel

Alle Ergebnisse sind Zusammenhänge, keine Ursachen. Prüfe in der Detailansicht
Stichprobengröße, p-Wert und die Hinweise. Weichen Pearson und Spearman stark
voneinander ab, steckt meist ein Ausreißer dahinter.

## Datenbank

### Tests scheitern mit „Connect call failed … 5433"

Postgres läuft nicht: `task dev:up`.

### Migration schlägt fehl mit „value too long for type character varying(32)"

Die Alembic-Revisions-ID ist zu lang. `alembic_version.version_num` fasst 32
Zeichen; Revisions-IDs müssen darunter bleiben.
