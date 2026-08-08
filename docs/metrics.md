# Metriken

Jede Messgröße, die die Plattform speichert, ist genau einmal definiert — in der
Registry unter `packages/shared-schemas/src/shared_schemas/metrics.py`. Diese Seite
erklärt, warum es sie gibt, welche Regeln sie durchsetzt und welche Metriken es gibt.

## Warum eine zentrale Definition

`metric_type` war vorher ein freier String. Jeder Importer hat seine Namen selbst
erfunden, und niemand konnte widersprechen:

- Apple Health schrieb `workout_avg_heart_rate`, WHOOP `workout_average_heart_rate` —
  dieselbe Größe, zwei Serien, die sich nie begegneten.
- WHOOP lieferte verbrannte Energie in **Kilojoule**, Apple Health in **Kilokalorien**,
  unter Namen, die beides verschwiegen. Die Konflikterkennung in
  `services/core/src/core/analytics.py` verglich also 8400 mit 2000 und meldete einen
  Widerspruch.
- Der Kalender-Importer schrieb `calendar_busy_minutes` **und** `calendar_busy_hours` —
  dieselbe Zahl zweimal, nur weil die Einheit im Namen steckte. Die Korrelationsanalyse
  meldete die beiden pflichtgemäß als perfekt korreliert.
- Das Dashboard suchte nach `steps`, `sleep_score`, `readiness_score`, `hrv_balance`,
  `resting_hr` und `carbs`. Keinen dieser Namen hat je ein Importer erzeugt; die Hälfte
  der Kacheln war dauerhaft leer.

Die Registry macht diese Zustände unmöglich, statt sie zu dokumentieren.

## Die beiden Regeln

**1. Eine Größe, ein Name.** Der Name sagt, *was* gemessen wurde — nie, *wer* gemessen
hat, und nie, *in welcher Einheit*. Zwei Quellen, die dieselbe physikalische Größe
liefern, schreiben denselben `metric_type`.

Ausnahme mit Absicht: herstellereigene Kennzahlen behalten ihr Präfix
(`whoop_strain`, `whoop_recovery_score`, `oura_sleep_score`). Ein Whoop-Strain ist mit
nichts außerhalb von Whoop vergleichbar, und ein Name ohne Präfix würde genau das
suggerieren.

**2. Ein Name, eine Einheit.** Die Einheit steht in der Registry, nicht im Namen. Die
Importer rechnen beim Transformieren um — WHOOPs Kilojoule werden zu Kilokalorien,
Apple Healths Meilen zu Kilometern, Stunden zu Minuten. Der Rohwert bleibt dabei in
`metadata.provider_value` erhalten, zusammen mit `metadata.units`: eine Umrechnung ist
ein Eingriff in fremde Daten, und die Frage „warum steht hier etwas anderes als in
meiner Health-App" muss beantwortbar bleiben.

Deshalb enthält kein kanonischer Name ein Einheitensuffix. Ein Test in
`packages/shared-schemas/tests/test_metrics.py` sorgt dafür, dass das so bleibt.

## Wo die Registry greift

| Stelle | Verhalten |
| --- | --- |
| Transformer der Importer | rufen `canonical_metric_type()` auf, **bevor** der `idempotency_key` gebildet wird |
| `shared_schemas.IngestEvent` | weist alles zurück, was nicht kanonisch ist — auch Aliase |
| Core NATS-Consumer | prüft jedes Event; unbekannte Namen werden mit Log-Eintrag verworfen statt gespeichert |
| Core Batch-/CSV-Import | bildet Aliase auf den kanonischen Namen ab, sonst HTTP 422 |
| `GET /api/v1/data/metrics/catalog` | liefert die vollständige Registry |
| Dashboard | nutzt `apps/dashboard/src/app/lib/metrics/catalog.ts`, generiert aus derselben Quelle |

Der `idempotency_key` ist `SHA256(tenant_id + source_id + metric_type + timestamp)`
(AGENTS.md Regel 4). Deshalb ist die Reihenfolge im ersten Punkt keine Stilfrage: Wer
erst den Schlüssel bildet und danach den Namen normalisiert, speichert einen Datenpunkt
unter einem Namen, den sein Schlüssel nicht beschreibt — und importiert dieselbe Messung
beim nächsten Lauf ein zweites Mal. Genau darum weist `IngestEvent` Aliase zurück,
anstatt sie stillschweigend umzuschreiben.

