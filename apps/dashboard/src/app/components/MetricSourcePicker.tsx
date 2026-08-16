"use client";

import { useCallback, useEffect, useState } from "react";
import { GitMerge, RefreshCw } from "lucide-react";
import { apiFetch } from "../lib/api";
import { useI18n } from "../lib/i18n/provider";
import { describeMetric } from "../lib/metrics/catalog";

/**
 * Which connector answers for a metric that several of them report.
 *
 * These metrics used to be dropped from every analysis. That was the safe half
 * of a correct observation — two step counters must not be added, because the
 * same walk would be counted twice (AGENTS.md rule 19), and averaging two
 * overlapping sensors reweights the samples without the reader being able to
 * tell. But "do not merge" does not imply "do not answer": one connector
 * answers, and this is where you say which.
 *
 * Only ambiguous metrics appear. A metric with a single source needs no
 * decision, and offering one would invite a preference that can never matter.
 */

type SourceOption = {
  source_id: string;
  source_type: string | null;
  sample_count: number;
};

type AmbiguousMetric = {
  metric_type: string;
  primary_source_id: string;
  /** `preference` or `coverage` — a stable identifier, not prose (rule 17). */
  primary_reason: string;
  sources: SourceOption[];
};

export default function MetricSourcePicker({ apiBase }: { apiBase: string }) {
  const { t, formatNumber, locale } = useI18n();
  const [metrics, setMetrics] = useState<AmbiguousMetric[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const load = useCallback(async () => {
    const response = await apiFetch(`${apiBase}/api/v1/data/metrics/source-preferences`);
    if (response.ok) setMetrics(((await response.json()).metrics ?? []) as AmbiguousMetric[]);
    setLoading(false);
  }, [apiBase]);

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

  const choose = useCallback(
    async (metricType: string, sourceId: string) => {
      setSaving(metricType);
      setFailed(null);
      try {
        const url = `${apiBase}/api/v1/data/metrics/source-preferences/${encodeURIComponent(metricType)}`;
        // An empty choice means "decide by coverage again", which is a deletion
        // rather than a preference naming no connector.
        const response = await apiFetch(url, {
          method: sourceId ? "PUT" : "DELETE",
          headers: sourceId ? { "Content-Type": "application/json" } : undefined,
          body: sourceId ? JSON.stringify({ primary_source_id: sourceId }) : undefined,
        });
        // Checked, because reloading after a rejected write silently redraws the
        // old value — the reader sees their choice revert with no explanation
        // and no reason to believe it did not save.
        if (!response.ok) setFailed(metricType);
        await load();
      } catch {
        setFailed(metricType);
      } finally {
        setSaving(null);
      }
    },
    [apiBase, load],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
      </div>
    );
  }

  return (
    <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
      <div className="flex items-start gap-3">
        <GitMerge className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700" aria-hidden="true" />
        <div>
          <h2 className="text-sm font-bold text-slate-900">{t("sources.title")}</h2>
          <p className="mt-1 text-xs text-slate-500">{t("sources.intro")}</p>
        </div>
      </div>

      {metrics.length === 0 ? (
        <p className="text-sm text-slate-400">{t("sources.none")}</p>
      ) : (
        <ul className="space-y-3">
          {metrics.map((metric) => (
            <li
              key={metric.metric_type}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-100 bg-slate-50 px-3 py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-800">
                  {/*
                    From the generated catalogue, not from the server's
                    `definition`: that carries `label_en`/`label_de`, so reading
                    `.label` off it silently fell through to the raw key and the
                    card listed `steps` rather than "Steps". `describeMetric`
                    also handles a name the registry does not know, which the
                    server's payload leaves as null.
                  */}
                  {describeMetric(metric.metric_type, locale).label}
                </p>
                <p className="text-xs text-slate-500">
                  {failed === metric.metric_type
                    ? t("sources.saveFailed")
                    : metric.primary_reason === "preference"
                      ? t("analysis.primaryByPreference")
                      : t("analysis.primaryByCoverage")}
                </p>
              </div>
              <select
                // The empty value is "automatic", which is the absence of a
                // stored preference rather than a third kind of choice.
                value={metric.primary_reason === "preference" ? metric.primary_source_id : ""}
                aria-label={t("analysis.chooseSource")}
                disabled={saving === metric.metric_type}
                onChange={(event) => void choose(metric.metric_type, event.target.value)}
                className="max-w-64 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 outline-none disabled:opacity-50"
              >
                <option value="">{t("sources.automatic")}</option>
                {metric.sources.map((source) => (
                  <option key={source.source_id} value={source.source_id}>
                    {source.source_type ?? source.source_id} ·{" "}
                    {t("sources.samples", { count: formatNumber(source.sample_count) })}
                  </option>
                ))}
              </select>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
