import type { Page, Route } from "@playwright/test";

import { METRIC_CATALOG } from "../src/app/lib/metrics/catalog";
import type { ReportEnvelope } from "../src/app/lib/reports";
import type { MetricSummaryEntry } from "../src/app/components/ExplorerMetricOverview";
import type { DayReport, DayStory } from "../src/app/components/DailyStory";
import type { StoredInsights } from "../src/app/components/AnalysisTab";
import type { DataPointItem } from "../src/app/components/ExplorerTab";
import type { WorkoutSummary } from "../src/app/components/WorkoutsTab";

/**
 * Example data for the screens that are empty on a fresh account.
 *
 * **Why the network and not a component harness.** Storybook is the usual answer to
 * "render a page with example data", and it was rejected on purpose: it renders
 * components in a second environment, outside this app's real layout, theme
 * bootstrap and middleware. Every visual defect found so far lived exactly there —
 * a card header that collides only at 390px, a token that resolves wrongly only in
 * dark mode — so a screenshot of a component in isolation would have shown none of
 * them while looking authoritative. `playwright.config.ts` already argues this for
 * the auth suite: a test with a mocked API would have passed throughout.
 *
 * So the page is the real page, served by the real Gateway and the real Next build,
 * signed in with a real session. Only the data is substituted, at the network
 * boundary, which works because every component here is a client component and
 * `lib/api.ts` fetches from the browser.
 *
 * **Why the fixtures are typed.** `WorkoutSummary`, `DataPointItem` and
 * `MetricSummaryEntry` are the app's own response types. Importing them means a
 * fixture that stops matching the wire shape is a compile error, not a screen that
 * renders empty while the test still passes. That is the failure mode that makes
 * fixture suites rot: they keep passing after the API moves on.
 *
 * Anything not listed here falls through to the real API, so an uncovered screen
 * behaves exactly as it does today rather than breaking.
 */

/**
 * The registry's unit for a metric, and proof the metric exists at all.
 *
 * Written after the first version of this file got it wrong twice in one screen:
 * `workout_duration` was given seconds when the registry declares minutes, so a
 * 45-minute run rendered as "2,700 min", and `sleep_score` was invented outright —
 * there is no such key (rule 15). Both produced a screenshot that looked exactly
 * like an application bug, which is the most expensive kind of wrong fixture: it
 * sends somebody to fix correct code.
 *
 * Deriving the unit from `METRIC_CATALOG` instead of restating it makes the first
 * mistake impossible and the second loud. The catalog is generated from the Python
 * registry by `task metrics:generate`, so this tracks the real thing.
 */
function unitOf(metric: string): string {
  const definition = METRIC_CATALOG[metric];
  if (!definition) {
    throw new Error(
      `fixtures: "${metric}" is not a canonical metric_type (rule 15). ` +
        `Pick a key from packages/shared-schemas/.../metrics.py.`,
    );
  }
  return definition.unit;
}

/** Units for a measure map, taken from the registry rather than retyped. */
function unitsFor(measures: Record<string, number>): Record<string, string> {
  return Object.fromEntries(Object.keys(measures).map((metric) => [metric, unitOf(metric)]));
}

/** Fixed instants, because a fixture that drifts with the clock is not a fixture. */
const DAY = "2026-08-17";
const SOURCE_WHOOP = "11111111-1111-4111-8111-111111111111";
const SOURCE_APPLE = "22222222-2222-4222-8222-222222222222";

function at(hour: number, minute = 0): string {
  return `${DAY}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00Z`;
}

/** A session whose `units` are derived from its `measures`, never restated. */
function session(
  fields: Omit<WorkoutSummary, "units"> & { measures: Record<string, number> },
): WorkoutSummary {
  return { ...fields, units: unitsFor(fields.measures) };
}