## Aliase

Ein Alias ist ein alter oder herstellereigener Name, der auf eine kanonische Metrik
zeigt. Er darf **gelesen**, aber nicht **geschrieben** werden. Das ist der Weg, auf dem
eine CSV-Spalte namens `carbs` in `nutrition_carbohydrates` landet, statt eine eigene
Metrik zu gründen.

`calendar_busy_hours` ist bewusst **kein** Alias von `calendar_busy_duration`: Der Name
trug dieselbe Größe in einer anderen Einheit, und eine Abbildung würde 8 Stunden und
8 Minuten in dieselbe Serie legen. Die Metrik ist ersatzlos entfallen.

## Dynamische Namensräume

Manche Quellen haben keinen festen Metriksatz. Welche Entitäten eine Home-Assistant-
Installation exportiert, entscheidet die Einrichtung des Nutzers, nicht der Hersteller.
Für diese Fälle gibt es registrierte Präfixe: Namen darunter sind erlaubt, ohne
katalogisiert zu sein, und tragen ihre Einheit in `metadata.unit` statt in der Registry.

Das ist keine Hintertür für Importer, die ihre Metriken katalogisieren könnten — es ist
die ehrliche Antwort, wenn die Einheit erst zur Laufzeit bekannt ist.

## Eine Metrik hinzufügen

1. Eintrag in `packages/shared-schemas/src/shared_schemas/metrics.py` ergänzen — Name,
   Einheit, Aggregation, Kategorie, Labels, Quellen, plausibler Wertebereich.
2. `task metrics:generate` ausführen. Das schreibt den TypeScript-Katalog des Dashboards
   und die Tabelle unten neu.
3. `task test:packages` ausführen. Die Tests prüfen unter anderem, dass kein Name seine
   Einheit als Suffix trägt und dass kein Importer einen unregistrierten Namen schreibt.
4. Die Seite des betroffenen Importers unter `docs/importers/` ergänzen.

Wird eine Metrik **umbenannt**, gehört der alte Name als Alias in denselben Eintrag —
sonst sind die bereits gespeicherten Zeilen aus der Anwendung heraus nicht mehr
erreichbar.

## Der Katalog

Erzeugt aus der Registry; Änderungen hier werden beim nächsten `task metrics:generate`
überschrieben.

<!-- BEGIN GENERATED METRIC TABLE -->

### Aktivität

| `metric_type` | Bedeutung | Einheit | Aggregation | Quellen | Alte Namen |
| --- | --- | --- | --- | --- | --- |
| `steps` | Schritte | `count` | Summe | apple_health | `step_count`, `steps_count` |
| `distance` | Zurückgelegte Distanz | `km` | Summe | apple_health | `distance_walking_running`, `walking_running_distance` |
| `energy_active` | Aktive Energie | `kcal` | Summe | apple_health | `active_energy`, `active_energy_burned` |
| `energy_resting` | Grundumsatz | `kcal` | Summe | apple_health | `resting_energy`, `basal_energy_burned` |
| `energy_total` | Gesamtumsatz | `kcal` | Summe | whoop | `cycle_kilojoule` |
| `exercise_duration` | Bewegungsminuten | `min` | Summe | apple_health | `apple_exercise_time` |
| `stand_duration` | Stehminuten | `min` | Summe | apple_health | `apple_stand_time` |
| `whoop_strain` | Whoop Strain (Tag) | `index` | Maximum | whoop | `strain` |
| `oura_activity_score` | Oura Activity Score | `index` | Mittelwert | oura | `activity_score` |

### Herz & Kreislauf

| `metric_type` | Bedeutung | Einheit | Aggregation | Quellen | Alte Namen |
| --- | --- | --- | --- | --- | --- |
| `heart_rate` | Puls | `bpm` | Mittelwert | apple_health | — |
| `heart_rate_average` | Durchschnittspuls (Tag) | `bpm` | Mittelwert | whoop | `cycle_average_heart_rate` |
| `heart_rate_resting` | Ruhepuls | `bpm` | Mittelwert | apple_health, whoop | `resting_heart_rate`, `resting_hr`, `resting_heart_rate_bpm` |
| `heart_rate_walking_average` | Gehpuls (Durchschnitt) | `bpm` | Mittelwert | apple_health | `walking_heart_rate_average` |
| `hrv_rmssd` | HRV (RMSSD) | `ms` | Mittelwert | whoop | `hrv_rmssd_milli` |
| `hrv_sdnn` | HRV (SDNN) | `ms` | Mittelwert | apple_health | `heart_rate_variability_sdnn`, `hrv` |
| `blood_oxygen` | Sauerstoffsättigung | `%` | Mittelwert | apple_health, whoop | `spo2_percentage`, `spo2`, `oxygen_saturation` |
| `respiratory_rate` | Atemfrequenz | `br/min` | Mittelwert | apple_health, whoop | — |

