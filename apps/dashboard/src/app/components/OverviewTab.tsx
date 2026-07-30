"use client";

import React from "react";
import MetricCards, { SummaryMetrics } from "./MetricCards";
import TrendChart from "./TrendChart";
import { RefreshCw } from "lucide-react";

interface OverviewTabProps {
  summary: SummaryMetrics;
  chartLabels: string[];
  sleepValues: number[];
  readinessValues: number[];
  calorieValues?: number[];
  proteinValues?: number[];
  carbValues?: number[];
  fatValues?: number[];
  onRefresh: () => void;
  onNavigateToConnectors: () => void;
}

export default function OverviewTab({
  summary,
  chartLabels,
  sleepValues,
  readinessValues,
  calorieValues = [],
  proteinValues = [],
  carbValues = [],
  fatValues = [],
  onRefresh,
  onNavigateToConnectors,
}: OverviewTabProps) {
  const hasData = Object.keys(summary).length > 0 || chartLabels.length > 0;

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-xl font-bold text-white">Health & Nutrition Overview</h2>
          <p className="text-xs text-neutral-400">Live-Analyse deiner verbundenen Sensoren und Ernährungs-Tracker</p>
        </div>
        <button
          onClick={onRefresh}
          className="flex items-center gap-2 text-xs font-medium text-neutral-300 hover:text-white transition-colors bg-neutral-900/80 border border-neutral-800 px-3 py-2 rounded-xl backdrop-blur-md"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Refresh</span>
        </button>
      </div>

      <MetricCards metrics={summary} />

      {hasData ? (
        <div className="mt-8">
          <TrendChart
            labels={chartLabels}
            sleepValues={sleepValues}
            readinessValues={readinessValues}
            calorieValues={calorieValues}
            proteinValues={proteinValues}
            carbValues={carbValues}
            fatValues={fatValues}
            onRefresh={onRefresh}
          />
        </div>
      ) : (
        <div className="mt-8 rounded-2xl border border-neutral-800 bg-neutral-900/50 p-8 text-center backdrop-blur-md">
          <p className="text-sm text-neutral-400 mb-4">Noch keine Gesundheits- oder Ernährungsdaten vorhanden.</p>
          <button
            onClick={onNavigateToConnectors}
            className="px-4 py-2 text-xs font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition-colors"
          >
            Connectoren verknüpfen & Daten importieren
          </button>
        </div>
      )}
    </div>
  );
}