const WORKOUTS: WorkoutSummary[] = [
  session({
    session_key: `${SOURCE_WHOOP}:run-1`,
    session_id: "run-1",
    identity: "run-1",
    start: at(6, 40),
    end: at(7, 25),
    title: "Morning run",
    category: "workout",
    source_id: SOURCE_WHOOP,
    measures: {
      workout_duration: 45,
      workout_distance: 8.4,
      workout_energy: 512,
      workout_heart_rate: 148,
      workout_heart_rate_max: 173,
    },
    point_count: 812,
    exercise_count: 0,
    muscle_groups: [],
  }),
  session({
    session_key: `${SOURCE_APPLE}:lift-1`,
    session_id: "lift-1",
    identity: "lift-1",
    start: at(18, 5),
    end: at(19, 12),
    title: "Upper body",
    category: "strength",
    source_id: SOURCE_APPLE,
    measures: {
      workout_duration: 67,
      strength_session_volume: 7480,
      workout_heart_rate: 112,
    },
    point_count: 96,
    exercise_count: 7,
    muscle_groups: ["chest", "back", "shoulders"],
  }),
  session({
    // A session the provider never closed. Worth a fixture of its own: the card has
    // to render without an end time, and a missing `end` is what a live import looks
    // like rather than an error.
    session_key: `${SOURCE_WHOOP}:walk-1`,
    session_id: null,
    identity: "2026-08-17T12:30:00Z_walk",
    start: at(12, 30),
    end: null,
    title: "Walk",
    category: "workout",
    source_id: SOURCE_WHOOP,
    measures: { workout_distance: 2.1, workout_duration: 25 },
    point_count: 41,
    exercise_count: 0,
    muscle_groups: [],
  }),
];

/**
 * An hourly series per metric, shaped like a day rather than like a random walk.
 *
 * Keyed by metric because the chart filters points by `metric_type`: one shared
 * series meant the legend listed three metrics and exactly one line was drawn, so
 * the screenshot showed a chart that looked broken and was only under-fed.
 */
const HOURLY: Record<string, number[]> = {
  steps: [
    0, 0, 0, 0, 0, 120, 940, 1580, 620, 410, 380, 520, 1240, 760, 430, 690, 1810, 2240, 980, 610,
    340, 180, 60, 0,
  ],
  heart_rate_resting: [
    52, 51, 50, 50, 51, 53, 58, 62, 60, 59, 61, 63, 66, 64, 62, 65, 72, 78, 70, 64, 58, 55, 53, 52,
  ],
  sleep_duration: [60, 60, 60, 60, 60, 33, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 20, 60],
};

function seriesFor(metric: string): DataPointItem[] {
  const perHour = HOURLY[metric] ?? HOURLY.steps;
  return perHour.map((value, hour) => ({
    id: `${metric}-${hour}`,
    source_id: SOURCE_APPLE,
    source_type: "apple_health",
    metric_type: metric,
    timestamp: at(hour),
    value,
    metadata: { provider_value: value, units: unitOf(metric) },
    sample_count: 1,
    resolution: "hour",
  }));
}

/** Every metric the request asked for, or all of them when it named none. */
function pointsFor(url: string): DataPointItem[] {
  const asked = new URL(url).searchParams.getAll("metric_type");
  const metrics = asked.length > 0 ? asked : Object.keys(HOURLY);
  return metrics.flatMap((metric) => seriesFor(metric));
}

const SUMMARY: Record<string, MetricSummaryEntry> = {
  steps: {
    count: 24,
    average: 683,
    min: 0,
    max: 2240,
    sum: 16400,
    latest_timestamp: at(23),
    definition: { unit: unitOf("steps"), aggregation: "sum", category: "activity", precision: 0 },
  },
  heart_rate_resting: {
    count: 1,
    average: 52,
    min: 52,
    max: 52,
    sum: 52,
    latest_timestamp: at(7),
    definition: {
      unit: unitOf("heart_rate_resting"),
      aggregation: "average",
      category: "heart",
      precision: 0,
    },
  },
  sleep_duration: {
    count: 1,
    average: 453,
    min: 453,
    max: 453,
    sum: 453,
    latest_timestamp: at(7),
    definition: {
      unit: unitOf("sleep_duration"),
      aggregation: "sum",
      category: "sleep",
      precision: 0,
    },
  },
};

