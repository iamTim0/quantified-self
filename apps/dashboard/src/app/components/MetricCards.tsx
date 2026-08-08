"use client";

import React from "react";

import { useI18n } from "../lib/i18n/provider";
import { METRIC_CATALOG } from "../lib/metrics/catalog";
import { Flame, Dumbbell, Wheat, Droplets, Moon, Footprints, Activity, Heart, ArrowUpRight, MapPin } from "lucide-react";

export interface MetricSummaryDetail {
  average: number;
  min: number;
  max: number;
  count: number;
}

/** Keyed by canonical metric name — see `apps/dashboard/src/app/lib/metrics/catalog.ts`. */
export interface SummaryMetrics {
  [key: string]: MetricSummaryDetail | undefined;
}

interface MetricCardsProps {
  metrics: SummaryMetrics;
}

/**
 * Which metrics get a card, and with which icon. Everything else about them — the
 * label, the unit, how many decimals — comes from the generated registry, so a card
 * cannot disagree with the data behind it.
 *
 * The old list could, and did: it looked up `sleep_score`, `readiness_score`,
 * `hrv_balance`, `resting_hr`, `steps` and `carbs`, and no importer emitted a single
 * one of those names. Four of the eight cards were permanently blank.
 */
const CARDS: { key: string; icon: React.ElementType }[] = [
  { key: "nutrition_energy", icon: Flame },
  { key: "nutrition_protein", icon: Dumbbell },
  { key: "nutrition_carbohydrates", icon: Wheat },
  { key: "nutrition_fat", icon: Droplets },
  { key: "steps", icon: Footprints },
  { key: "sleep_duration", icon: Moon },
  { key: "heart_rate_resting", icon: Heart },
  { key: "whoop_recovery_score", icon: Activity },
  { key: "location_point", icon: MapPin },
];

/** Cards shown at once. More than this and the grid stops being a summary. */
const MAX_CARDS = 4;

export default function MetricCards({ metrics }: MetricCardsProps) {
  const { t, locale, formatNumber } = useI18n();

  const activeCards = CARDS.map(({ key, icon }) => {
    const definition = METRIC_CATALOG[key];
    if (!definition) return null;

    // A tenant may still hold rows written under a name that has since become an
    // alias, so the aliases are searched too rather than the card reading empty.
    const detail = [key, ...definition.aliases]
      .map((name) => metrics[name])
      .find((d) => d != null && d.average != null && (d.count || 0) > 0);
    if (!detail) return null;

    return { definition, icon, detail };
  })
    .filter(Boolean)
    .slice(0, MAX_CARDS) as {
    definition: (typeof METRIC_CATALOG)[string];
    icon: React.ElementType;
    detail: MetricSummaryDetail;
  }[];

  if (activeCards.length === 0) {
    return null;
  }

  return (
    <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-${Math.min(activeCards.length, 4)} gap-6 mb-8`}>
      {activeCards.map(({ definition, detail }, index) => {
        const isFirst = index === 0;
        // Decimals come from the metric, not from a blanket Math.round: rounding a
        // body weight to whole kilograms hides exactly the change it is watched for.
        const format = (value: number) =>
          formatNumber(value, {
            minimumFractionDigits: 0,
            maximumFractionDigits: definition.precision,
          });
        const avgFormatted = format(detail.average);
        const minFormatted = format(detail.min);
        const maxFormatted = format(detail.max);
        const title = locale === "de" ? definition.labelDe : definition.labelEn;
        const unit = definition.unit;

        if (isFirst) {
          // Card 1: Highlighted Solid Emerald Green
          return (
            <div
              key={definition.key}
              className="dark-emerald-card p-6 relative overflow-hidden transition-all hover:-translate-y-1 hover:shadow-2xl"
            >
              <div className="flex justify-between items-start mb-4">
                <span className="text-xs font-bold uppercase tracking-wider text-emerald-100/90">
                  {title}
                </span>
                <div className="w-8 h-8 rounded-full bg-white/10 border border-white/20 flex items-center justify-center text-white backdrop-blur-sm">
                  <ArrowUpRight className="w-4 h-4" />
                </div>
              </div>
              <div className="text-4xl font-extrabold text-white tracking-tight mb-3">
                {avgFormatted} <span className="text-xs font-medium text-emerald-200">{unit}</span>
              </div>
              <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/20 border border-emerald-400/30 text-[11px] font-semibold text-emerald-100">
                <span>{t("cards.range", { min: minFormatted, max: maxFormatted, unit })}</span>
              </div>
            </div>
          );
        }

        // Cards 2, 3, 4: Pure White Card
        return (
          <div
            key={definition.key}
            className="glass-card p-6 relative transition-all hover:-translate-y-1 hover:shadow-xl border border-slate-200/80"
          >
            <div className="flex justify-between items-start mb-4">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                {title}
              </span>
              <div className="w-8 h-8 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-700 hover:bg-slate-200 transition-colors">
                <ArrowUpRight className="w-4 h-4" />
              </div>
            </div>
            <div className="text-4xl font-extrabold text-slate-900 tracking-tight mb-3">
              {avgFormatted} <span className="text-xs font-normal text-slate-500">{unit}</span>
            </div>
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600">
              <span>{t("cards.range", { min: minFormatted, max: maxFormatted, unit })}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
