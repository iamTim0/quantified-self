"use client";

import React from "react";
import { Flame, Dumbbell, Wheat, Droplets, Moon, Footprints } from "lucide-react";

export interface MetricSummaryDetail {
  average: number;
  min: number;
  max: number;
  count: number;
}

export interface SummaryMetrics {
  calories?: MetricSummaryDetail;
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
}

interface MetricCardsProps {
  metrics: SummaryMetrics;
}

export default function MetricCards({ metrics }: MetricCardsProps) {
  const calories = metrics.calories;
  const protein = metrics.protein;
  const carbs = metrics.carbohydrates;
  const fat = metrics.fat;
  const sleep = metrics.sleep_score;
  const steps = metrics.steps;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
      {/* Calories Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-orange-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400">Ø Kalorien</span>
          <Flame className="w-5 h-5 text-orange-400" />
        </div>
        <div className="text-4xl font-extrabold text-orange-400 tracking-tight">
          {calories?.average != null ? `${Math.round(calories.average)} kcal` : sleep?.average != null ? Math.round(sleep.average) : "—"}
        </div>
        <div className="text-xs text-neutral-400 mt-2">
          {calories ? `Spanne: ${Math.round(calories.min)} - ${Math.round(calories.max)} kcal` : "Keine Kaloriendaten"}
        </div>
      </div>

      {/* Protein Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-purple-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400">Ø Protein</span>
          <Dumbbell className="w-5 h-5 text-purple-400" />
        </div>
        <div className="text-4xl font-extrabold text-purple-400 tracking-tight">
          {protein?.average != null ? `${Math.round(protein.average)} g` : "—"}
        </div>
        <div className="text-xs text-neutral-400 mt-2">
          {protein ? `Spanne: ${Math.round(protein.min)} - ${Math.round(protein.max)} g` : "Keine Eiweißdaten"}
        </div>
      </div>

      {/* Carbohydrates Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-emerald-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400">Ø Kohlenhydrate</span>
          <Wheat className="w-5 h-5 text-emerald-400" />
        </div>
        <div className="text-4xl font-extrabold text-emerald-400 tracking-tight">
          {carbs?.average != null ? `${Math.round(carbs.average)} g` : "—"}
        </div>
        <div className="text-xs text-neutral-400 mt-2">
          {carbs ? `Spanne: ${Math.round(carbs.min)} - ${Math.round(carbs.max)} g` : "Keine Kohlenhydratdaten"}
        </div>
      </div>

      {/* Fat Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-rose-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400">Ø Fett</span>
          <Droplets className="w-5 h-5 text-rose-400" />
        </div>
        <div className="text-4xl font-extrabold text-rose-400 tracking-tight">
          {fat?.average != null ? `${Math.round(fat.average)} g` : steps?.average != null ? Math.round(steps.average).toLocaleString() : "—"}
        </div>
        <div className="text-xs text-neutral-400 mt-2">
          {fat ? `Spanne: ${Math.round(fat.min)} - ${Math.round(fat.max)} g` : "Keine Fettdaten"}
        </div>
      </div>
    </div>
  );
}
