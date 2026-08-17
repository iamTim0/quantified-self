# Metrics

Every quantity the platform stores is defined exactly once — in the registry at
`packages/shared-schemas/src/shared_schemas/metrics.py`. This page explains why it exists, which
rules it enforces, and which metrics there are.

## Why a central definition

`metric_type` used to be a free string. Every importer invented its own names, and nothing could
contradict it:

- Apple Health wrote `workout_avg_heart_rate`, WHOOP `workout_average_heart_rate` — the same
  quantity, two series that never met.
- WHOOP reported burned energy in **kilojoules**, Apple Health in **kilocalories**, under names that
  concealed both. So the conflict detection in `services/core/src/core/analytics.py` compared 8400
  with 2000 and reported a contradiction.
- The calendar importer wrote `calendar_busy_minutes` **and** `calendar_busy_hours` — the same
  number twice, purely because the unit was part of the name. The correlation analysis duly reported
  the two as perfectly correlated.
- The dashboard looked for `steps`, `sleep_score`, `readiness_score`, `hrv_balance`, `resting_hr` and
  `carbs`. No importer ever produced any of those names; half the tiles were permanently empty.

The registry makes these states impossible instead of documenting them.

## The two rules

**1. One quantity, one name.** The name says *what* was measured — never *who* measured it, and never
*in which unit*. Two sources reporting the same physical quantity write the same `metric_type`.

There is one deliberate exception: a vendor's own figures keep their prefix (`whoop_strain`,
`whoop_recovery_score`, `oura_sleep_score`). A Whoop strain is comparable with nothing outside Whoop,
and a name without the prefix would suggest exactly that it is.

**2. One name, one unit.** The unit lives in the registry, not in the name. The importers convert
while transforming — WHOOP's kilojoules become kilocalories, Apple Health's miles become kilometres,
hours become minutes. The raw value is kept in `metadata.provider_value` along with `metadata.units`:
a conversion is an intervention in somebody else's data, and "why does this differ from what my
health app shows" has to stay answerable.

That is why no canonical name carries a unit suffix. A test in
`packages/shared-schemas/tests/test_metrics.py` keeps it that way.

## Where the registry takes effect

| Place | Behaviour |
| --- | --- |
| The importers' transformers | call `canonical_metric_type()` **before** the `idempotency_key` is derived |
| `shared_schemas.IngestEvent` | rejects anything that is not canonical — aliases included |
| Core's NATS consumer | validates every event; unknown names are held in tenant-scoped quarantine until a mapping decision |
| Core's batch/CSV import | maps aliases onto the canonical name, otherwise HTTP 422 |
| `GET /api/v1/data/metrics/catalog` | serves the complete registry |
| Dashboard | uses `apps/dashboard/src/app/lib/metrics/catalog.ts`, generated from the same source |

The `idempotency_key` is `SHA256(tenant_id + source_id + metric_type + timestamp)` (AGENTS.md rule 4).
That is why the order in the first row is not a matter of style: derive the key first and normalize
the name afterwards, and you store a data point under a name its key does not describe — and import
the same reading a second time on the next run. It is exactly why `IngestEvent` rejects aliases
instead of quietly rewriting them.

## Aliases

An alias is a former or vendor-specific name that points at a canonical metric. It may be **read**
but not **written**. That is how a CSV column called `carbs` ends up in `nutrition_carbohydrates`
instead of founding a metric of its own.

`calendar_busy_hours` is deliberately **not** an alias of `calendar_busy_duration`: the name carried
the same quantity in a different unit, and a mapping would put 8 hours and 8 minutes into the same
series. The metric was dropped with nothing in its place.

## Dynamic namespaces

Some sources have no fixed set of metrics. Which entities a Home Assistant installation exports is
decided by the user's own setup, not by a vendor. For those cases there are registered prefixes:
names below them are legal without being catalogued, and they carry their unit in `metadata.unit`
rather than in the registry.