const DAY_STORY: DayStory = {
  day: DAY,
  is_today: false,
  complete: true,
  lanes: [
    {
      category: "sleep",
      last_import_at: at(8),
      complete: true,
      metrics: [
        {
          metric_type: "sleep_duration",
          value: 453,
          unit: unitOf("sleep_duration"),
          aggregation: "sum",
          cadence: "daily",
          sample_count: 1,
          source_id: SOURCE_WHOOP,
          source_type: "whoop",
          source_reason: "only_source",
          other_sources: [],
          last_at: at(7),
        },
        {
          // `sleep_score` does not exist in the registry; `unitOf` now refuses it.
          metric_type: "sleep_efficiency",
          value: 91,
          unit: unitOf("sleep_efficiency"),
          aggregation: "last",
          cadence: "daily",
          sample_count: 1,
          source_id: SOURCE_WHOOP,
          source_type: "whoop",
          source_reason: "only_source",
          other_sources: [],
          last_at: at(7),
        },
      ],
    },
    {
      category: "activity",
      last_import_at: at(23, 40),
      complete: true,
      metrics: [
        {
          metric_type: "steps",
          value: 16400,
          unit: unitOf("steps"),
          aggregation: "sum",
          cadence: "daily",
          sample_count: 24,
          source_id: SOURCE_APPLE,
          source_type: "apple_health",
          // Two connectors report steps, so the card has to say which one it chose
          // and why — the case that made `source_reason` an identifier.
          source_reason: "preference",
          other_sources: [SOURCE_WHOOP],
          last_at: at(23),
        },
      ],
    },
    {
      category: "nutrition",
      last_import_at: at(21),
      complete: false,
      metrics: [
        {
          metric_type: "nutrition_energy",
          value: 2180,
          unit: unitOf("nutrition_energy"),
          aggregation: "sum",
          cadence: "daily",
          sample_count: 12,
          source_id: SOURCE_APPLE,
          source_type: "yazio",
          source_reason: "only_source",
          other_sources: [],
          last_at: at(21),
        },
      ],
    },
  ],
  events: [
    {
      at: at(6, 40),
      until: at(7, 25),
      title: "Morning run",
      category: "workout",
      source_id: SOURCE_WHOOP,
      measures: { workout_distance: 8.4, workout_energy: 512 },
    },
    {
      at: at(18, 5),
      until: at(19, 12),
      title: "Upper body",
      category: "strength",
      source_id: SOURCE_APPLE,
      measures: { strength_session_volume: 7480 },
    },
  ],
  event_limit_reached: false,
  logged: [
    {
      group: "breakfast",
      category: "nutrition",
      entry_count: 2,
      energy: 480,
      energy_derived: false,
      unit: "kcal",
      logged_at: at(8, 15),
      entries: [
        {
          title: "Oat porridge",
          metric_type: "nutrition_energy",
          value: 320,
          unit: "kcal",
          logged_at: at(8, 15),
          amount: 80,
          serving_unit: "g",
        },
        {
          title: "Coffee",
          metric_type: "nutrition_energy",
          value: 160,
          unit: "kcal",
          logged_at: at(8, 20),
          amount: 1,
          serving_unit: "cup",
        },
      ],
    },
    {
      group: "dinner",
      category: "nutrition",
      entry_count: 1,
      energy: 900,
      // Our sum rather than the provider's own total, which the card marks.
      energy_derived: true,
      unit: "kcal",
      logged_at: null,
      entries: [
        {
          title: "Pasta with pesto",
          metric_type: "nutrition_energy",
          value: 900,
          unit: "kcal",
          logged_at: null,
          amount: 350,
          serving_unit: "g",
        },
      ],
    },
  ],
  logged_limit_reached: false,
};

/**
 * The day report, as an envelope around a *list* of days.
 *
 * Typed as `ReportEnvelope<DayReport>` after the untyped first attempt put a single
 * `DayStory` straight into `result`. The page reads `result.days`, so it rendered
 * the "Computed …" line from a payload it had understood and nothing underneath —
 * a screen that looks like a broken day story rather than a wrong fixture. The type
 * makes that a compile error.
 */
const DAY_REPORT: ReportEnvelope<DayReport> = {
  kind: "day",
  status: "ready",
  stale: false,
  deferred: false,
  running: false,
  computed_at: at(23, 55),
  covers_data_through: at(23, 59),
  params: { offset_minutes: 0 },
  result: { offset_minutes: 0, days: [DAY_STORY] },
  error: null,
};

const UNSUPPORTED_FIELDS = {
  fields: [
    {
      field_path: "workout.swimStrokeCount",
      source_type: "apple_health",
      source_id: SOURCE_APPLE,
      occurrences: 214,
      first_seen_at: at(3),
      last_seen_at: at(22),
      sample_value: "1840",
      metric_type: null,
      supported_since: null,
    },
    {
      field_path: "recovery.spo2Percentage",
      source_type: "whoop",
      source_id: SOURCE_WHOOP,
      occurrences: 31,
      first_seen_at: at(4),
      last_seen_at: at(20),
      sample_value: "96.4",
      metric_type: null,
      supported_since: null,
    },
  ],
};


