# Apple Health importer

The Apple Health importer brings health and activity data from Apple Health into the
Quantified Self platform. The raw data is translated into one uniform metric format and handed
to the Core service, kept separate per tenant.

## Prerequisites

- Apple Health is set up on the iPhone.
- **Health Auto Export**, or a compatible JSON/webhook source, is configured for the export.
- The data source is configured in the dashboard for the right workspace (tenant).
- The importer is running and can reach the Core service.

The importer produces no demo or stand-in data. Without a valid configuration it stays idle.

## Setup

### 1. Prepare the Apple Health export

1. On the iPhone, open the export app or the integration you set up for Apple Health.
2. Grant read permission only for the health categories you want to import.
3. Enable the integration's JSON export or its webhook.
4. Take the connection details the integration needs over into the connector configuration.

The exact menu names and the health categories on offer depend on the export app and its
version.

### 2. Configure the connector in the dashboard

1. Open **Connectors** in the dashboard.
2. Choose **Apple Health**.
3. Enter the export configuration, or the source's credentials.
4. Save the configuration.
5. Then start **Sync now**, if that action is offered. Otherwise the data arrives the next time
   the export app sends it — Apple Health is a push source, so nothing on this side polls for it.

The credentials are stored encrypted by the Core service. The importer reads them from Core at
run time; they belong in neither an `.env` file nor a NATS event.

## Two ways in

| Way | What it needs | What it brings |
| --- | --- | --- |
| **Health Auto Export** (push) | The app on the phone and an API key from the dashboard | Whatever you enable in the app, as it happens |
| **`export.zip`** (upload) | Nothing but the Health app | The whole history, workouts and GPS routes included |

The second is described in [Uploading an export file](../features/file-import.md), including
which parts of an archive are deliberately not stored. Both write into the same connector and the
same metrics, so a reading that arrives twice is stored once.

## Data flow

```text
Apple Health / export app -> Apple Health importer
  -> NATS: qs.ingest.apple_health -> Core service -> data_points

export.zip -> Gateway -> Apple Health importer (reads it in the background)
  -> NATS: qs.ingest.apple_health -> Core service -> data_points
```

The importer does not write to the database. The Core service is the database's only owner and
deduplicates on the `idempotency_key`. Every import stays attached to the configured
`tenant_id`.

## Resolution and completeness

Before publishing, the importer asks Core for the tenant's effective metric policies. Continuous
Apple Health samples are aggregated into minute buckets by default; provider-stated daily totals
remain authoritative for day rollups. A derived bucket carries its operation and sample count in
metadata, so the reduction is auditable without retaining the complete provider payload.

Policies apply to future imports only. Change them under the Explorer's **Import resolution**
control or through Core's ingest-policy API, then upload a deliberate archive again if historical
data needs to be rebuilt. The import run shows how many points were published and which provider
window was covered; the Data Quality Center names fields that arrived but are not stored. A
successful upload therefore means "the accepted export was processed", not "Apple Health supplied
every possible category or date".

## Imported metrics