This is not a back door for importers that could catalogue their metrics — it is the honest answer
when the unit is only known at run time.

## Adding a metric

1. Add the entry to `packages/shared-schemas/src/shared_schemas/metrics.py` — name, unit,
   aggregation, category, labels, sources, plausible value range.
2. Run `task metrics:generate`. That rewrites the dashboard's TypeScript catalog and the table below.
3. Run `task test:packages`. Among other things, the tests check that no name carries its unit as a
   suffix and that no importer writes an unregistered name.
4. Extend the page of the importer concerned under `docs/importers/`.

When a metric is **renamed**, the former name belongs in the same entry as an alias — otherwise the
rows already stored can no longer be reached from the application.

## The catalog

Generated from the registry; changes made here are overwritten by the next `task metrics:generate`.

Each metric carries a label in both interface languages. The table below shows the English one; the
dashboard picks whichever matches the reader's language.

<!-- BEGIN GENERATED METRIC TABLE -->

### Activity

| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |
| --- | --- | --- | --- | --- | --- |
| `steps` | Steps | `count` | `sum` | apple_health | `step_count`, `steps_count` |
| `distance` | Distance travelled | `km` | `sum` | apple_health | `distance_walking_running`, `walking_running_distance`, `distance_cycling`, `distance_swimming`, `distance_downhill_snow_sports` |
| `energy_active` | Active energy | `kcal` | `sum` | apple_health | `active_energy`, `active_energy_burned` |
| `energy_resting` | Resting energy | `kcal` | `sum` | apple_health | `resting_energy`, `basal_energy_burned` |
| `energy_total` | Total energy burned | `kcal` | `sum` | whoop | `cycle_kilojoule` |
| `exercise_duration` | Exercise time | `min` | `sum` | apple_health | `apple_exercise_time` |
| `stand_duration` | Stand time | `min` | `sum` | apple_health | `apple_stand_time` |
| `flights_climbed` | Flights climbed | `count` | `sum` | apple_health | — |
| `physical_effort` | Physical effort | `MET` | `average` | apple_health | `physical_effort_mets` |
| `standing_events` | Stand hours | `count` | `sum` | apple_health | `apple_stand_hour`, `stand_hours` |
| `daylight_duration` | Time in daylight | `min` | `sum` | apple_health | `time_in_daylight` |
| `running_power` | Running power | `W` | `average` | apple_health | `running_power_watts` |
| `running_speed` | Running speed | `km/h` | `average` | apple_health | `running_speed_kmh` |
| `running_stride_length` | Running stride length | `m` | `average` | apple_health | — |
| `running_vertical_oscillation` | Running vertical oscillation | `mm` | `average` | apple_health | `running_vertical_oscillation_mm` |
| `running_ground_contact_time` | Running ground contact time | `ms` | `average` | apple_health | `running_ground_contact_time_ms` |
| `walking_step_length` | Walking step length | `m` | `average` | apple_health | `walking_step_length_m` |
| `walking_speed` | Walking speed | `km/h` | `average` | apple_health | `walking_speed_kmh` |
| `walking_double_support` | Walking double support | `%` | `average` | apple_health | `walking_double_support_percentage` |
| `walking_asymmetry` | Walking asymmetry | `%` | `average` | apple_health | `walking_asymmetry_percentage` |
| `walking_steadiness` | Walking steadiness | `%` | `last` | apple_health | `apple_walking_steadiness` |
| `stair_ascent_speed` | Stair ascent speed | `km/h` | `average` | apple_health | `stair_ascent_speed_kmh` |
| `stair_descent_speed` | Stair descent speed | `km/h` | `average` | apple_health | `stair_descent_speed_kmh` |
| `six_minute_walk_distance` | Six-minute walk distance | `m` | `last` | apple_health | `six_minute_walk_test_distance` |
| `swimming_strokes` | Swimming strokes | `count` | `sum` | apple_health | `swimming_stroke_count` |
| `handwashing_events` | Handwashing events | `count` | `sum` | apple_health | `handwashing_event` |
| `mindful_session_duration` | Mindful session duration | `min` | `sum` | apple_health | `mindful_session` |
| `toothbrushing_events` | Toothbrushing events | `count` | `sum` | apple_health | `toothbrushing_event` |
| `whoop_strain` | Whoop strain (day) | `index` | `max` | whoop | `strain` |
| `oura_activity_score` | Oura activity score | `index` | `average` | oura | `activity_score` |

