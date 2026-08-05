# Kalender Importer

## Ziel

Der Kalender-Importer liest einen freigegebenen **ICS/iCalendar Feed** und erzeugt tägliche Zeitreihen für Termine, Meetingdauer und Busy Hours.

## Warum ICS?

iCalendar/ICS ist ein offenes Austauschformat für Kalenderdaten. Die Dateien oder Feed-URLs enthalten typischerweise `VEVENT`-Einträge mit Start-/Endzeiten, Titel und Wiederholungsinformationen. Viele Kalenderprodukte können private Abonnement-Links bereitstellen.

## Einrichtung

1. Im Kalenderprodukt einen privaten iCalendar-/ICS-Abonnement-Link erzeugen.
2. Im Dashboard den Connector **Kalender** öffnen.
3. Die ICS Feed URL als Token/Secret speichern.
4. Optional Lookback-Tage konfigurieren und Sync starten.

## Beispiele für Bezugsquellen

- Google Calendar: öffentliche oder geheime iCal-Adresse pro Kalender in den Kalendereinstellungen.
- Apple/iCloud Calendar: Kalender teilen und Kalenderlink als abonnierbare ICS-Quelle nutzen.
- Outlook/Microsoft 365: Kalender veröffentlichen und ICS-Link kopieren.
- Nextcloud Calendar: privaten Freigabelink bzw. Abonnement-Link verwenden.

## Metriken

| Metrik | Bedeutung |
| --- | --- |
| `calendar_event_count` | Anzahl der Termine pro Tag |
| `calendar_busy_hours` | Summe belegter Stunden pro Tag |
| `calendar_meeting_duration_minutes` | Dauer einzelner bzw. aggregierter Termine |

## Daten abrufen

```http
GET /api/v1/data/metrics?metric_type=calendar_busy_hours&start_time=<iso>&end_time=<iso>
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
```

## Referenzen

- [iCalendar.org](https://icalendar.org/) für Standardressourcen und Validatoren.
- [RFC 5545 / iCalendar Überblick](https://en.wikipedia.org/wiki/ICalendar) als Einstieg in Felder wie `VEVENT`, `DTSTART` und `DTEND`.