/**
 * An insights bundle with findings in it.
 *
 * `/analysis` was the one destination with no filled fixture, so the analysis tab with
 * *data* had never been rendered by any test or looked at by anybody — while
 * `normaliseInsights` was rewritten underneath it. Empty-state coverage cannot catch a
 * correlation card that collides at 390px or a heatmap cell whose colour fails contrast,
 * because neither is in the document until a finding exists.
 *
 * Typed as `StoredInsights`, which is the shape the wire may carry rather than the
 * normalised one — a fixture that types itself against the strict shape would be
 * claiming the server guarantees fields it does not, and would stop compiling for the
 * wrong reason the next time one becomes optional.
 *
 * **Every identifier here was checked against `services/analysis/src/analysis/insights.py`
 * rather than guessed**, because a fixture that guesses produces a screen that looks
 * exactly like an application bug — the most expensive kind of wrong fixture, since it
 * sends somebody to fix correct code. The first draft got three wrong and the screenshot
 * showed all three: a correlation `direction` of `lower` where the wire says
 * `negative`/`positive`, an anomaly `direction` of `higher` where it says
 * `unusually high` (which the client turns into `analysis.anomalyDirection.unusually_high`),
 * and `interpretation_params` missing `sample_size` — so the sentence rendered the
 * literal text `{sample_size} shared days`. They are legible English and valid markup,
 * so axe cannot object; the filled suite now rejects unresolved placeholders and
 * catalogue keys explicitly.
 *
 * These are identifiers, not prose (rule 17), and the two vocabularies differ by field:
 * `positive`/`negative` for a correlation's own direction, `higher`/`lower` inside its
 * interpretation params, `rising`/`falling`/`flat` for a trend, `unusually high`/`unusually
 * low` for an outlier.
 */