| `metric_type` | Meaning | Unit |
| --- | --- | --- |
| `steps` | number of steps | `count` |
| `distance` | distance travelled | `km` |
| `energy_active` | active energy | `kcal` |
| `energy_resting` | resting energy | `kcal` |
| `heart_rate` | heart rate | `bpm` |
| `heart_rate_resting` | resting heart rate | `bpm` |
| `hrv_sdnn` | heart-rate variability (SDNN) | `ms` |
| `blood_oxygen` | blood oxygen | `%` |
| `sleep_duration` | sleep duration | `min` |
| `sleep_duration_deep` / `_rem` / `_light` / `_awake` / `_in_bed` | sleep stages | `min` |
| `body_weight` | body weight | `kg` |
| `workout_duration`, `workout_distance`, `workout_energy`, `workout_heart_rate_average`, `workout_heart_rate_max` | workout sessions | `min`, `km`, `kcal`, `bpm` |
| `workout_speed_average`, `workout_speed_max`, `workout_cadence`, `workout_cycling_cadence`, `workout_cycling_power` | workout speed, cadence and cycling power | `km/h`, `spm`, `rpm`, `W` |
| `workout_elevation_gain`, `workout_elevation_loss`, `workout_lap_length` | ascent, descent and swimming lap length | `m` |
| `workout_swim_cadence`, `workout_swimming_strokes`, `workout_steps`, `workout_intensity` | swimming cadence, stroke count, workout steps and intensity | `spm`, `count`, `MET` |
| `blood_pressure_systolic`, `blood_pressure_diastolic` | blood pressure | `mmHg` |
| `location_point` | one point per GPS fix in a workout route | — |
| `physical_effort`, `running_power`, `running_speed`, `running_stride_length`, `running_vertical_oscillation`, `running_ground_contact_time` | physical effort and running dynamics | `MET`, `W`, `km/h`, `m`, `mm`, `ms` |
| `walking_step_length`, `walking_speed`, `walking_double_support`, `walking_asymmetry`, `walking_steadiness` | walking mobility measurements | `m`, `km/h`, `%`, `%`, `%` |
| `stair_ascent_speed`, `stair_descent_speed`, `six_minute_walk_distance`, `daylight_duration`, `standing_events` | stair, mobility-test, daylight and standing measurements | `km/h`, `km/h`, `m`, `min`, `count` |
| `audio_exposure_environmental`, `audio_exposure_headphone`, `audio_exposure_reduction`, `audio_exposure_events` | hearing exposure and exposure events | `dB`, `dB`, `dB`, `count` |
| `nutrition_sugar`, `nutrition_sodium`, `nutrition_fat_saturated`, `nutrition_fat_monounsaturated`, `nutrition_fat_polyunsaturated`, `nutrition_potassium`, `nutrition_cholesterol`, `nutrition_calcium`, `nutrition_vitamin_c_intake`, `nutrition_iron`, `nutrition_caffeine`, `water_intake` | dietary details and water intake | `g`, `mg`, `g`, `g`, `g`, `mg`, `mg`, `mg`, `mg`, `mg`, `mg`, `mL` |
| `body_height`, `body_mass_index`, `lean_body_mass`, `heart_rate_recovery` | body composition and recovery | `m`, `index`, `kg`, `bpm` |
| `swimming_strokes`, `handwashing_events`, `mindful_session_duration`, `toothbrushing_events` | daily activity and wellbeing events | `count`, `count`, `min`, `count` |

Health Auto Export sends the unit along with each metric, and that unit follows the phone's
locale — miles or kilometres, hours or minutes. The importer reads it and converts to the
registry's unit; the original value stays in `metadata.provider_value`, the reported unit in
`metadata.units`.

HealthKit types the catalog does not know land under the prefix `apple_health_`. They are not
lost, but they do not occupy a canonical name either. The fields listed above are catalogued,
so their canonical names are the ones to query.

Queries always use the exact `metric_type` value.

### What a workout and a night carry besides their metrics

Health Auto Export has changed the shape of these payloads more than once, and a renamed field
is a quantity that arrives and is dropped in silence. Two spellings of the same quantity are
therefore read wherever both exist, and only the first present becomes a data point — two would
share an `idempotency_key` and the second would be discarded by Core anyway.

| Arrives as | Becomes |
| --- | --- |
| `heartRate: {Min, Avg, Max}`, or the older `avgHeartRate` / `maxHeartRate` | `workout_heart_rate_average`, `workout_heart_rate_max`; the minimum is kept in metadata, the registry having no metric for it |
| `totalEnergy`, or the older `activeEnergyBurned` | `workout_energy` — the session total is preferred, which is what the archive path reads from `totalEnergyBurned` too, so a workout imported both ways cannot mean two things under one name |
| `totalSleep`, or the older `asleep`, or the entry's own `qty` | `sleep_duration` |
| `sleepStart`, `sleepEnd`, `inBedStart`, `inBedEnd` | metadata on that night's readings, normalised to UTC — which night a reading belongs to, a single timestamp cannot say |
| `isIndoor`, `location`, `metadata` | metadata on the session's readings |
| `temperature`, `humidity` | ambient conditions in the session metadata |
| `elevationDown`, `lapLength`, `swimCadence`, `totalSwimmingStrokeCount` | scalar workout metrics after unit conversion |

Apple archive metadata is retained field by field rather than as a raw payload. Indoor/user
entered flags, timezone, weather context, sync identifiers, external UUID, swimming location
and Fitness+ session markers travel with the workout points. Numeric metadata such as average
METs, elevation, maximum speed, lap length and WHOOP strain becomes a normal metric point.
Workout statistics for running dynamics, steps and swimming strokes follow the same registry
and unit conversion rules.

