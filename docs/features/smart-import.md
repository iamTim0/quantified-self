# Smart- und Force-Import

## Was das Feature tut

Beim Import eines Connectors prüft die Plattform zuerst, welche Teile des
gewünschten Zeitraums **bereits vollständig vorhanden** sind, und importiert nur den
Rest. Der Zeitraum selbst wird dabei automatisch an die tatsächliche Importfrequenz
des Connectors angepasst.

Vorher wurde bei jedem Sync unabhängig vom Datenbestand ein fester Zeitraum (Standard
30 Tage) erneut abgefragt. Das erzeugte bei jedem Lauf tausende Duplicate Events, die
zwar durch die Idempotenzprüfung verworfen wurden, aber unnötig Rechenzeit und
API-Kontingent des Anbieters verbrauchten.

## Warum Core und nicht der Importer entscheidet

Die Entscheidung braucht die Import-Historie, und nur `services/core/` besitzt die
Datenbank (AGENTS.md Regel 1). Core berechnet deshalb das Fenster und schickt
`window_start`, `window_end` und `mode` im NATS-Task `qs.task.sync.<source>` mit. Der
Importer führt aus, was er bekommt.

```text
Dashboard ──► Gateway ──► Core (berechnet Fenster, legt SyncRun an)
                            │
                            ├──► NATS qs.task.sync.<source>  { window_start, window_end, mode, sync_run_id }
                            │                                        │
                            │                                   Importer
                            │                                        │
                            └──◄── NATS qs.ingest.<source> ◄─────────┘
```

## Adaptive Importzeiträume

Der Überlappungszeitraum richtet sich nach dem konfigurierten Abfrageintervall:

| Abfrageintervall | Überlappung |
| --- | --- |
| stündlich | 2 Stunden |
| alle 3 Stunden | 6 Stunden |
| alle 6 Stunden | 12 Stunden |
| täglich | 48 Stunden |
| wöchentlich | 72 Stunden (Obergrenze) |

Der nächste Import beginnt also um diese Überlappung **vor** dem Ende des letzten
erfolgreichen Laufs. Damit gehen keine Daten verloren, die beim Anbieter verspätet
eintreffen, und ein einzelner ausgefallener Lauf wird automatisch nachgeholt.

Weitere Regeln:

- Ohne vorherigen erfolgreichen Lauf wird der volle konfigurierte Lookback verwendet.
- Ist eine ältere Datenlücke bekannt, wird das Fenster bis dorthin ausgedehnt.
- Das Fenster wird immer auf den konfigurierten Lookback begrenzt.
- Nur ein Lauf mit Status `success` verschiebt den Wiederaufsetzpunkt.

## Duplikaterkennung auf Zeitraum-Ebene

Die Prüfung läuft **grob nach fein**, nicht Datenpunkt für Datenpunkt:

1. Eine einzige Aggregatabfrage zählt die Datenpunkte je Zeitblock über den gesamten
   Zeitraum.
2. Jeder Block wird gegen die beobachtete Datendichte (Median der nicht-leeren
   Blöcke) als **vollständig**, **teilweise** oder **leer** eingestuft.
3. Die Grenzen zwischen vorhandenen und fehlenden Bereichen werden durch
   Intervallhalbierung verfeinert — etwa sechs Abfragen genügen, um einen Tagesblock
   auf 15 Minuten genau aufzulösen.

### Sicherheitsregel

Übersprungen wird **ausschließlich** ein Bereich, der nachweislich vollständig ist.
Alles Unsichere wird importiert:

- teilweise gefüllte Blöcke,
- unregelmäßige Messintervalle,
- stark fragmentierte Abdeckung (viele abwechselnd vorhandene und fehlende Blöcke).

Der Grund ist die Asymmetrie der Fehler: ein überflüssiger Import ist dank
Idempotenz folgenlos, ein fälschlich übersprungener Bereich bedeutet dauerhaften
Datenverlust.

## Smart-Modus (Standard)

Der Importdialog zeigt vor dem Start an, was passieren wird:

> „Bereits vorhanden: 01.07.2026 00:00–05.07.2026 00:00. Importiert wird nur der neue
> Zeitraum von 05.07.2026 00:00 bis 08.07.2026 12:00."

Ist der gesamte Zeitraum vorhanden, wird gar kein Task erzeugt:

> „Der Zeitraum von … bis … ist bereits vollständig vorhanden und wird übersprungen."

## Force-Modus

Mit **„Alles erzwingen"** wird der komplette angegebene Zeitraum erneut verarbeitet.

- Idempotenz und Datenintegrität bleiben aktiv — es entstehen keine doppelten Zeilen.
- Es entstehen mehr Duplicate Events und damit spürbar mehr Verarbeitungsaufwand.
- Der Lauf wird im Importprotokoll mit `mode = force` gekennzeichnet.

Force ist sinnvoll, wenn beim Anbieter rückwirkend Daten korrigiert wurden.

## API

### Importplan abrufen

```http
POST /api/v1/data/sources/{source_type}/import-plan
Authorization: Bearer <jwt>

{ "start": "2026-07-01T00:00:00Z", "end": "2026-07-08T00:00:00Z", "mode": "smart" }
```

Antwort (gekürzt):

```json
{
  "requested":        { "start": "...", "end": "..." },
  "covered_ranges":   [ { "start": "...", "end": "..." } ],
  "missing_ranges":   [ { "start": "...", "end": "..." } ],
  "recommended_range":{ "start": "...", "end": "..." },
  "skipped_ranges":   [ { "start": "...", "end": "..." } ],
  "confidence": "high",
  "reason": "Bereits vorhanden: … Importiert wird nur der neue Zeitraum von … bis …"
}
```

Lässt man `start` und `end` weg, liefert der Endpunkt das automatisch abgeleitete
Fenster samt Begründung in `window_reason`.

### Import auslösen

```http
POST /api/v1/data/sources/sync
Authorization: Bearer <jwt>

{ "source_type": "whoop", "mode": "smart" }
```

Antwortstatus `skipped` bedeutet, dass nichts zu tun war.

### Abdeckung abfragen

```http
GET /api/v1/data/coverage?start=<iso>&end=<iso>&source_type=whoop
Authorization: Bearer <jwt>
```

### Importhistorie

```http
GET /api/v1/data/sources/{source_type}/sync-runs?limit=20
Authorization: Bearer <jwt>
```

Jeder Lauf enthält Fenster, Modus, Auslöser, Status, übersprungene Bereiche sowie
die Zähler `points_received`, `points_accepted` und `points_duplicate`.

## Interpretation und Grenzen

- `confidence: "low"` heißt, dass die Datenlage keine sichere Bereichsaussage
  zulässt. Dann wird bewusst der volle Zeitraum importiert.
- Die erwartete Datendichte wird aus den vorhandenen Daten geschätzt. Bei sehr
  wenigen Datenpunkten ist diese Schätzung ungenau, und der Planer verhält sich
  entsprechend konservativ.
- Die Abdeckungsanalyse betrachtet Datenpunkte, nicht deren inhaltliche Richtigkeit.
  Ein Bereich kann vollständig und trotzdem fachlich falsch sein.