### Schlaf

| `metric_type` | Bedeutung | Einheit | Aggregation | Quellen | Alte Namen |
| --- | --- | --- | --- | --- | --- |
| `sleep_duration` | Schlafdauer | `min` | Summe | apple_health | `sleep_analysis`, `sleep`, `sleep_duration_hours`, `sleep_asleep_duration` |
| `sleep_duration_deep` | Tiefschlaf | `min` | Summe | apple_health | `sleep_deep_duration` |
| `sleep_duration_rem` | REM-Schlaf | `min` | Summe | apple_health | `sleep_rem_duration` |
| `sleep_duration_light` | Leichtschlaf | `min` | Summe | apple_health | `sleep_core_duration`, `sleep_light_duration` |
| `sleep_duration_awake` | Wachzeit | `min` | Summe | apple_health | `sleep_awake_duration` |
| `sleep_duration_in_bed` | Zeit im Bett | `min` | Summe | apple_health | `sleep_inbed_duration`, `sleep_in_bed_duration` |
| `sleep_efficiency` | Schlafeffizienz | `%` | Mittelwert | whoop | `sleep_efficiency_percentage` |
| `whoop_sleep_performance` | Whoop Sleep Performance | `%` | Mittelwert | whoop | `sleep_performance_percentage`, `whoop_sleep_performance_percent` |
| `whoop_recovery_score` | Whoop Recovery | `%` | Mittelwert | whoop | `recovery_score` |
| `oura_sleep_score` | Oura Sleep Score | `index` | Mittelwert | oura | `sleep_score` |
| `oura_readiness_score` | Oura Readiness Score | `index` | Mittelwert | oura | `readiness_score` |

### Körper

| `metric_type` | Bedeutung | Einheit | Aggregation | Quellen | Alte Namen |
| --- | --- | --- | --- | --- | --- |
| `body_weight` | Körpergewicht | `kg` | letzter Wert | apple_health | `body_mass`, `weight` |
| `body_fat` | Körperfettanteil | `%` | letzter Wert | apple_health | `body_fat_percentage` |
| `vo2_max` | VO2max | `mL/kg/min` | letzter Wert | apple_health | — |
| `skin_temperature` | Hauttemperatur | `°C` | Mittelwert | whoop | `skin_temp_celsius` |

### Ernährung

| `metric_type` | Bedeutung | Einheit | Aggregation | Quellen | Alte Namen |
| --- | --- | --- | --- | --- | --- |
| `nutrition_energy` | Kalorien | `kcal` | Summe | yazio, apple_health | `calories`, `yazio_calories`, `calories_consumed`, `dietary_energy_consumed`, `nutrition_calories_kcal` |
| `nutrition_protein` | Protein | `g` | Summe | yazio | `protein`, `yazio_protein`, `nutrition_protein_g` |
| `nutrition_carbohydrates` | Kohlenhydrate | `g` | Summe | yazio | `carbohydrates`, `carbs`, `yazio_carbs`, `nutrition_carbs_g` |
| `nutrition_fat` | Fett | `g` | Summe | yazio | `fat`, `yazio_fat`, `nutrition_fat_g` |
| `nutrition_fiber` | Ballaststoffe | `g` | Summe | yazio | `fiber`, `yazio_fiber`, `nutrition_fiber_g` |
| `nutrition_meal_energy` | Kalorien je Mahlzeit | `kcal` | Summe | yazio | — |
| `nutrition_item_energy` | Kalorien je Eintrag | `kcal` | Summe | yazio | `consumed_item_calories` |
| `nutrition_item_amount` | Menge je Eintrag | `g` | Summe | yazio | `consumed_product` |
| `nutrition_recipe_portions` | Rezeptportionen | `count` | Summe | yazio | `consumed_recipe_portion` |

