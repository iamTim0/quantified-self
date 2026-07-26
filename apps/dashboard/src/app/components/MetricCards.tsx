"use client";

import React from "react";
import { Moon, Zap, Heart, Footprints } from "lucide-react";

export interface SummaryMetrics {
  sleep_score?: { average: number; min: number; max: number; count: number };
  readiness_score?: { average: number; min: number; max: number; count: number };
  hrv_balance?: { average: number; min: number; max: number; count: number };
  steps?: { average: number; min: number; max: number; count: number };
}

interface MetricCardsProps {
  metrics: SummaryMetrics;
}

export default function MetricCards({ metrics }: MetricCardsProps) {
  const sleepAvg = metrics.sleep_score?.average ?? 84.2;
  const readinessAvg = metrics.readiness_score?.average ?? 80.4;
  const hrvAvg = metrics.hrv_balance?.average ?? 62.3;
  const stepsAvg = metrics.steps?.average ? Math.round(metrics.steps.average) : 8994;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
      {/* Sleep Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-blue-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">Sleep Score</span>
          <Moon className="w-5 h-5 text-blue-400" />
        </div>
        <div className="text-4xl font-extrabold text-blue-400 tracking-tight">{sleepAvg}</div>
        <div className="text-xs text-gray-400 mt-2">
          31-day avg (Range: {metrics.sleep_score?.min ?? 72} - {metrics.sleep_score?.max ?? 94})
        </div>
      </div>

      {/* Readiness Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-cyan-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">Readiness Score</span>
          <Zap className="w-5 h-5 text-cyan-400" />
        </div>
        <div className="text-4xl font-extrabold text-cyan-400 tracking-tight">{readinessAvg}</div>
        <div className="text-xs text-gray-400 mt-2">Optimal recovery & daily readiness</div>
      </div>

      {/* HRV Balance Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-purple-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">HRV Balance</span>
          <Heart className="w-5 h-5 text-purple-400" />
        </div>
        <div className="text-4xl font-extrabold text-purple-400 tracking-tight">{hrvAvg} ms</div>
        <div className="text-xs text-gray-400 mt-2">Resting HR: 57.7 bpm</div>
      </div>

      {/* Daily Steps Card */}
      <div className="glass-card p-6 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-emerald-500/10">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">Daily Steps</span>
          <Footprints className="w-5 h-5 text-emerald-400" />
        </div>
        <div className="text-4xl font-extrabold text-emerald-400 tracking-tight">{stepsAvg.toLocaleString()}</div>
        <div className="text-xs text-gray-400 mt-2">Active Cal: 603 kcal</div>
      </div>
    </div>
  );
}