### Environment

| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |
| --- | --- | --- | --- | --- | --- |
| `audio_exposure_events` | Audio exposure events | `count` | `sum` | apple_health | `audio_exposure_event`, `headphone_audio_exposure_event` |
| `audio_exposure_environmental` | Environmental audio exposure | `dB` | `average` | apple_health | `environmental_audio_exposure` |
| `audio_exposure_headphone` | Headphone audio exposure | `dB` | `average` | apple_health | `headphone_audio_exposure` |
| `audio_exposure_reduction` | Environmental sound reduction | `dB` | `average` | apple_health | `environmental_sound_reduction` |
| `weather_temperature` | Outdoor temperature | `°C` | `average` | weather | `weather_temperature_c` |
| `weather_temperature_apparent` | Apparent temperature | `°C` | `average` | weather | `weather_apparent_temperature_c` |
| `weather_humidity` | Humidity | `%` | `average` | weather | `weather_humidity_pct` |
| `weather_precipitation` | Precipitation | `mm` | `sum` | weather | `weather_precipitation_mm` |
| `weather_pressure` | Air pressure | `hPa` | `average` | weather | `weather_pressure_hpa` |
| `weather_wind_speed` | Wind speed | `km/h` | `average` | weather | `weather_wind_speed_kmh` |
| `weather_cloud_cover` | Cloud cover | `%` | `average` | weather | `weather_cloud_cover_pct` |
| `weather_uv_index` | UV index | `index` | `max` | weather | — |

### Heart and circulation

| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |
| --- | --- | --- | --- | --- | --- |
| `blood_pressure_systolic` | Blood pressure, systolic | `mmHg` | `average` | apple_health | `systolic` |
| `blood_pressure_diastolic` | Blood pressure, diastolic | `mmHg` | `average` | apple_health | `diastolic` |
| `heart_rate` | Heart rate | `bpm` | `average` | apple_health | — |
| `heart_rate_average` | Average heart rate (day) | `bpm` | `average` | whoop | `cycle_average_heart_rate` |
| `heart_rate_max` | Maximum heart rate (day) | `bpm` | `max` | whoop | `max_heart_rate` |
| `heart_rate_resting` | Resting heart rate | `bpm` | `average` | apple_health, whoop | `resting_heart_rate`, `resting_hr`, `resting_heart_rate_bpm` |
| `heart_rate_walking_average` | Walking heart rate average | `bpm` | `average` | apple_health | `walking_heart_rate_average` |
| `heart_rate_recovery` | Heart-rate recovery | `bpm` | `average` | apple_health | `heart_rate_recovery_one_minute` |
| `hrv_rmssd` | HRV (RMSSD) | `ms` | `average` | whoop | `hrv_rmssd_milli` |
| `hrv_sdnn` | HRV (SDNN) | `ms` | `average` | apple_health | `heart_rate_variability_sdnn`, `hrv` |
| `blood_oxygen` | Blood oxygen | `%` | `average` | apple_health, whoop | `spo2_percentage`, `spo2`, `oxygen_saturation` |
| `respiratory_rate` | Respiratory rate | `br/min` | `average` | apple_health, whoop | — |

### Sleep

| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |
| --- | --- | --- | --- | --- | --- |
| `sleep_duration` | Sleep duration | `min` | `sum` | apple_health, whoop | `sleep_analysis`, `sleep`, `sleep_duration_hours`, `sleep_asleep_duration` |
| `sleep_duration_deep` | Deep sleep | `min` | `sum` | apple_health, whoop | `sleep_deep_duration` |
| `sleep_duration_rem` | REM sleep | `min` | `sum` | apple_health, whoop | `sleep_rem_duration` |
| `sleep_duration_light` | Light sleep | `min` | `sum` | apple_health, whoop | `sleep_core_duration`, `sleep_light_duration` |
| `sleep_duration_awake` | Awake time | `min` | `sum` | apple_health, whoop | `sleep_awake_duration` |
| `sleep_duration_in_bed` | Time in bed | `min` | `sum` | apple_health, whoop | `sleep_inbed_duration`, `sleep_in_bed_duration` |
| `sleep_efficiency` | Sleep efficiency | `%` | `average` | whoop | `sleep_efficiency_percentage` |
| `whoop_sleep_need` | WHOOP sleep need | `min` | `average` | whoop | `sleep_need_minutes` |
| `whoop_sleep_debt` | WHOOP sleep debt | `min` | `average` | whoop | `sleep_debt_minutes` |
| `whoop_sleep_consistency` | WHOOP sleep consistency | `%` | `average` | whoop | `sleep_consistency_percentage` |
| `sleep_nap_count` | Naps | `count` | `sum` | whoop | `naps` |
| `whoop_sleep_performance` | Whoop sleep performance | `%` | `average` | whoop | `sleep_performance_percentage`, `whoop_sleep_performance_percent` |
| `whoop_recovery_score` | Whoop recovery | `%` | `average` | whoop | `recovery_score` |
| `oura_sleep_score` | Oura sleep score | `index` | `average` | oura | `sleep_score` |
| `oura_readiness_score` | Oura readiness score | `index` | `average` | oura | `readiness_score` |

### Body

| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |
| --- | --- | --- | --- | --- | --- |
| `body_weight` | Body weight | `kg` | `last` | apple_health | `body_mass`, `weight` |
| `body_fat` | Body fat | `%` | `last` | apple_health | `body_fat_percentage` |
| `body_height` | Body height | `m` | `last` | apple_health | `height` |
| `body_mass_index` | Body mass index | `index` | `last` | apple_health | `bmi` |
| `lean_body_mass` | Lean body mass | `kg` | `last` | apple_health | `lean_body_mass_kg` |
| `vo2_max` | VO2 max | `mL/kg/min` | `last` | apple_health | — |
| `skin_temperature` | Skin temperature | `°C` | `average` | whoop | `skin_temp_celsius` |

### Nutrition

| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |
| --- | --- | --- | --- | --- | --- |
| `nutrition_energy` | Calories | `kcal` | `sum` | yazio, apple_health | `calories`, `yazio_calories`, `calories_consumed`, `dietary_energy_consumed`, `nutrition_calories_kcal` |
| `nutrition_protein` | Protein | `g` | `sum` | yazio, apple_health | `protein`, `yazio_protein`, `nutrition_protein_g`, `dietary_protein` |
| `nutrition_carbohydrates` | Carbohydrates | `g` | `sum` | yazio, apple_health | `carbohydrates`, `carbs`, `yazio_carbs`, `nutrition_carbs_g`, `dietary_carbohydrates` |
| `nutrition_fat` | Fat | `g` | `sum` | yazio, apple_health | `fat`, `yazio_fat`, `nutrition_fat_g`, `dietary_fat_total` |
| `nutrition_fiber` | Fibre | `g` | `sum` | yazio, apple_health | `fiber`, `yazio_fiber`, `nutrition_fiber_g`, `dietary_fiber` |
| `nutrition_sugar` | Sugar | `g` | `sum` | apple_health | `dietary_sugar` |
| `nutrition_sodium` | Sodium | `mg` | `sum` | apple_health | `dietary_sodium` |
| `nutrition_fat_saturated` | Saturated fat | `g` | `sum` | apple_health | `dietary_fat_saturated` |
| `nutrition_fat_monounsaturated` | Monounsaturated fat | `g` | `sum` | apple_health | `dietary_fat_monounsaturated` |
| `nutrition_fat_polyunsaturated` | Polyunsaturated fat | `g` | `sum` | apple_health | `dietary_fat_polyunsaturated` |
| `nutrition_potassium` | Potassium | `mg` | `sum` | apple_health | `dietary_potassium` |
| `nutrition_cholesterol` | Cholesterol | `mg` | `sum` | apple_health | `dietary_cholesterol` |
| `nutrition_calcium` | Calcium | `mg` | `sum` | apple_health | `dietary_calcium` |
| `nutrition_vitamin_c_intake` | Vitamin C | `mg` | `sum` | apple_health | `dietary_vitamin_c` |
| `nutrition_iron` | Iron | `mg` | `sum` | apple_health | `dietary_iron` |
| `nutrition_caffeine` | Caffeine | `mg` | `sum` | apple_health | `dietary_caffeine` |
| `water_intake` | Water intake | `mL` | `sum` | apple_health | `dietary_water`, `water_consumed` |
| `nutrition_meal_energy` | Calories per meal | `kcal` | `sum` | yazio | — |
| `nutrition_item_energy` | Calories per item | `kcal` | `sum` | yazio | `consumed_item_calories` |
| `nutrition_item_amount` | Amount per item | `g` | `sum` | yazio | `consumed_product` |
| `nutrition_recipe_portions` | Recipe portions | `count` | `sum` | yazio | `consumed_recipe_portion` |

### Training (endurance)

| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |
| --- | --- | --- | --- | --- | --- |
| `workout_duration` | Workout duration | `min` | `sum` | apple_health, whoop | `whoop_workout_duration_minutes` |
| `workout_distance` | Workout distance | `km` | `sum` | apple_health, whoop | `workout_distance_meter` |
| `workout_energy` | Workout energy | `kcal` | `sum` | apple_health, whoop | `workout_active_energy`, `workout_kilojoule` |
| `workout_energy_resting` | Workout resting energy | `kcal` | `sum` | apple_health | `workout_basal_energy_burned` |
| `workout_heart_rate_average` | Workout heart rate (average) | `bpm` | `average` | apple_health, whoop | `workout_avg_heart_rate`, `workout_average_heart_rate` |
| `workout_heart_rate` | Workout heart rate (series) | `bpm` | `average` | apple_health | — |
| `workout_heart_rate_max` | Workout heart rate (max) | `bpm` | `max` | apple_health, whoop | `workout_max_heart_rate` |
| `workout_heart_rate_zone_1` | Workout heart-rate zone 1 | `%` | `average` | whoop | `heart_rate_zone_1` |
| `workout_heart_rate_zone_2` | Workout heart-rate zone 2 | `%` | `average` | whoop | `heart_rate_zone_2` |
| `workout_heart_rate_zone_3` | Workout heart-rate zone 3 | `%` | `average` | whoop | `heart_rate_zone_3` |
| `workout_heart_rate_zone_4` | Workout heart-rate zone 4 | `%` | `average` | whoop | `heart_rate_zone_4` |
| `workout_heart_rate_zone_5` | Workout heart-rate zone 5 | `%` | `average` | whoop | `heart_rate_zone_5` |
| `workout_steps` | Steps (workout) | `count` | `sum` | apple_health | — |
| `workout_speed_average` | Speed (average) | `km/h` | `average` | apple_health | — |
| `workout_speed_max` | Speed (max) | `km/h` | `max` | apple_health | — |
| `workout_cadence` | Cadence | `spm` | `average` | apple_health | — |
| `workout_cycling_cadence` | Cycling cadence | `rpm` | `average` | apple_health | — |
| `workout_cycling_power` | Cycling power | `W` | `average` | apple_health | — |
| `workout_elevation_gain` | Elevation gain | `m` | `sum` | apple_health, whoop | — |
| `workout_elevation_loss` | Elevation loss | `m` | `sum` | apple_health | — |
| `workout_lap_length` | Lap length | `m` | `last` | apple_health | — |
| `workout_swim_cadence` | Swim cadence | `spm` | `average` | apple_health | — |
| `workout_swimming_strokes` | Swimming strokes | `count` | `sum` | apple_health | — |
| `workout_intensity` | Intensity | `MET` | `average` | apple_health | — |
| `whoop_workout_strain` | Whoop strain (workout) | `index` | `max` | whoop | `workout_strain` |

