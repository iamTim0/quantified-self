"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";

import { apiFetch } from "../lib/api";
import { useI18n, type MessageKey } from "../lib/i18n/provider";

/**
 * A connector whose quarantine is filling up, or has stopped accepting values.
 *
 * This lived on `/quality`, which on a phone is behind "More" — so the one
 * notice in the product that means *data is being thrown away right now* was
 * two taps and a scroll from anybody. It is the same class of news as the
 * configuration problems `SystemWarnings` carries, so it sits beside them: on
 * every page, above the content, unmissable.
 *
 * Only the states that are actually urgent are shown here. "Half full" and
 * "has pending" are for the connector's own page — a banner on every screen
 * that says nothing is happening yet is a banner people learn to skip, and then
 * they skip the one that matters.
 */

type QuarantineCapacity = {
  source_id: string;
  source_type: string;
  connector_name: string;
  warning_code: string;
  usage_percent: number;
  active_rows: number;
  max_rows: number;
  active_names: number;
  max_names: number;
  refused_occurrences: number;
};

/**
 * The codes worth interrupting a reader for, how loudly, and what each says.
 *
 * A `Record` rather than a `switch` with a default, so a code this build does
 * not know simply does not render — silence is the right failure here, since the
 * alternative is a banner on every screen whose text nobody chose.
 */
const URGENT: Record<string, { severity: "danger" | "warn"; key: MessageKey }> = {
  quarantine_values_refused: {
    severity: "danger",
    key: "quality.quarantineCapacityRefused",
  },
  quarantine_full: { severity: "danger", key: "quality.quarantineCapacityFull" },
  quarantine_near_full: { severity: "warn", key: "quality.quarantineCapacityNearFull" },
};

export default function QuarantineAlerts({ apiBase }: { apiBase: string }) {
  const { t, formatNumber } = useI18n();
  const [capacity, setCapacity] = useState<QuarantineCapacity[]>([]);

  const load = useCallback(async () => {
    try {
      const response = await apiFetch(`${apiBase}/api/v1/data/quality/quarantine`);
      if (!response.ok) return;
      const data = await response.json();
      setCapacity(data.capacity ?? []);
    } catch {
      // A banner that fails to load is silent rather than noisy: the connector's
      // own page still reports the same state in full.
    }
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

  const urgent = capacity.filter((entry) => entry.warning_code in URGENT);
  if (urgent.length === 0) return null;

  return (
    <section aria-label={t("quality.quarantineTitle")} className="mb-6 space-y-2">
      {urgent.map((entry) => {
        const { severity, key } = URGENT[entry.warning_code];
        const tone =
          severity === "danger"
            ? "border-danger-line bg-danger-soft text-danger-ink-on-soft"
            : "border-warn-line bg-warn-soft text-warn-ink";
        return (
          <div
            key={entry.source_id}
            role={severity === "danger" ? "alert" : undefined}
            className={`flex gap-3 rounded-2xl border p-4 ${tone}`}
          >
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
            <div className="min-w-0">
              <p className="text-body font-bold">
                {entry.connector_name || entry.source_type}
              </p>
              <p className="mt-1 text-meta leading-relaxed">
                {t(key, {
                  percent: formatNumber(entry.usage_percent),
                  rows: formatNumber(entry.active_rows),
                  maxRows: formatNumber(entry.max_rows),
                  names: formatNumber(entry.active_names),
                  maxNames: formatNumber(entry.max_names),
                  refused: formatNumber(entry.refused_occurrences),
                })}
              </p>
            </div>
          </div>
        );
      })}
    </section>
  );
}
