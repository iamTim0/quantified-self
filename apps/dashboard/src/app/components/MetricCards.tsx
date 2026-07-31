"use client";

import React from "react";
import { Flame, Dumbbell, Wheat, Droplets, Moon, Footprints, Activity, Heart, Activity as Pulse } from "lucide-react";

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
  colorClass: string;
  borderClass: string;
  textClass: string;
}

const CARD_CONFIGS: CardConfig[] = [
  {
    keys: ["calories", "consumed_item_calories"],
    title: "Ø Kalorien",
    unit: "kcal",
    icon: Flame,
    colorClass: "hover:shadow-orange-500/10",
    borderClass: "border-orange-500/20",
    textClass: "text-orange-400",
  },
  {
    keys: ["protein"],
    title: "Ø Protein",
    unit: "g",
    icon: Dumbbell,
    colorClass: "hover:shadow-purple-500/10",
    borderClass: "border-purple-500/20",
    textClass: "text-purple-400",
  },
  {
    keys: ["carbohydrates", "carbs"],
    title: "Ø Kohlenhydrate",
    unit: "g",
    icon: Wheat,
    colorClass: "hover:shadow-emerald-500/10",
    borderClass: "border-emerald-500/20",
    textClass: "text-emerald-400",
  },
  {
    keys: ["fat"],
    title: "Ø Fett",
    unit: "g",
    icon: Droplets,
    colorClass: "hover:shadow-rose-500/10",
    borderClass: "border-rose-500/20",
    textClass: "text-rose-400",
  },
  {
    keys: ["sleep_score"],
    title: "Ø Schlaf-Score",
    unit: "/100",
    icon: Moon,
    colorClass: "hover:shadow-blue-500/10",
    borderClass: "border-blue-500/20",
    textClass: "text-blue-400",
  },
  {
    keys: ["readiness_score"],
    title: "Ø Readiness Score",
    unit: "/100",
    icon: Activity,
    colorClass: "hover:shadow-cyan-500/10",
    borderClass: "border-cyan-500/20",
    textClass: "text-cyan-400",
  },
  {
    keys: ["hrv_balance"],
    title: "Ø HRV Balance",
    unit: "ms",
    icon: Heart,
    colorClass: "hover:shadow-indigo-500/10",
    borderClass: "border-indigo-500/20",
    textClass: "text-indigo-400",
  },
  {
    keys: ["steps"],
    title: "Ø Schritte",
    unit: "Schritte",
    icon: Footprints,
    colorClass: "hover:shadow-amber-500/10",
    borderClass: "border-amber-500/20",
    textClass: "text-amber-400",
  },
  {
    keys: ["resting_hr"],
    title: "Ø Ruhepuls",
    unit: "bpm",
    icon: Pulse,
    colorClass: "hover:shadow-red-500/10",
    borderClass: "border-red-500/20",
    textClass: "text-red-400",
  },
];

export default function MetricCards({ metrics }: MetricCardsProps) {
  // Curate present-only metric cards
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
      {activeCards.map(({ cfg, detail }) => {
        const IconComponent = cfg.icon;
        const avgFormatted = Math.round(detail.average).toLocaleString();
        const minFormatted = Math.round(detail.min).toLocaleString();
        const maxFormatted = Math.round(detail.max).toLocaleString();

        return (
          <div
            key={cfg.title}
            className={`glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl ${cfg.colorClass}`}
          >
            <div className="flex justify-between items-center mb-4">
              <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400">{cfg.title}</span>
              <IconComponent className={`w-5 h-5 ${cfg.textClass}`} />
            </div>
            <div className={`text-4xl font-extrabold tracking-tight ${cfg.textClass}`}>
              {avgFormatted} <span className="text-xs font-normal text-neutral-400">{cfg.unit}</span>
            </div>
            <div className="text-xs text-neutral-400 mt-2">
              Spanne: {minFormatted} - {maxFormatted} {cfg.unit}
            </div>
          </div>
        );
      })}
    </div>
  );
}
