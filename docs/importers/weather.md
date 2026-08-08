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
| `weather_temperature` | Außentemperatur (`°C`) | Mit Schlafqualität, Puls und Aktivitätsniveau vergleichen. |
| `weather_temperature_apparent` | Gefühlte Temperatur (`°C`) | Belastung bei Outdoor-Aktivität einordnen. |
| `weather_humidity` | Luftfeuchtigkeit (`%`) | Schlafqualität und Raumklima gegenüberstellen. |
| `weather_precipitation` | Niederschlag (`mm`) | Kontext für Outdoor-Aktivität und GPS-Routen. |
| `weather_pressure` | Luftdruck (`hPa`) | Optional für Migräne-/Stimmungsanalysen. |
| `weather_wind_speed` | Windgeschwindigkeit (`km/h`) | Kontext für Lauf- und Radeinheiten. |
| `weather_cloud_cover` | Bewölkung (`%`) | Zusammen mit dem UV-Index als Lichtkontext. |
| `weather_uv_index` | UV-Index (`index`) | Kontext für Tageslicht-/Outdoor-Exposition. |

Die Namen trugen früher ihre Einheit als Suffix (`weather_temperature_c`,
`weather_wind_speed_kmh`). Die Einheit steht jetzt in der Registry - ein Wechsel der
Einheit wird damit zu einer Umrechnung statt zu einer zweiten Metrik.

## Daten abrufen

```http
GET /api/v1/data/metrics?metric_type=weather_temperature&start_time=<iso>&end_time=<iso>
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
```

Die vollständige Definition jeder Metrik - Einheit, Aggregation und die alten Namen, die noch darauf zeigen - steht in [Metriken](../metrics.md).
