"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  CalendarX2,
  Lightbulb,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import ImportDialog from "./ImportDialog";
import { plural, useI18n, type Translate } from "../lib/i18n/provider";
import { apiFetch } from "../lib/api";

// tenantId is no longer read: Core derives the tenant from the session credential, so the
// prop is kept only for call-site compatibility with the other tabs.
type Props = { apiBase: string; tenantId?: string };
type Gap = { metric_type: string; missing_dates: string[] };
type Connector = { source_type: string; lookback_days: number };

/**
 * An interruption in a metric sampled faster than daily.
 *
 * Reported as spans rather than missing days: a calendar day is the wrong unit
 * for something recorded every few minutes. Without reading these, heart rate and
 * every weather series would show nothing at all once they left the daily check.
 */
type CadenceGap = {
  metric_type: string;
  missing_ranges: { start: string; end: string }[];
};

/**
 * One provider field that arrives and is not stored.
 *
 * Deliberately shape-only: a path, the kind of value that sat there, and how often
 * it was seen. There is no value field, and there is not meant to be one — keeping
 * payloads would mean a second copy of the most sensitive data in the system.
 */
type UnsupportedField = {
  source_id: string;
  source_type: string;
  connector_name: string;
  field_path: string;
  value_kind: string;
  occurrences: number;
  last_seen_at: string | null;
};

/** Contiguous runs of missing days, so "12 Tage" becomes a usable backfill range. */
function toRanges(dates: string[]): { start: string; end: string; days: number }[] {
  const sorted = [...dates].sort();
  const ranges: { start: string; end: string; days: number }[] = [];

  for (const day of sorted) {
    const last = ranges[ranges.length - 1];
    if (last) {
      const nextExpected = new Date(`${last.end}T00:00:00Z`);
      nextExpected.setUTCDate(nextExpected.getUTCDate() + 1);
      if (nextExpected.toISOString().slice(0, 10) === day) {
        last.end = day;
        last.days += 1;
        continue;
      }
    }
    ranges.push({ start: day, end: day, days: 1 });
  }
  return ranges.sort((a, b) => b.days - a.days);
}

const gapRecommendation = (t: Translate, missingDays: number): string => {
  if (missingDays === 0) return t("quality.recommendationComplete");
  if (missingDays <= 3) return t("quality.recommendationMinor");
  return t("quality.recommendationSerious");
};

