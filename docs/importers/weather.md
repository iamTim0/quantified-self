# Wetter Importer

## Ziel

Der Wetter-Importer liest Wetter-Zeitreihen von einer Open-Meteo-kompatiblen API und erzeugt Kontextmetriken für Schlaf-, Aktivitäts- und Stimmungsauswertungen.

## Empfohlener Standard: Open-Meteo

Open-Meteo bietet HTTP-GET APIs mit JSON-Antworten, einheitlichen Parametern und für nicht-kommerzielle Nutzung ohne API-Key. Für kommerzielle Nutzung oder höhere Limits sollte ein bezahlter Endpoint mit API-Key eingeplant werden.

## Beispielquellen

- [Open-Meteo Forecast API](https://open-meteo.com/en/docs)
- [Open-Meteo Historical Weather API](https://open-meteo.com/)
- Nationale Wetterdienste oder selbst gehostete Gateways, sofern sie Open-Meteo-kompatible JSON-Zeitreihen liefern.

## Einrichtung

1. Standortkoordinaten oder eine vorkonfigurierte API URL im Dashboard-Connector speichern.
2. Optional Variablen wie Temperatur, Niederschlag, Luftdruck und UV-Index festlegen.
3. Sync starten; der Importer veröffentlicht `qs.ingest.weather` Events.

## Metriken

| Metrik | Bedeutung | Empfehlung |
| --- | --- | --- |
| `weather_temperature_c` | Außentemperatur in °C | Mit Schlafqualität, Puls und Aktivitätsniveau vergleichen. |
| `weather_precipitation_mm` | Niederschlag | Kontext für Outdoor-Aktivität und GPS-Routen. |
| `weather_pressure_hpa` | Luftdruck | Optional für Migräne-/Stimmungsanalysen. |
| `weather_uv_index` | UV-Index | Kontext für Tageslicht-/Outdoor-Exposition. |

## Daten abrufen

```http
GET /api/v1/data/metrics?metric_type=weather_temperature_c&start_time=<iso>&end_time=<iso>
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
```