### Training (Ausdauer)

| `metric_type` | Bedeutung | Einheit | Aggregation | Quellen | Alte Namen |
| --- | --- | --- | --- | --- | --- |
| `workout_duration` | Trainingsdauer | `min` | Summe | apple_health | `whoop_workout_duration_minutes` |
| `workout_distance` | Trainingsdistanz | `km` | Summe | apple_health, whoop | `workout_distance_meter` |
| `workout_energy` | Trainingsenergie | `kcal` | Summe | apple_health, whoop | `workout_active_energy`, `workout_kilojoule` |
| `workout_heart_rate_average` | Trainingspuls (Durchschnitt) | `bpm` | Mittelwert | apple_health, whoop | `workout_avg_heart_rate`, `workout_average_heart_rate` |
| `workout_heart_rate_max` | Trainingspuls (Maximum) | `bpm` | Maximum | apple_health | `workout_max_heart_rate` |
| `whoop_workout_strain` | Whoop Strain (Training) | `index` | Maximum | whoop | `workout_strain` |

### Krafttraining

| `metric_type` | Bedeutung | Einheit | Aggregation | Quellen | Alte Namen |
| --- | --- | --- | --- | --- | --- |
| `strength_set_weight` | Satzgewicht | `kg` | Maximum | streak | `workout_set_weight_kg` |
| `strength_set_reps` | Wiederholungen | `count` | Summe | streak | `workout_set_reps` |
| `strength_set_volume` | Satzvolumen | `kg` | Summe | streak | `workout_set_volume` |
| `strength_set_heart_rate_max` | Maximalpuls im Satz | `bpm` | Maximum | streak | `workout_set_heart_rate_max` |
| `strength_session_volume` | Trainingsvolumen | `kg` | Summe | streak | `workout_total_volume` |
| `strength_session_sets` | Sätze | `count` | Summe | streak | `workout_total_sets` |

### Standort

| `metric_type` | Bedeutung | Einheit | Aggregation | Quellen | Alte Namen |
| --- | --- | --- | --- | --- | --- |
| `location_point` | Standortpunkte | `count` | Summe | dawarich | — |
| `location_latitude` | Breitengrad | `°` | letzter Wert | dawarich | — |
| `location_longitude` | Längengrad | `°` | letzter Wert | dawarich | — |

### Kalender

| `metric_type` | Bedeutung | Einheit | Aggregation | Quellen | Alte Namen |
| --- | --- | --- | --- | --- | --- |
| `calendar_event_count` | Termine | `count` | Summe | calendar | — |
| `calendar_busy_duration` | Belegte Zeit | `min` | Summe | calendar | `calendar_busy_minutes` |
| `calendar_meeting_duration` | Termindauer | `min` | Summe | calendar | `calendar_meeting_duration_minutes` |

### Umwelt

| `metric_type` | Bedeutung | Einheit | Aggregation | Quellen | Alte Namen |
| --- | --- | --- | --- | --- | --- |
| `weather_temperature` | Außentemperatur | `°C` | Mittelwert | weather | `weather_temperature_c` |
| `weather_temperature_apparent` | Gefühlte Temperatur | `°C` | Mittelwert | weather | `weather_apparent_temperature_c` |
| `weather_humidity` | Luftfeuchtigkeit | `%` | Mittelwert | weather | `weather_humidity_pct` |
| `weather_precipitation` | Niederschlag | `mm` | Summe | weather | `weather_precipitation_mm` |
| `weather_pressure` | Luftdruck | `hPa` | Mittelwert | weather | `weather_pressure_hpa` |
| `weather_wind_speed` | Windgeschwindigkeit | `km/h` | Mittelwert | weather | `weather_wind_speed_kmh` |
| `weather_cloud_cover` | Bewölkung | `%` | Mittelwert | weather | `weather_cloud_cover_pct` |
| `weather_uv_index` | UV-Index | `index` | Maximum | weather | — |

### Dynamische Namensräume

| Präfix | Bedeutung | Quellen |
| --- | --- | --- |
| `home_assistant_` | Home Assistant | home_assistant |
| `apple_health_` | Apple Health (nicht katalogisiert) | apple_health |
| `custom_` | Eigene Metrik | manueller Import |

<!-- END GENERATED METRIC TABLE -->
