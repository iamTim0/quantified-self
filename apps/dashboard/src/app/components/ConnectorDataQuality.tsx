"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "../lib/api";
import { useI18n } from "../lib/i18n/provider";
import { CANONICAL_KEYS } from "../lib/metrics/catalog";
import Disclosure from "./Disclosure";

/**
 * One connector's data-quality chores, on that connector's own page.
 *
 * These three lists used to live on `/quality`, which presented them as a
 * property of the workspace. They are not: every row carries a `source_id`, the
 * decisions they ask for are per connector ("this Whoop field is a heart rate",
 * "these Apple Health rows are junk"), and the page that already shows a
 * connector's run history was counting `unsupported_fields` per run with nowhere
 * to click through to what they actually were.
 *
 * What stayed on `/quality` is what genuinely spans the workspace: gaps and
 * cross-source conflicts, which are questions about the data as a whole rather
 * than about any one connector.
 *
 * Capacity alarms are elsewhere again — `QuarantineAlerts` puts them in the
 * shell, because a connector refusing to store values is not news that should
 * wait until somebody opens its detail page.
 */

type QuarantinedMetric = {
  source_id: string;
  source_type: string;
  connector_name: string;
  raw_metric_type: string;
  points: number;
  seen: number;
  units: string | null;
  action: MappingAction | null;
};

type MappingAction = "map" | "adopt" | "discard" | "keep";

type QuarantineCapacity = {
  source_id: string;
  warning_code: string;
  usage_percent: number;
  active_rows: number;
  max_rows: number;
  active_names: number;
  max_names: number;
};

type MappingDraft = {
  action: MappingAction;
  target_metric_type: string;
  source_unit: string;
  target_unit: string;
  aggregation: "average" | "sum" | "last" | "max";
  cadence: "event" | "daily" | "continuous";
  keep_indefinitely: boolean;
};

type UnsupportedField = {
  source_id: string;
  source_type: string;
  connector_name: string;
  field_path: string;
  value_kind: string;
  occurrences: number;
  last_seen_at: string;
};

type NewlySupportedField = {
  source_id: string;
  source_type: string;
  connector_name: string;
  field_path: string;
  metric_type: string | null;
  occurrences: number;
  supported_since: string;
  history_recoverable: boolean;
  history_backfilled_at: string | null;
};

