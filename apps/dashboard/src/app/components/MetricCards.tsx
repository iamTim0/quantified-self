"use client";

import React from "react";
import { Moon, Zap, Heart, Footprints } from "lucide-react";

export interface MetricSummaryDetail {
  average: number;
  min: number;
  max: number;
  count: number;
}

export interface SummaryMetrics {
  sleep_score?: MetricSummaryDetail;
  readiness_score?: MetricSummaryDetail;
  hrv_balance?: MetricSummaryDetail;
  steps?: MetricSummaryDetail;
  calories?: MetricSummaryDetail;
  protein?: MetricSummaryDetail;
  carbohydrates?: MetricSummaryDetail;
  fat?: MetricSummaryDetail;
  activity_score?: MetricSummaryDetail;
  resting_hr?: MetricSummaryDetail;
}

interface MetricCardsProps {
  metrics: SummaryMetrics;
}

export default function MetricCards({ metrics }: MetricCardsProps) {
  const sleep = metrics.sleep_score;
  const readiness = metrics.readiness_score;
  const hrv = metrics.hrv_balance;
  const steps = metrics.steps;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
      {/* Sleep Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-blue-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400">Sleep Score</span>
          <Moon className="w-5 h-5 text-blue-400" />
        </div>
        <div className="text-4xl font-extrabold text-blue-400 tracking-tight">
          {sleep?.average != null ? Math.round(sleep.average) : "—"}
        </div>
        <div className="text-xs text-neutral-400 mt-2">
          {sleep ? `Range: ${Math.round(sleep.min)} - ${Math.round(sleep.max)}` : "No sleep data logged"}
        </div>
      </div>

      {/* Readiness Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-cyan-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400">Readiness Score</span>
          <Zap className="w-5 h-5 text-cyan-400" />
        </div>
        <div className="text-4xl font-extrabold text-cyan-400 tracking-tight">
          {readiness?.average != null ? Math.round(readiness.average) : "—"}
        </div>
        <div className="text-xs text-neutral-400 mt-2">
          {readiness ? `Range: ${Math.round(readiness.min)} - ${Math.round(readiness.max)}` : "No readiness data logged"}
        </div>
      </div>

      {/* HRV Balance Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-purple-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400">HRV Balance</span>
          <Heart className="w-5 h-5 text-purple-400" />
        </div>
        <div className="text-4xl font-extrabold text-purple-400 tracking-tight">
          {hrv?.average != null ? `${Math.round(hrv.average)} ms` : "—"}
        </div>
        <div className="text-xs text-neutral-400 mt-2">
          {metrics.resting_hr?.average != null
            ? `Resting HR: ${Math.round(metrics.resting_hr.average)} bpm`
            : "No HRV data logged"}
        </div>
      </div>

      {/* Daily Steps Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-emerald-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400">Daily Steps</span>
          <Footprints className="w-5 h-5 text-emerald-400" />
        </div>
        <div className="text-4xl font-extrabold text-emerald-400 tracking-tight">
          {steps?.average != null ? Math.round(steps.average).toLocaleString() : "—"}
        </div>
        <div className="text-xs text-neutral-400 mt-2">
          {metrics.calories?.average != null
            ? `Calories: ${Math.round(metrics.calories.average)} kcal`
            : "No step data logged"}
        </div>
      </div>
    </div>
  );
}