### Strength training

| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |
| --- | --- | --- | --- | --- | --- |
| `strength_set_weight` | Set weight | `kg` | `max` | streak | `workout_set_weight_kg` |
| `strength_set_reps` | Repetitions | `count` | `sum` | streak | `workout_set_reps` |
| `strength_set_volume` | Set volume | `kg` | `sum` | streak | `workout_set_volume` |
| `strength_set_heart_rate_max` | Set peak heart rate | `bpm` | `max` | streak | `workout_set_heart_rate_max` |
| `strength_session_volume` | Session volume | `kg` | `sum` | streak | `workout_total_volume` |
| `strength_session_sets` | Sets | `count` | `sum` | streak | `workout_total_sets` |

### Location

| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |
| --- | --- | --- | --- | --- | --- |
| `location_point` | Location points | `count` | `sum` | dawarich, apple_health | — |
| `location_latitude` | Latitude | `°` | `last` | dawarich | — |
| `location_longitude` | Longitude | `°` | `last` | dawarich | — |

### Calendar

| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |
| --- | --- | --- | --- | --- | --- |
| `calendar_event_count` | Calendar events | `count` | `sum` | calendar | — |
| `calendar_busy_duration` | Busy time | `min` | `sum` | calendar | `calendar_busy_minutes` |
| `calendar_meeting_duration` | Meeting duration | `min` | `sum` | calendar | `calendar_meeting_duration_minutes` |

### developer

| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |
| --- | --- | --- | --- | --- | --- |
| `code_commits` | Commits | `count` | `sum` | github | — |
| `code_lines_added` | Lines added | `count` | `sum` | github | — |
| `code_lines_removed` | Lines removed | `count` | `sum` | github | — |
| `code_repositories_touched` | Repositories touched | `count` | `max` | github | — |
| `code_pull_requests_opened` | Pull requests opened | `count` | `sum` | github | — |
| `code_pull_requests_merged` | Pull requests merged | `count` | `sum` | github | — |
| `code_reviews_submitted` | Reviews submitted | `count` | `sum` | github | — |
| `code_issues_opened` | Issues opened | `count` | `sum` | github | — |
| `code_contribution_streak` | Current streak | `count` | `last` | github | — |
| `code_followers` | Followers | `count` | `last` | github | — |
| `code_stars_received` | Stars received | `count` | `last` | github | — |

### Dynamic namespaces

| Prefix | Meaning | Sources |
| --- | --- | --- |
| `home_assistant_` | Home Assistant | home_assistant |
| `apple_health_` | Apple Health (uncatalogued) | apple_health |
| `github_` | GitHub (per repository) | github |
| `custom_` | Custom metric | manual import |

<!-- END GENERATED METRIC TABLE -->

## Cadence

Every metric records how often a reading is expected, which is what makes "is data missing?"
answerable:

- `daily` — one value per day is the expectation. A day without one is a gap.
- `continuous` — sampled far more often than daily, at a rate the device chooses. Judged
  against the cadence actually observed rather than against calendar days.
- `event` — happens when it happens. Absence carries no information, so no gap is ever
  reported.

`event` is the default. A metric nobody has classified therefore reports no gaps rather than a
year of imaginary ones — the conservative answer, and the one that cannot invent a problem.

See [Data quality](features/data-quality.md) for what each setting changes.
