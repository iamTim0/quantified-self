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
| `sensor.*temperature*` | `home_temperature_c` | Schlaf-/Erholungsqualität mit Raumtemperatur vergleichen. |
| `sensor.*humidity*` | `home_humidity_percent` | Trockene Luft oder hohe Luftfeuchte sichtbar machen. |
| `sensor.*illuminance*` | `home_illuminance_lux` | Lichtmenge mit Tagesrhythmus korrelieren. |
| `sensor.*noise*` | `home_noise_db` | Nächtliche Störungen bewerten. |

## Daten abrufen

```http
GET /api/v1/data/metrics?metric_type=home_temperature_c&start_time=<iso>&end_time=<iso>
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
```

## Sicherheit

Das Home Assistant Token wird ausschließlich in Core verschlüsselt gespeichert. Es darf nicht in NATS Events, Logs oder `.env` Dateien gelangen.

## Referenzen

- [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/)
- [Home Assistant Authentication API](https://developers.home-assistant.io/docs/auth_api)