### Time series inside a workout

Some quantities arrive per interval rather than as one figure for the session. An array is not a
reason to lose them: collapsed, a series states the same thing the scalar field does.

| Arrives as | Collapsed by | Becomes |
| --- | --- | --- |
| `activeEnergy` **+** `basalEnergy` | sum of both — they are the two halves of the total | `workout_energy` |
| `walkingAndRunningDistance`, `cyclingDistance` | sum | `workout_distance` |
| `swimDistance` | sum | `workout_distance` |
| `cyclingCadence` | mean | `workout_cycling_cadence` |
| `cyclingPower` | mean | `workout_cycling_power` |
| `cyclingSpeed` | mean | `workout_speed_average` |
| `swimStroke` | sum | `workout_swimming_strokes` |
| `heartRateData` | mean of the samples' averages, and the greatest of their maxima | `workout_heart_rate_average`, `workout_heart_rate_max` |

A figure stated outright always wins: these are read only when the session sent no scalar for that
quantity. A point derived this way says so in its metadata — `derived_from` names the fields,
`derived_by` the operation, `sample_count` how many samples it stands on — so a derived number is
never mistaken for one the phone reported.

What such a series must **not** become is one data point per sample under the daily metric.
`steps` and `distance` aggregate by sum over a day, and the day's own total already arrives from
the phone; adding a workout's per-minute samples on top would make that day read roughly a third
too high everywhere it is shown. Per-sample resolution needs a metric of its own before it can be
stored. A provider-stated workout total always takes precedence over a derived series.

The remaining workout fields without a canonical metric are still named in the
[Data Quality Center](../features/data-quality.md) rather than dropped quietly. This currently
includes recovery time-series data and swimming descriptors such as `heartRateRecovery`,
`strokeStyle`, `swolfScore` and `salinity`. Adding one means adding the metric to the registry
first — one metric, one name, one unit; see [Metrics](../metrics.md).

## Retrieving the data

The measurements are queried through the tenant-protected Core/Gateway API:

```http
GET /api/v1/data/metrics?metric_type=steps&start_time=2026-01-01T00:00:00Z&end_time=2026-01-08T00:00:00Z&limit=1000
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

The JWT has to belong to the workspace named in the `X-Tenant-ID` header. `X-Request-ID` is
what lets one import be followed across the API, the importer and NATS.

For other measurements only the query parameter changes, for example `energy_active`,
`heart_rate_resting` or `sleep_duration`.

## Checking and troubleshooting

### No values appear

Check, in this order:

1. Is the Apple Health export active, and does it actually contain data?
2. Is the connector saved in the right tenant?
3. Is the configuration complete and valid?
4. Was a manual sync started, or is the worker running?
5. Is the expected `metric_type` being queried, and does the period fall inside `start_time`/`end_time`?
6. Are there entries with the same `X-Request-ID` in the importer or Core log?

Without a connector configuration, an empty data set is the expected behaviour. The importer
produces no test data in that case.

### Values appear to be duplicated

The Core service deduplicates on the deterministically derived `idempotency_key`. First check
whether the same measurement really was delivered more than once with different timestamps or
different `metric_type` values.

## What is not imported

Health Auto Export can also send `stateOfMind`, `symptoms`, `cycleTracking`, `ecg`,
`medications` and `heartRateNotifications`. None of them is stored. They are special-category
health data, and whether a platform keeps them is an operator's decision that changes what the
privacy policy has to say — not something a transformer should settle by recognising a field
name.

They are not silently dropped either: each is reported as arriving-but-not-stored, so the
[Data Quality Center](../features/data-quality.md) can answer "my phone sends ECGs and nothing
shows up" instead of leaving you to guess.

## Privacy and limits

Apple Health data deserves particular protection. Configure only the categories you need, and
grant access to the intended tenant only. Credentials are stored encrypted and must not turn up
in logs, broker messages or source code.

Which data is available depends on Apple Health, the permissions that were granted, and the
export app in use. A successful connector sync is therefore no guarantee that values exist for
every period. The API returns normalized platform metrics; the original Apple Health raw objects
are not the primary query format.

The full definition of every metric — its unit, its aggregation and the former names that still
point at it — is in [Metrics](../metrics.md).
