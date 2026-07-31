"use client";

import React from "react";
import dynamic from "next/dynamic";
import MetricCards, { SummaryMetrics } from "./MetricCards";
import { RefreshCw, Calendar } from "lucide-react";

const TrendChart = dynamic(() => import("./TrendChart"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-80 rounded-3xl border border-slate-200 bg-white p-6 flex items-center justify-center text-xs text-slate-400">
      Lade Analytics Diagramm...
    </div>
  ),
});

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

  const todayFormatted = new Date().toLocaleDateString("de-DE", {
    weekday: "long",
    day: "2-digit",
    month: "long",
    year: "numeric",
  });

  return (
    <div className="space-y-6">
      {/* Hero Title & Actions Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-2">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Dashboard</h1>
          <p className="text-xs text-slate-500 mt-1">
            Aggregierte Echtzeit-Analysen deiner verbundenen Sensoren und Ernährungs-Tracker.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-800 bg-emerald-50 border border-emerald-200/80 px-3 py-2 rounded-2xl">
            <Calendar className="w-3.5 h-3.5 text-[#0d5c3a]" />
            <span>{todayFormatted}</span>
          </span>
          <button
            onClick={onRefresh}
            className="flex items-center gap-2 text-xs font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 px-3.5 py-2 rounded-2xl shadow-sm transition-all"
          >
            <RefreshCw className="w-3.5 h-3.5 text-slate-500" />
            <span>Aktualisieren</span>
          </button>
        </div>
      </div>

      {/* Dynamic Curated Metric Stat Cards (Renders only metrics with present data) */}
      <MetricCards metrics={summary} />

      {/* Main Analytics Trend Chart */}
      <div>
        {hasData ? (
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
        ) : (
          <div className="glass-card p-10 text-center bg-white border border-slate-200 rounded-3xl">
            <p className="text-sm font-medium text-slate-500 mb-4">Noch keine Datenpunkte in PostgreSQL vorhanden.</p>
            <button
              onClick={onNavigateToConnectors}
              className="px-5 py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all shadow-md shadow-[#0d5c3a]/20"
            >
              Connectoren verknüpfen & Daten importieren
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