export default function DataQualityTab({ apiBase }: Props) {
  const { t, formatDate } = useI18n();
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [conflicts, setConflicts] = useState<number>(0);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [windowDays, setWindowDays] = useState(30);
  const [loading, setLoading] = useState(true);
  // Fields a connector is being given and this platform does not store. Shapes
  // only — the response carries a path and a value *kind*, never a value.
  const [unsupported, setUnsupported] = useState<UnsupportedField[]>([]);
  const [cadenceGaps, setCadenceGaps] = useState<CadenceGap[]>([]);
  const [copied, setCopied] = useState(false);
  const [backfill, setBackfill] = useState<{ sourceType: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const end = new Date();
    const start = new Date(end);
    start.setDate(end.getDate() - (windowDays - 1));
    
    try {
      const [gapRes, conflictRes, connectorRes, unsupportedRes] = await Promise.all([
        apiFetch(
          `${apiBase}/api/v1/data/quality/gaps?start_date=${start
            .toISOString()
            .slice(0, 10)}&end_date=${end.toISOString().slice(0, 10)}` +
            `&offset_minutes=${-new Date().getTimezoneOffset()}`,
        ),
        apiFetch(`${apiBase}/api/v1/data/quality/conflicts`),
        apiFetch(`${apiBase}/api/v1/data/sources`),
        apiFetch(`${apiBase}/api/v1/data/quality/unsupported-fields`),
      ]);
      if (gapRes.ok) {
        const data = await gapRes.json();
        setGaps(data.gaps ?? []);
        setCadenceGaps(data.cadence_gaps ?? []);
      }
      if (conflictRes.ok)
        setConflicts(((await conflictRes.json()).conflicts ?? []).length);
      if (connectorRes.ok)
        setConnectors((await connectorRes.json()).connectors ?? []);
      if (unsupportedRes.ok)
        setUnsupported((await unsupportedRes.json()).fields ?? []);
    } finally {
      setLoading(false);
    }
  }, [apiBase, windowDays]);

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

  /**
   * A ready-to-paste report of what is not being stored.
   *
   * Carries the provider's field names, their types and how often they were seen —
   * and deliberately nothing else. No values, no connector ids, no workspace
   * identifier: this is meant to be pasted into a public issue tracker, so it must
   * be safe to paste there without anyone having to check it first.
   */
  const copyFieldReport = async () => {
    const bySource = new Map<string, UnsupportedField[]>();
    for (const field of unsupported) {
      const list = bySource.get(field.source_type) ?? [];
      list.push(field);
      bySource.set(field.source_type, list);
    }

    const lines = ["## Unsupported provider fields", ""];
    for (const [sourceType, fields] of [...bySource].sort()) {
      lines.push(`### ${sourceType}`, "");
      lines.push("| Field | Type | Seen |", "| --- | --- | ---: |");
      for (const field of fields) {
        lines.push(`| \`${field.field_path}\` | ${field.value_kind} | ${field.occurrences} |`);
      }
      lines.push("");
    }

    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be refused; the table above is still readable.
    }
  };

  const missingTotal = gaps.reduce((sum, gap) => sum + gap.missing_dates.length, 0);
  const cards = [
    {
      title: t("quality.gapsTitle"),
      value: missingTotal,
      icon: CalendarX2,
      detail: t("quality.gapsDetail", { metrics: gaps.length, days: windowDays }),
      help: gapRecommendation(t, missingTotal),
    },
    {
      title: t("quality.conflictsTitle"),
      value: conflicts,
      icon: AlertTriangle,
      detail: t("quality.conflictsDetail"),
      help:
        conflicts === 0 ? t("quality.conflictsNone") : t("quality.conflictsHelp"),
    },
  ];

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-widest text-emerald-700">
            {t("quality.eyebrow")}
          </p>
          <h1 className="text-3xl font-extrabold text-slate-900">{t("quality.title")}</h1>
          <p className="mt-2 text-sm text-slate-500">
            {t("quality.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs font-semibold text-slate-500">
            {t("quality.window")}
            <select
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
              className="ml-2 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 outline-none"
            >
              {[7, 30, 90, 180, 365].map((days) => (
                <option key={days} value={days}>
                  {t("quality.windowDays", { count: days })}
                </option>
              ))}
            </select>
          </label>
          {loading && <RefreshCw className="h-5 w-5 animate-spin text-emerald-700" />}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {cards.map(({ title, value, icon: Icon, detail, help }) => (
          <article
            key={title}
            className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <Icon className="mb-5 h-6 w-6 text-emerald-700" />
            <p className="text-sm font-semibold text-slate-500">{title}</p>
            <p className="text-4xl font-black text-slate-900">{value}</p>
            <p className="mt-2 text-xs text-slate-400">{detail}</p>
            <p className="mt-3 rounded-2xl bg-emerald-50 p-3 text-xs font-semibold text-emerald-800">
              {help}
            </p>
          </article>
        ))}
      </div>

      <article className="rounded-3xl border border-amber-200 bg-amber-50 p-5">
        <div className="flex gap-3">
          <Lightbulb className="h-5 w-5 shrink-0 text-amber-700" />
          <div>
            <h2 className="font-bold text-slate-900">{t("quality.explainTitle")}</h2>
            <p className="mt-1 text-sm text-slate-600">
              {t("quality.explainBody")}
            </p>
            <a
              href="/docs/features/data-quality/"
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-amber-800 underline"
            >
              <BookOpen className="h-3.5 w-3.5" /> {t("quality.explainDocs")}
            </a>
          </div>
        </div>
      </article>

      {/*
        Fields this platform is being given and does not store. The question a user
        cannot otherwise ask — "is my device sending something that never arrives?"
        — and the reason four Apple Health quantities went missing for months
        without anyone being able to notice.
      */}
      {/*
        Continuous metrics report interrupted spans, not missing days. They are
        shown separately because they answer a different question — "the watch
        stopped for a week" rather than "no value on the 3rd".
      */}
      {cadenceGaps.length > 0 && (
        <article className="rounded-3xl border border-slate-200 bg-white p-6">
          <h2 className="mb-1 font-bold text-slate-900">{t("quality.interruptionsTitle")}</h2>
          <p className="mb-4 text-xs leading-relaxed text-slate-500">
            {t("quality.interruptionsHint")}
          </p>
          <ul className="space-y-2">
            {cadenceGaps.map((gap) => (
              <li key={gap.metric_type} className="rounded-2xl bg-slate-50 px-3.5 py-2.5">
                <div className="text-xs font-bold text-slate-900">{gap.metric_type}</div>
                <ul className="mt-1 space-y-0.5">
                  {gap.missing_ranges.slice(0, 5).map((range) => (
                    <li key={range.start} className="text-[11px] text-slate-600">
                      {formatDate(range.start)} – {formatDate(range.end)}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </article>
      )}

      {unsupported.length > 0 && (
        <article className="rounded-3xl border border-amber-200 bg-amber-50/60 p-6">
          <h2 className="mb-1 font-bold text-amber-900">{t("quality.unsupportedTitle")}</h2>
          <p className="mb-4 text-xs leading-relaxed text-amber-800">
            {t("quality.unsupportedHint")}
          </p>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-amber-200 text-[11px] font-bold uppercase tracking-wider text-amber-700">
                  <th className="pb-2 pr-3">{t("quality.unsupportedConnector")}</th>
                  <th className="pb-2 pr-3">{t("quality.unsupportedField")}</th>
                  <th className="pb-2 pr-3">{t("quality.unsupportedKind")}</th>
                  <th className="pb-2 pr-3 text-right">{t("quality.unsupportedSeen")}</th>
                  <th className="pb-2 text-right">{t("quality.unsupportedLastSeen")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-amber-100">
                {unsupported.map((field) => (
                  <tr key={`${field.source_id}:${field.field_path}`}>
                    <td className="py-2 pr-3 font-semibold text-amber-900">
                      {field.connector_name || field.source_type}
                    </td>
                    <td className="py-2 pr-3 font-mono text-amber-900">{field.field_path}</td>
                    <td className="py-2 pr-3 text-amber-700">{field.value_kind}</td>
                    <td className="py-2 pr-3 text-right text-amber-700">{field.occurrences}</td>
                    <td className="py-2 text-right text-amber-700">
                      {formatDate(field.last_seen_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <button
            type="button"
            onClick={() => void copyFieldReport()}
            className="mt-4 inline-flex items-center gap-1.5 rounded-2xl border border-amber-300 bg-white px-3.5 py-2 text-xs font-semibold text-amber-900 hover:bg-amber-100"
          >
            {copied ? t("quality.unsupportedCopied") : t("quality.unsupportedCopy")}
          </button>
        </article>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <article className="rounded-3xl border border-slate-200 bg-white p-6">
          <h2 className="mb-1 font-bold text-slate-900">{t("quality.largestGaps")}</h2>
          <p className="mb-4 text-xs text-slate-500">
            {t("quality.largestGapsHint")}
          </p>

          {gaps.length === 0 ? (
            <p className="text-sm text-slate-400">
              {t("quality.noGaps", { days: windowDays })}
            </p>
          ) : (
            gaps.slice(0, 6).map((gap) => {
              const ranges = toRanges(gap.missing_dates);
              return (
                <div key={gap.metric_type} className="border-b border-slate-100 py-3">
                  <div className="flex justify-between text-sm">
                    <span className="font-medium text-slate-700">{gap.metric_type}</span>
                    <span className="font-bold text-amber-600">
                      {t(
                        plural(
                          gap.missing_dates.length,
                          "common.days_one",
                          "common.days_other",
                        ),
                        { count: gap.missing_dates.length },
                      )}
                    </span>
                  </div>
                  <ul className="mt-1.5 space-y-1">
                    {ranges.slice(0, 3).map((r) => (
                      <li
                        key={`${r.start}-${r.end}`}
                        className="flex items-center justify-between rounded-lg bg-slate-50 px-2.5 py-1.5 text-[11px]"
                      >
                        <span className="font-mono text-slate-600">
                          {r.start === r.end
                            ? formatDate(`${r.start}T00:00:00Z`)
                            : `${formatDate(`${r.start}T00:00:00Z`)} – ${formatDate(
                                `${r.end}T00:00:00Z`,
                              )}`}
                        </span>
                        <span className="text-slate-400">
                          {t(plural(r.days, "common.days_one", "common.days_other"), {
                            count: r.days,
                          })}
                        </span>
                      </li>
                    ))}
                    {ranges.length > 3 && (
                      <li className="text-[11px] text-slate-400">
                        {t("quality.moreRanges", { count: ranges.length - 3 })}
                      </li>
                    )}
                  </ul>
                  <p className="mt-1.5 text-xs text-slate-500">
                    {gapRecommendation(t, gap.missing_dates.length)}
                  </p>
                </div>
              );
            })
          )}

          {gaps.length > 0 && connectors.length > 0 && (
            <div className="mt-4 border-t border-slate-100 pt-4">
              <p className="mb-2 text-xs font-semibold text-slate-600">
                {t("quality.backfillTitle")}
              </p>
              <div className="flex flex-wrap gap-2">
                {connectors.map((c) => (
                  <button
                    key={c.source_type}
                    onClick={() => setBackfill({ sourceType: c.source_type })}
                    className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[11px] font-semibold text-emerald-800 hover:bg-emerald-100"
                  >
                    {t("quality.backfillSource", { source: c.source_type })}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-slate-400">
                {t("quality.backfillHint")}
              </p>
            </div>
          )}
        </article>

        <article className="rounded-3xl border border-slate-200 bg-white p-6">
          <ShieldCheck className="mb-4 h-6 w-6 text-emerald-700" />
          <h2 className="mb-2 font-bold text-slate-900">{t("quality.conflictsTitle")}</h2>
          <p className="text-sm text-slate-500">
            {conflicts === 0
              ? t("quality.conflictsNoneLong")
              : t("quality.conflictsSome", { count: conflicts })}
          </p>
          <p className="mt-3 text-xs text-slate-500">
            {t("quality.conflictsAdvice")}
          </p>
        </article>
      </div>

      {backfill && (
        <ImportDialog
          key={backfill.sourceType}
          apiBase={apiBase}
          sourceType={backfill.sourceType}
          sourceName={backfill.sourceType}
          isOpen={true}
          onClose={() => setBackfill(null)}
          onQueued={load}
        />
      )}
    </section>
  );
}
