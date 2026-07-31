"use client";

import React from "react";
import { Flame, Dumbbell, Wheat, Droplets, Moon, Footprints, Activity, Heart, ArrowUpRight, MapPin } from "lucide-react";

export interface MetricSummaryDetail {
  average: number;
  min: number;
  max: number;
  count: number;
}

export interface SummaryMetrics {
  calories?: MetricSummaryDetail;
  consumed_item_calories?: MetricSummaryDetail;
  protein?: MetricSummaryDetail;
  carbohydrates?: MetricSummaryDetail;
  fat?: MetricSummaryDetail;
  fiber?: MetricSummaryDetail;
  sleep_score?: MetricSummaryDetail;
  readiness_score?: MetricSummaryDetail;
  hrv_balance?: MetricSummaryDetail;
  steps?: MetricSummaryDetail;
  activity_score?: MetricSummaryDetail;
  resting_hr?: MetricSummaryDetail;
  location_point?: MetricSummaryDetail;
  location_latitude?: MetricSummaryDetail;
  [key: string]: MetricSummaryDetail | undefined;
}

interface MetricCardsProps {
  metrics: SummaryMetrics;
}

interface CardConfig {
  keys: string[];
  title: string;
  unit: string;
  icon: React.ElementType;
}

const CARD_CONFIGS: CardConfig[] = [
  {
    keys: ["calories", "consumed_item_calories"],
    title: "Ø Kalorien",
    unit: "kcal",
    icon: Flame,
  },
  {
    keys: ["protein"],
    title: "Ø Protein",
    unit: "g",
    icon: Dumbbell,
  },
  {
    keys: ["carbohydrates", "carbs"],
    title: "Ø Kohlenhydrate",
    unit: "g",
    icon: Wheat,
  },
  {
    keys: ["fat"],
    title: "Ø Fett",
    unit: "g",
    icon: Droplets,
  },
  {
    keys: ["location_point", "location_latitude"],
    title: "Standorte / GPS",
    unit: "Punkte",
    icon: MapPin,
  },
  {
    keys: ["sleep_score"],
    title: "Ø Schlaf-Score",
    unit: "/100",
    icon: Moon,
  },
  {
    keys: ["readiness_score"],
    title: "Ø Readiness",
    unit: "/100",
    icon: Activity,
  },
  {
    keys: ["steps"],
    title: "Ø Schritte",
    unit: "Schritte",
    icon: Footprints,
  },
];

export default function MetricCards({ metrics }: MetricCardsProps) {
  // Curate active cards
  const activeCards = CARD_CONFIGS.map((cfg) => {
    let detail: MetricSummaryDetail | undefined = undefined;
    for (const key of cfg.keys) {
      if (metrics[key] && metrics[key]?.average != null && (metrics[key]?.count || 0) > 0) {
        detail = metrics[key];
        break;
      }
    }
    if (!detail) return null;
    return { cfg, detail };
  }).filter(Boolean) as { cfg: CardConfig; detail: MetricSummaryDetail }[];

  if (activeCards.length === 0) {
    return null;
  }

  return (
    <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-${Math.min(activeCards.length, 4)} gap-6 mb-8`}>
      {activeCards.map(({ cfg, detail }, index) => {
        const isFirst = index === 0;
        const avgFormatted = Math.round(detail.average).toLocaleString("de-DE");
        const minFormatted = Math.round(detail.min).toLocaleString("de-DE");
        const maxFormatted = Math.round(detail.max).toLocaleString("de-DE");

        if (isFirst) {
          // Card 1: Highlighted Solid Emerald Green
          return (
            <div
              key={cfg.title}
              className="dark-emerald-card p-6 relative overflow-hidden transition-all hover:-translate-y-1 hover:shadow-2xl"
            >
              <div className="flex justify-between items-start mb-4">
                <span className="text-xs font-bold uppercase tracking-wider text-emerald-100/90">
                  {cfg.title}
                </span>
                <div className="w-8 h-8 rounded-full bg-white/10 border border-white/20 flex items-center justify-center text-white backdrop-blur-sm">
                  <ArrowUpRight className="w-4 h-4" />
                </div>
              </div>
              <div className="text-4xl font-extrabold text-white tracking-tight mb-3">
                {avgFormatted} <span className="text-xs font-medium text-emerald-200">{cfg.unit}</span>
              </div>
              <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/20 border border-emerald-400/30 text-[11px] font-semibold text-emerald-100">
                <span>Spanne: {minFormatted} - {maxFormatted} {cfg.unit}</span>
              </div>
            </div>
          );
        }

        // Cards 2, 3, 4: Pure White Card
        return (
          <div
            key={cfg.title}
            className="glass-card p-6 relative transition-all hover:-translate-y-1 hover:shadow-xl border border-slate-200/80"
          >
            <div className="flex justify-between items-start mb-4">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                {cfg.title}
              </span>
              <div className="w-8 h-8 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-700 hover:bg-slate-200 transition-colors">
                <ArrowUpRight className="w-4 h-4" />
              </div>
            </div>
            <div className="text-4xl font-extrabold text-slate-900 tracking-tight mb-3">
              {avgFormatted} <span className="text-xs font-normal text-slate-500">{cfg.unit}</span>
            </div>
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600">
              <span>Spanne: {minFormatted} - {maxFormatted} {cfg.unit}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