const INSIGHTS: StoredInsights = {
  provenance: {
    analysis_version: "1.4.0",
    computed_at: at(4, 30),
    window_start: "2026-05-19T00:00:00Z",
    window_end: `${DAY}T23:59:59Z`,
    sources: ["whoop", "apple_health"],
  },
  disclaimer: "Results describe statistical associations, not cause and effect.",
  metrics_analysed: ["steps", "sleep_duration", "sleep_efficiency", "heart_rate_resting"],
  metrics_excluded_for_quality: ["body_weight"],
  data_quality: {
    steps: { observed_days: 88, window_days: 90, coverage_pct: 97.8, sufficient: true, note: "" },
    sleep_duration: {
      observed_days: 84, window_days: 90, coverage_pct: 93.3, sufficient: true, note: "",
    },
    sleep_efficiency: {
      observed_days: 84, window_days: 90, coverage_pct: 93.3, sufficient: true, note: "",
    },
    heart_rate_resting: {
      observed_days: 90, window_days: 90, coverage_pct: 100, sufficient: true, note: "",
    },
    body_weight: {
      observed_days: 9, window_days: 90, coverage_pct: 10, sufficient: false,
      note: "Too few days to analyse.",
    },
  },
  correlations: [
    {
      metric_a: "sleep_duration",
      metric_b: "heart_rate_resting",
      pearson: -0.62,
      spearman: -0.59,
      coefficient: -0.62,
      strength_pct: 62,
      direction: "negative",
      strength_label: "moderate",
      sample_size: 84,
      p_value: 0.0001,
      q_value: 0.0004,
      multiple_testing_method: "benjamini_hochberg",
      significant: true,
      interpretation_code: "correlation_association",
      interpretation_params: {
        metric_a: "sleep_duration",
        metric_b: "heart_rate_resting",
        direction: "lower",
        strength: "moderate",
        sample_size: 84,
        q_value: 0.0004,
        significant: true,
      },
      interpretation: "Longer sleep is associated with a lower resting heart rate.",
      caveats: [],
      caveat_codes: [],
    },
    {
      metric_a: "steps",
      metric_b: "sleep_efficiency",
      pearson: 0.31,
      spearman: 0.28,
      coefficient: 0.31,
      strength_pct: 31,
      direction: "positive",
      strength_label: "weak",
      sample_size: 82,
      p_value: 0.041,
      q_value: 0.082,
      multiple_testing_method: "benjamini_hochberg",
      // Deliberately not significant after correction: the card has to render the
      // distinction, and an all-significant fixture never exercises it.
      significant: false,
      interpretation_code: "correlation_association",
      interpretation_params: {
        metric_a: "steps",
        metric_b: "sleep_efficiency",
        direction: "higher",
        strength: "weak",
        sample_size: 82,
        q_value: 0.082,
        significant: false,
      },
      interpretation: "More steps are associated with higher sleep efficiency.",
      caveats: ["Not statistically significant after adjustment."],
      caveat_codes: [{ code: "bh_not_significant_raw_below_alpha", params: {} }],
    },
  ],
  lagged_correlations: [
    {
      metric_a: "steps",
      metric_b: "sleep_duration",
      lag_days: 1,
      coefficient: 0.34,
      strength_pct: 34,
      sample_size: 80,
      p_value: 0.03,
      significant: true,
      significance_method: "unadjusted_exploratory",
      interpretation_code: "lagged_association",
      interpretation_params: {
        metric_a: "steps",
        metric_b: "sleep_duration",
        lag_days: 1,
        strength: "weak",
        sample_size: 80,
      },
      interpretation: "A day with more steps is followed by slightly longer sleep.",
    },
  ],
  trends: {
    heart_rate_resting: {
      direction: "falling",
      slope_per_day: -0.02,
      change_pct_over_window: -3.4,
      r_squared: 0.41,
      sample_size: 90,
      mean: 54.2,
      // A `null` in the middle on purpose: a gap in a moving average is a real thing
      // and the sparkline has to survive it rather than draw through it.
      moving_average_7d: [56.1, 55.8, 55.4, null, 54.9, 54.4, 53.9, 53.6],
      interpretation_code: "trend_summary",
      interpretation_params: {
        direction: "falling",
        change_pct: -3.4,
        sample_size: 90,
        uncertain: false,
      },
      interpretation: "Resting heart rate is falling slightly over the window.",
    },
  },
  anomalies: {
    sleep_duration: {
      baseline_median: 447,
      normal_range_low: 372,
      normal_range_high: 522,
      sample_size: 84,
      anomalies: [
        {
          date: "2026-07-04", value: 288, deviation_score: -2.6,
          direction: "unusually low",
        },
        {
          date: "2026-08-02", value: 601, deviation_score: 2.1,
          direction: "unusually high",
        },
      ],
      interpretation_code: "anomaly_summary",
      interpretation_params: {
        normal_range_low: 372,
        normal_range_high: 522,
        anomaly_count: 2,
        sample_size: 84,
      },
      interpretation: "Two nights fell outside the usual range.",
    },
  },
  routines: {
    steps: {
      per_weekday: [
        { weekday: "monday", mean: 9200, sample_size: 13 },
        { weekday: "tuesday", mean: 11400, sample_size: 13 },
        { weekday: "wednesday", mean: 10800, sample_size: 13 },
        { weekday: "thursday", mean: 9900, sample_size: 12 },
        { weekday: "friday", mean: 12600, sample_size: 13 },
        // A weekday with no data at all: `null` is a gap, not a zero, and the bar
        // has to be absent rather than flat on the floor.
        { weekday: "saturday", mean: null, sample_size: 0 },
        { weekday: "sunday", mean: 6400, sample_size: 12 },
      ],
      weekend_effect: {
        weekday_mean: 10780,
        weekend_mean: 6400,
        difference_pct: -40.6,
        interpretation_code: "routine_weekend_difference",
        interpretation_params: { difference_pct: -40.6, direction: "lower" },
        interpretation: "Weekends are considerably quieter than weekdays.",
      },
    },
  },
  period_comparisons: {},
  strength: {
    exercises: [
      {
        exercise_title: "Bench press",
        muscle_group: "chest",
        sessions: 11,
        total_sets: 44,
        total_volume_kg: 24_860,
        best_set_weight_kg: 82.5,
        best_set_day: "2026-08-11",
        latest_estimated_1rm_kg: 92.3,
        trend: {
          direction: "rising",
          basis: "estimated_1rm",
          change_pct_over_window: 6.4,
          r_squared: 0.55,
          sample_size: 11,
        },
      },
      {
        exercise_title: "Pull-up",
        muscle_group: "back",
        sessions: 9,
        total_sets: 31,
        // Bodyweight: zero volume at every session is real, and calling that flat
        // would be a wrong answer — `basis` says it trends on repetitions instead.
        total_volume_kg: 0,
        best_set_weight_kg: null,
        best_set_day: null,
        latest_estimated_1rm_kg: null,
        trend: {
          direction: "rising",
          basis: "reps",
          change_pct_over_window: 12.5,
          r_squared: 0.62,
          sample_size: 9,
        },
      },
    ],
    muscle_groups: [
      { muscle_group: "chest", volume_kg: 24_860, sets: 44, volume_share_pct: 58.1, set_share_pct: 58.7 },
      { muscle_group: "back", volume_kg: 17_930, sets: 31, volume_share_pct: 41.9, set_share_pct: 41.3 },
    ],
    sets_analysed: 75,
    truncated: false,
    min_sessions_for_trend: 4,
    disclaimer: "Estimated one-rep maxima are calculated, not measured.",
  },
};

