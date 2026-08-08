# Home Assistant Importer

## Ziel

Der Home-Assistant-Importer liest ausgewählte Sensorzustände über die Home Assistant REST API und macht Raumklima, Licht, Geräusche oder Anwesenheit als Zeitreihen analysierbar.

## Einrichtung in Home Assistant

1. In Home Assistant im Browser anmelden.
2. Profil öffnen (`http://<home-assistant-host>:8123/profile`).
3. Unter **Long-Lived Access Tokens** ein Token für Quantified Self erzeugen.
4. Im Dashboard den Connector **Home Assistant** öffnen.
5. Base URL, Token und optional erlaubte `entity_id`-Muster speichern, z. B. `sensor.schlafzimmer_temperature`.

Home Assistant REST Requests verwenden den Header `Authorization: Bearer <TOKEN>`. Long-lived Tokens werden im Profil erzeugt und sind für Integrationen gedacht.

## Metriken

| Beispiel-Entity | Normalisierte Metrik | Nutzen |
| --- | --- | --- |
| `sensor.living_room_temperature` | `home_assistant_living_room_temperature` | Schlaf-/Erholungsqualität mit Raumtemperatur vergleichen. |
| `sensor.bedroom_humidity` | `home_assistant_bedroom_humidity` | Trockene Luft oder hohe Luftfeuchte sichtbar machen. |
| `sensor.hallway_illuminance` | `home_assistant_hallway_illuminance` | Lichtmenge mit Tagesrhythmus korrelieren. |
| `binary_sensor.window_open` | `home_assistant_window_open` | Zustände werden als `1`/`0` gespeichert. |

Der Metrikname entsteht aus der `entity_id`: alles nach dem Punkt, kleingeschrieben,
mit dem Präfix `home_assistant_`. Welche Entitäten es gibt, entscheidet die
Einrichtung des Nutzers, nicht der Hersteller - deshalb ist `home_assistant_` in der
Registry als *dynamischer Namensraum* eingetragen. Namen darunter sind erlaubt, ohne
katalogisiert zu sein, und tragen ihre Einheit in `metadata.unit` (aus
`unit_of_measurement`) statt in der Registry.

## Daten abrufen

```http
GET /api/v1/data/metrics?metric_type=home_assistant_living_room_temperature&start_time=<iso>&end_time=<iso>
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
```

## Sicherheit

Das Home Assistant Token wird ausschließlich in Core verschlüsselt gespeichert. Es darf nicht in NATS Events, Logs oder `.env` Dateien gelangen.

## Referenzen

- [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/)
- [Home Assistant Authentication API](https://developers.home-assistant.io/docs/auth_api)

Die vollständige Definition jeder Metrik - Einheit, Aggregation und die alten Namen, die noch darauf zeigen - steht in [Metriken](../metrics.md).