export default function ConnectorDataQuality({
  apiBase,
  sourceId,
}: {
  apiBase: string;
  /** Only this connector's rows are shown; the endpoints answer for the tenant. */
  sourceId: string;
}) {
  const { t, formatDate, formatNumber } = useI18n();
  const [quarantine, setQuarantine] = useState<QuarantinedMetric[]>([]);
  const [unsupported, setUnsupported] = useState<UnsupportedField[]>([]);
  const [newlySupported, setNewlySupported] = useState<NewlySupportedField[]>([]);
  const [drafts, setDrafts] = useState<Record<string, MappingDraft>>({});
  const [saving, setSaving] = useState<string | null>(null);
  /**
   * This connector's quarantine fill level.
   *
   * `QuarantineAlerts` in the shell shows only the two states that mean data is
   * being lost right now. The quieter ones — half full, something pending —
   * belong here rather than nowhere: a banner on every screen that reports a
   * situation needing no action is how people learn to skip the banner.
   */
  const [capacity, setCapacity] = useState<QuarantineCapacity | null>(null);

  const load = useCallback(async () => {
    const [quarantineRes, unsupportedRes, newlyRes] = await Promise.all([
      apiFetch(`${apiBase}/api/v1/data/quality/quarantine`),
      apiFetch(`${apiBase}/api/v1/data/quality/unsupported-fields`),
      apiFetch(`${apiBase}/api/v1/data/quality/newly-supported-fields`),
    ]);
    // The endpoints answer for the whole tenant; every row names its connector,
    // so the page filters rather than the API growing a parameter for one caller.
    function mine<T extends { source_id: string }>(rows: T[]): T[] {
      return rows.filter((row) => row.source_id === sourceId);
    }

    if (quarantineRes.ok) {
      const body = (await quarantineRes.json()) as {
        metrics?: QuarantinedMetric[];
        capacity?: QuarantineCapacity[];
      };
      setQuarantine(mine(body.metrics ?? []));
      setCapacity(mine(body.capacity ?? [])[0] ?? null);
    }
    if (unsupportedRes.ok) {
      const body = (await unsupportedRes.json()) as { fields?: UnsupportedField[] };
      setUnsupported(mine(body.fields ?? []));
    }
    if (newlyRes.ok) {
      const body = (await newlyRes.json()) as { fields?: NewlySupportedField[] };
      setNewlySupported(mine(body.fields ?? []));
    }
  }, [apiBase, sourceId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) await load();
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  const draftFor = (metric: QuarantinedMetric): MappingDraft =>
    drafts[metric.raw_metric_type] ?? {
      action: metric.action ?? "keep",
      target_metric_type: CANONICAL_KEYS[0] ?? "steps",
      source_unit: metric.units ?? "count",
      target_unit: "",
      aggregation: "average",
      cadence: "event",
      keep_indefinitely: false,
    };

  const updateDraft = (metric: QuarantinedMetric, change: Partial<MappingDraft>) =>
    setDrafts((current) => ({
      ...current,
      [metric.raw_metric_type]: { ...draftFor(metric), ...change },
    }));

  const saveMapping = async (metric: QuarantinedMetric) => {
    const draft = draftFor(metric);
    setSaving(metric.raw_metric_type);
    try {
      const response = await apiFetch(`${apiBase}/api/v1/data/quality/mapping-rules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_id: metric.source_id,
          raw_metric_type: metric.raw_metric_type,
          action: draft.action,
          target_metric_type:
            draft.action === "map" || draft.action === "adopt"
              ? draft.target_metric_type
              : undefined,
          source_unit:
            draft.action === "map" || draft.action === "adopt" ? draft.source_unit : undefined,
          target_unit: draft.action === "adopt" ? draft.target_unit : undefined,
          aggregation: draft.action === "adopt" ? draft.aggregation : undefined,
          cadence: draft.action === "adopt" ? draft.cadence : undefined,
          keep_indefinitely: draft.action === "keep" ? draft.keep_indefinitely : false,
        }),
      });
      if (response.ok) await load();
    } finally {
      setSaving(null);
    }
  };

  const copyFieldReport = async () => {
    const lines = unsupported.map(
      (field) =>
        `| ${field.field_path} | ${field.value_kind} | ${field.occurrences} | ${formatDate(field.last_seen_at)} |`,
    );
    await navigator.clipboard.writeText(
      [`| Field | Kind | Seen | Last seen |`, `| --- | --- | --- | --- |`, ...lines].join("\n"),
    );
  };

  if (
    quarantine.length === 0 &&
    unsupported.length === 0 &&
    newlySupported.length === 0 &&
    capacity === null
  ) {
    return null;
  }

  return (
    <div className="space-y-3">
      {capacity && (
        <p className="rounded-2xl border border-line bg-surface px-4 py-3 text-meta text-ink-muted">
          {t("quality.quarantineCapacityUsage", {
            rows: formatNumber(capacity.active_rows),
            maxRows: formatNumber(capacity.max_rows),
            names: formatNumber(capacity.active_names),
            maxNames: formatNumber(capacity.max_names),
          })}
        </p>
      )}

      {/* Open by default: this is the only one of the three that asks the reader
          to decide something, and a decision behind a closed row is a decision
          nobody makes. */}
      {quarantine.length > 0 && (
        <Disclosure
          defaultOpen
          titleAs="h2"
          title={t("quality.quarantineTitle")}
          meta={formatNumber(quarantine.length)}
          note={t("quality.quarantineHint")}
        >
          <div className="space-y-4">
            {quarantine.map((metric) => {
              const draft = draftFor(metric);
              return (
                <div
                  key={metric.raw_metric_type}
                  className="rounded-2xl border border-info-line bg-info-soft p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-body font-semibold text-ink">
                        {metric.raw_metric_type}
                      </p>
                      <p className="mt-1 text-meta text-ink-muted">
                        {t("quality.quarantineConnectorDetail", {
                          connector: metric.connector_name || metric.source_type,
                          count: metric.points,
                        })}
                      </p>
                    </div>
                    <select
                      value={draft.action}
                      onChange={(event) =>
                        updateDraft(metric, { action: event.target.value as MappingAction })
                      }
                      className="min-h-11 rounded-xl border border-info-line bg-surface px-2.5 text-meta text-ink-secondary focus-ring"
                      aria-label={t("quality.mappingDecision")}
                    >
                      <option value="map">{t("quality.mappingMap")}</option>
                      <option value="adopt">{t("quality.mappingAdopt")}</option>
                      <option value="discard">{t("quality.mappingDiscard")}</option>
                      <option value="keep">{t("quality.mappingKeep")}</option>
                    </select>
                  </div>

                  {(draft.action === "map" || draft.action === "adopt") && (
                    <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                      {draft.action === "map" ? (
                        <select
                          value={draft.target_metric_type}
                          onChange={(event) =>
                            updateDraft(metric, { target_metric_type: event.target.value })
                          }
                          className="min-h-11 rounded-xl border border-line px-2.5 text-meta focus-ring"
                          aria-label={t("quality.mappingTarget")}
                        >
                          {CANONICAL_KEYS.map((keyName) => (
                            <option key={keyName} value={keyName}>
                              {keyName}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          value={draft.target_metric_type}
                          onChange={(event) =>
                            updateDraft(metric, { target_metric_type: event.target.value })
                          }
                          placeholder={t("quality.mappingCustomName")}
                          className="min-h-11 rounded-xl border border-line px-2.5 text-meta focus-ring"
                          aria-label={t("quality.mappingTarget")}
                        />
                      )}
                      <input
                        value={draft.source_unit}
                        onChange={(event) =>
                          updateDraft(metric, { source_unit: event.target.value })
                        }
                        placeholder={t("quality.mappingSourceUnit")}
                        className="min-h-11 rounded-xl border border-line px-2.5 text-meta focus-ring"
                        aria-label={t("quality.mappingSourceUnit")}
                      />
                      {draft.action === "adopt" && (
                        <>
                          <input
                            value={draft.target_unit}
                            onChange={(event) =>
                              updateDraft(metric, { target_unit: event.target.value })
                            }
                            placeholder={t("quality.mappingTargetUnit")}
                            className="min-h-11 rounded-xl border border-line px-2.5 text-meta focus-ring"
                            aria-label={t("quality.mappingTargetUnit")}
                          />
                          <select
                            value={draft.aggregation}
                            onChange={(event) =>
                              updateDraft(metric, {
                                aggregation: event.target.value as MappingDraft["aggregation"],
                              })
                            }
                            className="min-h-11 rounded-xl border border-line px-2.5 text-meta focus-ring"
                            aria-label={t("quality.mappingAggregation")}
                          >
                            <option value="average">{t("quality.mappingAverage")}</option>
                            <option value="sum">{t("quality.mappingSum")}</option>
                            <option value="last">{t("quality.mappingLast")}</option>
                            <option value="max">{t("quality.mappingMax")}</option>
                          </select>
                          <select
                            value={draft.cadence}
                            onChange={(event) =>
                              updateDraft(metric, {
                                cadence: event.target.value as MappingDraft["cadence"],
                              })
                            }
                            className="min-h-11 rounded-xl border border-line px-2.5 text-meta focus-ring"
                            aria-label={t("quality.mappingCadence")}
                          >
                            <option value="event">{t("quality.mappingEvent")}</option>
                            <option value="daily">{t("quality.mappingDaily")}</option>
                            <option value="continuous">{t("quality.mappingContinuous")}</option>
                          </select>
                        </>
                      )}
                    </div>
                  )}

                  {draft.action === "keep" && (
                    <label className="mt-3 flex min-h-11 items-center gap-2 text-meta text-ink-secondary">
                      <input
                        type="checkbox"
                        checked={draft.keep_indefinitely}
                        onChange={(event) =>
                          updateDraft(metric, { keep_indefinitely: event.target.checked })
                        }
                      />
                      {t("quality.mappingKeepIndefinitely")}
                    </label>
                  )}

                  <button
                    type="button"
                    onClick={() => void saveMapping(metric)}
                    disabled={saving === metric.raw_metric_type}
                    className="mt-3 inline-flex min-h-11 items-center rounded-2xl bg-brand px-4 text-meta font-bold text-brand-ink hover:bg-brand-hover disabled:opacity-50"
                  >
                    {saving === metric.raw_metric_type
                      ? t("quality.mappingSaving")
                      : t("quality.mappingApply")}
                  </button>
                </div>
              );
            })}
          </div>
        </Disclosure>
      )}

      {newlySupported.length > 0 && (
        <Disclosure
          titleAs="h2"
          title={t("quality.newlySupportedTitle", { count: String(newlySupported.length) })}
          meta={formatNumber(newlySupported.length)}
          note={t("quality.newlySupportedHint")}
        >
          <div className="overflow-x-auto">
            <table className="w-full text-left text-meta">
              <thead>
                <tr className="border-b border-line text-ink-muted">
                  <th className="py-1 pr-4 font-semibold">{t("quality.colField")}</th>
                  <th className="py-1 pr-4 font-semibold">{t("quality.colMetric")}</th>
                  <th className="py-1 pr-4 font-semibold">{t("quality.colSince")}</th>
                  <th className="py-1 font-semibold">{t("quality.colHistory")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line text-ink-secondary">
                {newlySupported.map((field) => (
                  <tr key={field.field_path}>
                    <td className="py-1.5 pr-4 font-mono">{field.field_path}</td>
                    <td className="py-1.5 pr-4 font-mono">{field.metric_type ?? "—"}</td>
                    <td className="py-1.5 pr-4">{formatDate(field.supported_since)}</td>
                    <td className="py-1.5">
                      {/* Three states, not two. "Recoverable" was a statement about
                          what was possible, which read as an instruction — and the
                          platform now does it by itself, so the column has to say
                          whether that has happened yet. */}
                      {!field.history_recoverable
                        ? t("quality.historyOnDevice")
                        : field.history_backfilled_at
                          ? t("quality.historyRecovered", {
                              date: formatDate(field.history_backfilled_at),
                            })
                          : t("quality.historyQueued")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Disclosure>
      )}

      {unsupported.length > 0 && (
        <Disclosure
          titleAs="h2"
          title={t("quality.unsupportedTitle")}
          meta={formatNumber(unsupported.length)}
          note={t("quality.unsupportedHint")}
        >
          <p className="mb-4 text-meta leading-relaxed text-ink-muted">
            {t("quality.unsupportedLifecycle")}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-meta">
              <thead>
                <tr className="border-b border-line text-ink-muted">
                  <th className="pb-2 pr-3 font-semibold">{t("quality.unsupportedField")}</th>
                  <th className="pb-2 pr-3 font-semibold">{t("quality.unsupportedKind")}</th>
                  <th className="pb-2 pr-3 text-right font-semibold">
                    {t("quality.unsupportedSeen")}
                  </th>
                  <th className="pb-2 text-right font-semibold">
                    {t("quality.unsupportedLastSeen")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line text-ink-secondary">
                {unsupported.map((field) => (
                  <tr key={field.field_path}>
                    <td className="py-2 pr-3 font-mono">{field.field_path}</td>
                    <td className="py-2 pr-3">{field.value_kind}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{field.occurrences}</td>
                    <td className="py-2 text-right">{formatDate(field.last_seen_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            type="button"
            onClick={() => void copyFieldReport()}
            className="mt-4 inline-flex min-h-11 items-center gap-1.5 rounded-2xl border border-line bg-surface px-3.5 text-meta font-semibold text-ink-secondary hover:bg-surface-muted"
          >
            {t("quality.unsupportedCopy")}
          </button>
        </Disclosure>
      )}
    </div>
  );
}