const INSIGHTS_REPORT: ReportEnvelope<StoredInsights> = {
  kind: "insights",
  status: "ready",
  stale: false,
  deferred: false,
  running: false,
  computed_at: at(4, 30),
  covers_data_through: `${DAY}T23:59:59Z`,
  params: { days: 90, compare_to_previous: true },
  result: INSIGHTS,
  error: null,
};

/**
 * One route table. Keys are matched against the pathname *and* query, first match
 * wins, and a request that matches nothing is left to the real API.
 */
const ROUTES: Array<[RegExp, unknown | ((url: string) => unknown)]> = [
  [
    /\/api\/v1\/data\/workouts\b/,
    { sessions: WORKOUTS, scan_limit_reached: false, has_more: false },
  ],
  [/\/api\/v1\/data\/metrics\/summary\b/, { metrics: SUMMARY }],
  [
    /\/api\/v1\/data\/metrics\/types\b/,
    { metric_types: Object.keys(SUMMARY).map((metric_type) => ({ metric_type, count: 24 })) },
  ],
  [
    /\/api\/v1\/data\/metrics\?/,
    (url: string) => {
      const points = pointsFor(url);
      return { data_points: points, total: points.length, has_more: false };
    },
  ],
  [/\/api\/v1\/data\/reports\/day\b/, DAY_REPORT],
  [/\/api\/v1\/data\/reports\/insights\b/, INSIGHTS_REPORT],
  [/\/api\/v1\/data\/quality\/unsupported-fields\b/, UNSUPPORTED_FIELDS],
];

/**
 * The same day report as an **older Core** would have written it.
 *
 * A report is stored and served while stale — `lib/reports.ts` says so outright — so a
 * newly deployed client will read payloads written by the version before it. Every
 * field this release added is therefore absent from the data already in the database,
 * and that is not an edge case: it is what every existing installation looks like on
 * the morning after an update.
 *
 * This shape is the one that took production down. `logged` and `logged_limit_reached`
 * arrived with the meal log; the overview called `story.logged.reduce(...)` on a
 * payload that predated them and threw `Cannot read properties of undefined`, which
 * Next rendered as its own fallback page — so the whole dashboard was a blank error
 * after every sign-in, for the one reason no test covered.
 *
 * Derived by deletion rather than written out, so it cannot drift from the current
 * fixture: whatever the fresh payload gains, this one keeps lacking exactly the two
 * fields under test.
 */
function staleDayStory(): Record<string, unknown> {
  const { logged, logged_limit_reached, ...rest } = DAY_STORY as unknown as Record<string, unknown>;
  void logged;
  void logged_limit_reached;
  return rest;
}

const STALE_DAY_REPORT = {
  ...DAY_REPORT,
  // Stale on purpose: this is a run from before the update, which is exactly why the
  // client is handed a shape it did not write.
  stale: true,
  result: { offset_minutes: 0, days: [staleDayStory()] },
};

/**
 * Serve reports in the shape an older Core wrote, and everything else as usual.
 *
 * Installed instead of `useFixtures`, not alongside it: the first matching route wins,
 * so the two would fight over `/reports/day`.
 */
export async function useStaleReportFixtures(page: Page): Promise<void> {
  // General first, specific second. Playwright matches the **last** registered route,
  // so registering these the other way round let the broad `/data/**` handler answer
  // the day report with the current shape — and the test passed while testing nothing.
  await useFixtures(page);
  await page.route("**/api/v1/data/reports/day*", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(STALE_DAY_REPORT),
    });
  });
}

