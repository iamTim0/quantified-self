# Kalender Importer

## Ziel

Der Kalender-Importer liest einen **ICS/iCalendar-Feed** und erzeugt daraus Zeitreihen
für Termine, Meetingdauer und belegte Zeit.

## Kein API Key für ICS-Feeds

Eine gültige `.ics`-URL funktioniert **ohne API Key**. Das gilt insbesondere für
Outlook/Microsoft 365, Google Calendar, iCloud und Nextcloud. Ein API Key ist nur
dann nötig, wenn dein Anbieter gar keinen ICS-Feed anbietet, sondern ausschließlich
eine eigene REST-API.

Der Importer unterscheidet vier Zugriffsarten und erkennt sie automatisch aus deiner
Konfiguration:

| Modus | Wann | Zugangsdaten |
| --- | --- | --- |
| `public_ics` | Öffentlich freigegebene `.ics`-URL | keine |
| `private_ics` | Private/„geheime" Feed-Adresse (langer Token im Pfad oder als Query-Parameter) | die URL selbst ist das Geheimnis |
| `basic_auth` | CalDAV-Server mit Benutzername/Passwort | Benutzername + Passwort |
| `api_key` | Anbieter-REST-API ohne ICS | Bearer Token |

Du kannst den Modus über `auth_mode` in der Connector-Konfiguration auch explizit
setzen, falls die automatische Erkennung nicht passt.

!!! warning "Private Feed-URLs sind Zugangsdaten"
    Eine private ICS-Adresse erlaubt jedem, der sie kennt, den vollständigen Zugriff
    auf deinen Kalender. Sie wird deshalb verschlüsselt gespeichert (Fernet AES-256)
    und niemals in Logs, Fehlermeldungen oder API-Antworten ausgegeben — dort
    erscheint nur `https://host/…`.

## Einrichtung

1. Im Kalenderprodukt einen iCalendar-/ICS-Abonnement-Link erzeugen.
2. Im Dashboard den Connector **Kalender** öffnen.
3. Die ICS-URL im Feld **Kalender-Feed URL (.ics)** eintragen. Das API-Key-Feld
   bleibt leer.
4. Optional Abfrageintervall und Zeitraum einstellen, dann Sync starten.

### Bezugsquellen

- **Google Calendar**: Kalendereinstellungen → „Geheime Adresse im iCal-Format".
- **Apple/iCloud**: Kalender freigeben → öffentlichen Kalenderlink kopieren
  (`webcal://` durch `https://` ersetzen).
- **Outlook/Microsoft 365**: Kalender veröffentlichen → ICS-Link kopieren.
- **Nextcloud**: Kalender teilen → Abonnement-Link kopieren.

## Wiederholungen und Zeitzonen

- `RRULE`, `EXDATE` und `RECURRENCE-ID` werden ausgewertet. Eine wöchentliche Serie
  erzeugt einen Datenpunkt pro Termin, nicht einen für die gesamte Serie.
- Verschobene Einzeltermine einer Serie (`RECURRENCE-ID`) ersetzen den Serientermin.
- `DTSTART;TZID=` und `VTIMEZONE` werden aufgelöst und nach UTC normalisiert.
- Ganztägige Termine (`VALUE=DATE`) und Termine ohne Zeitzone werden in der
  konfigurierten Anzeige-Zeitzone verankert (`timezone` in der Connector-Konfiguration,
  Standard `UTC`). „War ich am Dienstag beschäftigt?" ist eine lokale Frage.
- Abgesagte Termine (`STATUS:CANCELLED`) und als frei markierte Einträge
  (`TRANSP:TRANSPARENT`) werden importiert, zählen aber nicht als belegte Zeit.

## Metriken

| Metrik | Bedeutung |
| --- | --- |
| `calendar_event_count` | Anzahl der Termine pro Tag (`count`) |
| `calendar_busy_duration` | Summe belegter Zeit pro Tag (`min`) |
| `calendar_meeting_duration` | Dauer eines einzelnen Termins (`min`) |

`calendar_busy_hours` gibt es nicht mehr. Die Metrik trug dieselbe Zahl wie
`calendar_busy_minutes`, nur in einer anderen Einheit - allein deshalb, weil die
Einheit im Namen stand. Die Korrelationsanalyse meldete die beiden folgerichtig als
perfekt korrelierte Serien. Die Einheit steht jetzt in der Registry, eine Metrik
genügt, und die Darstellung in Stunden ist Sache der Oberfläche.

Pro-Termin-Datenpunkte werden über UID und ggf. `RECURRENCE-ID` eindeutig
identifiziert. Zwei verschiedene Termine zur selben Minute kollidieren daher nicht.

## Daten abrufen

```http
GET /api/v1/data/metrics?metric_type=calendar_busy_duration&start_time=<iso>&end_time=<iso>
Authorization: Bearer <jwt>
```

Der Tenant wird aus dem Token abgeleitet; ein separater `X-Tenant-ID`-Header ist
nicht erforderlich.

## Fehlerbehebung

| Symptom | Ursache | Lösung |
| --- | --- | --- |
| „Calendar URL returned an HTML page" | Der Feed verlangt eine Anmeldung, oder die geheime Adresse wurde zurückgezogen | Neue Feed-URL im Kalenderprodukt erzeugen |
| „Calendar feed not found (404)" | Adresse widerrufen oder Kalender gelöscht | Link neu erzeugen |
| „not iCalendar data" | Die URL zeigt auf eine Web-Ansicht statt auf den Feed | ICS-Link statt Kalender-Weblink verwenden |
| Keine Termine importiert | Alle Termine liegen außerhalb des Importzeitraums | Zeitraum im Importdialog erweitern |

## Einschränkungen

- Reine CalDAV-Discovery (`PROPFIND`) wird nicht unterstützt, nur direkte
  Feed-URLs.
- Ein Feed mit mehr als 10.000 Terminen im Zeitraum wird abgeschnitten; das wird
  protokolliert.
- Teilnehmerlisten, Beschreibungen und Anhänge werden nicht importiert.

## Referenzen

- [iCalendar.org](https://icalendar.org/) für Standardressourcen und Validatoren.
- [RFC 5545 / iCalendar Überblick](https://en.wikipedia.org/wiki/ICalendar) als
  Einstieg in Felder wie `VEVENT`, `DTSTART` und `DTEND`.

Die vollständige Definition jeder Metrik - Einheit, Aggregation und die alten Namen, die noch darauf zeigen - steht in [Metriken](../metrics.md).
