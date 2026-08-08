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
- Hat der Anmeldeanbieter die Sitzung beendet? Ein
  [Back-Channel-Logout](features/oidc.md#back-channel-logout) beendet alle
  Sitzungen des Kontos. Im Log steht dann `Back-Channel logout from … ended every
  session for user=…`.

### Ich lande beim Aufruf einer Unterseite auf der Anmeldeseite

Das ist der [Route-Guard](features/authentication.md#serverseitiger-route-guard).
Er prüft, ob ein `qs_csrf`-Cookie vorhanden ist, und leitet sonst auf
`/?next=<Ziel>` um; nach der Anmeldung geht es dort weiter. Wer sein Cookie-
Verzeichnis geleert oder Cookies für diese Seite blockiert hat, sieht das bei
jedem Aufruf.

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

## Lokale Entwicklung

### Jeder API-Aufruf des Dev-Servers antwortet mit 404

`GET /api/v1/auth/config 404`, `/api/v1/auth/me 404` im Log von `next dev`: die
404 kommt von Next selbst, nicht vom Gateway. Die UI ruft ihren eigenen Ursprung
auf, und der ist hier der Dev-Server. `next.config.ts` schreibt `/api/*` deshalb
im Entwicklungsmodus an den Gateway um (`DEV_GATEWAY_URL`, Standard
`http://127.0.0.1:8000`).

Kommt die 404 trotzdem: läuft der Gateway? Der Dev-Server liest `next.config.ts`
nur beim Start neu — nach einer Änderung daran startet er selbst durch, nach
einem Wechsel von `DEV_GATEWAY_URL` nicht.

### Jede Seite braucht ungefähr 13 Sekunden

Gemessen und behoben: der Gateway hat die UI unter drei Adressen gesucht und mit
der falschen angefangen. `dashboard` löst außerhalb von Docker nicht auf (~2,7 s
DNS-Fehler), `host.docker.internal` löst auf, aber dort hört nichts zu — also lief
der Verbindungs-Timeout von 10 s vollständig ab, bevor `127.0.0.1:3000` in ~50 ms
antwortete. Zusammen 12,7 s, und zwar **pro Anfrage**, weil das Ergebnis nirgends
gemerkt wurde.

Der Standard ist jetzt loopback, die Reihenfolge stellt loopback vor
`host.docker.internal`, und die Adresse, die geantwortet hat, wird gemerkt. Im
Container setzen beide Compose-Dateien `DASHBOARD_URL` ausdrücklich auf den
Containernamen.

Tritt es wieder auf, ist `DASHBOARD_URL` falsch gesetzt: ein Name, der nicht
auflöst, kostet dieselbe Verzögerung erneut.

### Der Analyse-Reiter meldet 503

Der Gateway schleift `/api/v1/analysis/*` an den Analysis-Service durch. Läuft
er? `task dev:local` startet ihn mit; einzeln geht `task run:analysis` (Port
8010). `ANALYSIS_SERVICE_URL` muss auf denselben Port zeigen.

### `http://localhost:8080` antwortet mit 404

Traefik läuft, hat aber nichts zu verteilen. Es findet seine Routen ausschließlich
über Docker-Labels, und die gibt es nur an Containern — im Modus `dev:local` laufen
die Dienste als Prozesse auf dem Host und sind für Traefik unsichtbar. Dann ist
`:3000` die richtige Adresse, nicht `:8080`.

Prüfen lässt sich das ohne Raten: `curl -s http://localhost:8081/api/http/routers`
listet auf, was Traefik tatsächlich kennt. Stehen dort nur `api@internal` und
`dashboard@internal`, ist keine einzige Anwendungsroute geladen.

### Die Oberfläche bleibt auf `:8000` weiß

Erwartet. Der Gateway kann `next dev` durchschleifen, aber die Seite hydriert
dahinter nicht — untersucht und im Quelltext festgehalten (`proxy_dashboard_ui` in
`services/api-gateway/src/gateway/main.py`): das durchgereichte Dokument ist
byteweise identisch, der HMR-Socket verbindet, und die Seite wird trotzdem nie
interaktiv. Der Port des Gateways ist für produktionsnahe Prüfungen gegen einen
gebauten Stand gedacht, nicht für die Entwicklung.

Hinter **Traefik** hydriert derselbe Dev-Server dagegen einwandfrei; das ist mit
einem Browsertest gegen `:8080` nachgemessen. Es liegt also am Durchschleifen im
Gateway, nicht an `next dev`.

### Eine UI-Änderung wird im Container-Stack nicht sichtbar

Kein Fehler in der Konfiguration, sondern eine Grenze der Plattform. Turbopack
erkennt Änderungen über inotify, und ein Docker-Bind-Mount eines Windows- oder
macOS-Verzeichnisses liefert diese Ereignisse nicht in den Container. Der Container
liest die Datei korrekt — ein `tail` darin zeigt die Änderung sofort —, nur erfährt
der Beobachter nichts davon. Eine neu angelegte Route antwortet dauerhaft mit 404,
eine geänderte liefert weiter das alte Markup, und zwar ohne jede Meldung.

`watchOptions.pollIntervalMs` aus `next.config.ts` ist die dokumentierte Antwort auf
genau diesen Fall und wurde zuerst versucht. Sie erreicht den Turbopack-Beobachter
nachweislich, half aber nicht: bei 1 s Intervall war eine geänderte Route auch nach
45 s nicht übernommen. Die Einstellung wurde deshalb wieder entfernt, statt als
scheinbare Lösung stehen zu bleiben — wer sie erneut erwägt, hat sie hiermit
bereits ausprobiert.

Was hilft: `docker compose … restart dashboard` (rund zehn Sekunden, kein Neubau,
weil der Code gemountet ist), oder für längere Arbeit an der Oberfläche `next dev`
nativ auf dem Host.

Die Python-Dienste sind davon nicht betroffen: uvicorn startet mit `StatReload`,
das die Dateien abfragt statt auf Ereignisse zu warten, und übernimmt Änderungen
über denselben Mount zuverlässig.

### `/docs` läuft in eine Weiterleitungsschleife

Behoben, hier steht das Warum. `mkdocs serve` liest `site_url` aus `mkdocs.yml`,
das auf `/docs/` endet, und liefert die Seite unter genau diesem Präfix aus — im
eigenen Log als `Serving on http://0.0.0.0:8003/docs/` zu sehen. Traefik hat das
Präfix zusätzlich abgeschnitten, MkDocs bekam `GET /` und antwortete mit
`302 → /docs/`, was erneut abgeschnitten wurde.

Im Entwicklungs-Stack gibt es deshalb keine `stripprefix`-Middleware. In der
Produktion schon, und das ist richtig: dort ist die Dokumentation ein per
`mkdocs build` erzeugtes Abbild, das an der Wurzel liegt.

Beim Nachmessen lohnt `curl` **ohne** `-L`: mit gefolgten Weiterleitungen meldet es
die 200 der Anmeldeseite, auf der man am Ende landet, und die Schleife sieht aus
wie ein Erfolg.

## Konfiguration

### Core oder Gateway startet nicht: „refuses to start with published secrets"

Genau das ist beabsichtigt. `ENVIRONMENT` ist produktiv gesetzt und mindestens
einer der Werte `JWT_SECRET`, `INTERNAL_SERVICE_SECRET`, `ENCRYPTION_KEY` fehlt
oder entspricht einem Default, der in diesem Repository steht. Die Meldung nennt
alle betroffenen Variablen auf einmal. Siehe
[Betrieb](operations.md#erforderliche-konfiguration).

Für lokale Entwicklung `ENVIRONMENT=dev` setzen — dann wird nur gewarnt.

### `docker compose` bricht ab mit „set JWT_SECRET"

`docker-compose.prod.yml` verwendet `${VAR:?…}`. Eine fehlende Variable stoppt
den Deploy, bevor ein Container startet. Vorher hätte derselbe Deploy mit dem
öffentlichen Default weitergelaufen, ohne etwas zu sagen.

### Connector-Zugangsdaten lassen sich nicht mehr entschlüsseln

`ENCRYPTION_KEY` unterscheidet sich von dem, mit dem sie gespeichert wurden. Mit
dem alten Wert umschlüsseln statt ihn zu erraten:

```bash
python -m core.rotate_encryption_key --old "$ALT" --new "$NEU" --dry-run
```

Der Probelauf sagt, welche Werte auf welchem Schlüssel liegen, und schreibt
nichts. Der vollständige Ablauf steht unter
[`ENCRYPTION_KEY` wechseln](operations.md#encryption_key-wechseln).