/**
 * Serve the fixtures above for this page.
 *
 * Installed before the first navigation so a screen never renders its empty state
 * first and then swaps — a screenshot taken mid-swap is the kind of flake that
 * makes people stop trusting a suite.
 */
export async function useFixtures(page: Page): Promise<void> {
  await page.route("**/api/v1/data/**", async (route: Route) => {
    const url = route.request().url();
    if (route.request().method() !== "GET") return route.fallback();
    for (const [pattern, body] of ROUTES) {
      if (pattern.test(url)) {
        const payload = typeof body === "function" ? (body as (u: string) => unknown)(url) : body;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(payload),
        });
      }
    }
    return route.fallback();
  });
}

/** The screens the fixtures above actually fill, for a suite to iterate. */
export const FILLED_ROUTES = [
  "/",
  "/explorer",
  "/workouts",
  "/quality",
  "/analysis",
] as const;

/**
 * Every report kind, answered with the thinnest payload a stored run can have.
 *
 * `useStaleReportFixtures` above reproduces one outage precisely: two named fields
 * missing from the day report. This is the same idea taken to the general case,
 * because the specific fix that followed that outage was applied to the two fields
 * rather than to the shape — `AnalysisTab` went on dereferencing seven required
 * fields of a payload no schema validates, and `Object.keys(undefined)` throws just
 * as loudly as `undefined.reduce`.
 *
 * `result: {}` is not a contrived shape. It is the lower bound of what a stored run
 * can hand a client, and every field a release ever adds is missing from it by
 * definition. A component that survives this survives every future rename, which is
 * the property worth having: the next field to be added is not knowable today, so a
 * test naming today's fields would only ever catch yesterday's bug.
 *
 * `status: "ready"` deliberately, with a `computed_at`: this must not be mistaken
 * for the never-computed state, which every tab already handles. The claim under
 * test is "a finished run whose shape we do not recognise", and the only acceptable
 * outcome is a page that renders with its sections empty.
 */
const MINIMAL_ENVELOPE = {
  status: "ready" as const,
  stale: true,
  deferred: false,
  running: false,
  computed_at: at(6),
  covers_data_through: at(6),
  params: {},
  result: {},
  error: null,
};

/**
 * Serve `result: {}` for every report kind, and real fixtures for everything else.
 *
 * Registered after `useFixtures` for the reason that one documents: Playwright
 * matches the **last** registered route, so the broad `/data/**` handler would
 * otherwise answer the day report with the current shape and the suite would test
 * nothing while passing.
 */
export async function useMinimalReportFixtures(page: Page): Promise<void> {
  await useFixtures(page);
  await page.route("**/api/v1/data/reports/**", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const kind = new URL(route.request().url()).pathname.split("/").pop() ?? "day";
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ kind, ...MINIMAL_ENVELOPE }),
    });
  });
}

/**
 * The screens that read a precomputed report, and therefore the ones a stored
 * payload from another release can reach. Derived from `useReport` call sites:
 * the overview reads `day`, analysis reads `insights`, quality reads `gaps` and
 * `conflicts`.
 */
export const REPORT_ROUTES = ["/", "/analysis", "/quality"] as const;

/**
 * A report whose field changed *type* rather than merely going missing.
 *
 * `useMinimalReportFixtures` covers absence, and normalisation answers absence
 * completely. It cannot answer this: `gaps: 7` satisfies no reader's expectations and
 * `?? []` leaves it exactly where it was, so `gaps.reduce(...)` throws. Nor should
 * normalisation try — validating every field's type at the boundary is a schema
 * validator, and this app does not have one on the client.
 *
 * So this fixture exists to test the *other* half of the answer: that a throw is
 * caught by an error boundary, that the reader gets a page they can read and act on,
 * and that the navigation above it survives. A crash that costs one screen is an
 * acceptable outcome; a crash that costs the whole dashboard is what happened in
 * production.
 */
export async function useBrokenReportFixtures(page: Page): Promise<void> {
  await useFixtures(page);
  await page.route("**/api/v1/data/reports/gaps*", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        kind: "gaps",
        ...MINIMAL_ENVELOPE,
        // A number where the client expects a list. Not contrived: a field that
        // changes from a list to a count is an ordinary API evolution, and the stored
        // report from before the change keeps the old shape either way.
        result: { gaps: 7, cadence_gaps: [] },
      }),
    });
  });
}
