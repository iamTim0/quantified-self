"use client";

import React, { useState, useMemo } from "react";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from "chart.js";
import { Line, Bar } from "react-chartjs-2";
import { RefreshCw, BarChart2, TrendingUp, AreaChart, Flame, Moon, Calendar, Filter } from "lucide-react";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

ChartJS.defaults.font.family = "'Outfit', 'Inter', system-ui, sans-serif";

interface TrendChartProps {
  labels: string[];
  sleepValues: number[];
  readinessValues: number[];
  calorieValues?: number[];
  proteinValues?: number[];
  carbValues?: number[];
  fatValues?: number[];
  onRefresh: () => void;
}

export default function TrendChart({
  labels,
  sleepValues,
  readinessValues,
  calorieValues = [],
  proteinValues = [],
  carbValues = [],
  fatValues = [],
  onRefresh,
}: TrendChartProps) {
  const [chartType, setChartType] = useState<"line" | "bar" | "area">("area");
  const [datasetCategory, setDatasetCategory] = useState<"nutrition" | "bio">("nutrition");

  // Date Filter State
  const [datePreset, setDatePreset] = useState<"7d" | "14d" | "30d" | "90d" | "all" | "custom">("30d");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  // Filter series data based on selected date preset or custom range
  const filtered = useMemo(() => {
    if (labels.length === 0) {
      return { labels: [], sleep: [], readiness: [], cal: [], prot: [], carb: [], fat: [] };
    }

    const total = labels.length;
    let startIndex = 0;

    if (datePreset === "7d") startIndex = Math.max(0, total - 7);
    else if (datePreset === "14d") startIndex = Math.max(0, total - 14);
    else if (datePreset === "30d") startIndex = Math.max(0, total - 30);
    else if (datePreset === "90d") startIndex = Math.max(0, total - 90);
    else if (datePreset === "custom" && (customStart || customEnd)) {
      const indices: number[] = [];
      labels.forEach((l, i) => {
        if (customStart && l < customStart) return;
        if (customEnd && l > customEnd) return;
        indices.push(i);
      });
      if (indices.length > 0) {
        return {
          labels: indices.map((i) => labels[i]),
          sleep: indices.map((i) => sleepValues[i] || 0),
          readiness: indices.map((i) => readinessValues[i] || 0),
          cal: indices.map((i) => calorieValues[i] || 0),
          prot: indices.map((i) => proteinValues[i] || 0),
          carb: indices.map((i) => carbValues[i] || 0),
          fat: indices.map((i) => fatValues[i] || 0),
        };
      }
    }

    return {
      labels: labels.slice(startIndex),
      sleep: sleepValues.slice(startIndex),
      readiness: readinessValues.slice(startIndex),
      cal: calorieValues.slice(startIndex),
      prot: proteinValues.slice(startIndex),
      carb: carbValues.slice(startIndex),
      fat: fatValues.slice(startIndex),
    };
  }, [labels, sleepValues, readinessValues, calorieValues, proteinValues, carbValues, fatValues, datePreset, customStart, customEnd]);

  const hasBioData = filtered.labels.length > 0 && (filtered.sleep.some((v) => v > 0) || filtered.readiness.some((v) => v > 0));
  const hasNutritionData = filtered.labels.length > 0 && (filtered.cal.some((v) => v > 0) || filtered.prot.some((v) => v > 0));

  const activeCategory = datasetCategory === "nutrition" && !hasNutritionData && hasBioData ? "bio" : datasetCategory;

  const nutritionChartData = {
    labels: filtered.labels,
    datasets: [
      {
        label: "Kalorien (kcal)",
        data: filtered.cal,
        borderColor: "#f59e0b",
        backgroundColor: chartType === "area" ? "rgba(245, 158, 11, 0.25)" : "rgba(245, 158, 11, 0.7)",
        borderWidth: 2,
        tension: 0.3,
        fill: chartType === "area",
        pointRadius: 3,
        pointHoverRadius: 6,
        yAxisID: "yKcal",
      },
      {
        label: "Protein (g)",
        data: filtered.prot,
        borderColor: "#3b82f6",
        backgroundColor: chartType === "area" ? "rgba(59, 130, 246, 0.15)" : "rgba(59, 130, 246, 0.7)",
        borderWidth: 2,
        tension: 0.3,
        fill: chartType === "area",
        pointRadius: 3,
        pointHoverRadius: 6,
        yAxisID: "yGrams",
      },
      {
        label: "Kohlenhydrate (g)",
        data: filtered.carb,
        borderColor: "#10b981",
        backgroundColor: chartType === "area" ? "rgba(16, 185, 129, 0.15)" : "rgba(16, 185, 129, 0.7)",
        borderWidth: 2,
        tension: 0.3,
        fill: chartType === "area",
        pointRadius: 3,
        pointHoverRadius: 6,
        yAxisID: "yGrams",
      },
      {
        label: "Fett (g)",
        data: filtered.fat,
        borderColor: "#ec4899",
        backgroundColor: chartType === "area" ? "rgba(236, 72, 153, 0.15)" : "rgba(236, 72, 153, 0.7)",
        borderWidth: 2,
        tension: 0.3,
        fill: chartType === "area",
        pointRadius: 3,
        pointHoverRadius: 6,
        yAxisID: "yGrams",
      },
    ],
  };

  const bioChartData = {
    labels: filtered.labels,
    datasets: [
      {
        label: "Sleep Score",
        data: filtered.sleep,
        borderColor: "#3b82f6",
        backgroundColor: chartType === "area" ? "rgba(59, 130, 246, 0.2)" : "rgba(59, 130, 246, 0.7)",
        borderWidth: 2,
        tension: 0.4,
        fill: chartType === "area",
        pointRadius: 4,
        yAxisID: "yScore",
      },
      {
        label: "Readiness Score",
        data: filtered.readiness,
        borderColor: "#06b6d4",
        backgroundColor: chartType === "area" ? "rgba(6, 182, 212, 0.15)" : "rgba(6, 182, 212, 0.7)",
        borderWidth: 2,
        tension: 0.4,
        fill: chartType === "area",
        pointRadius: 4,
        yAxisID: "yScore",
      },
    ],
  };

  const chartData = activeCategory === "nutrition" ? nutritionChartData : bioChartData;

  const options: any = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: "index" as const,
      intersect: false,
    },
    plugins: {
      legend: {
        position: "top" as const,
        labels: {
          color: "#e5e7eb",
          font: { family: "'Outfit', 'Inter', sans-serif", size: 12, weight: 600 },
          usePointStyle: true,
          boxWidth: 8,
        },
      },
      tooltip: {
        backgroundColor: "rgba(10, 10, 15, 0.95)",
        borderColor: "rgba(255, 255, 255, 0.15)",
        borderWidth: 1,
        titleColor: "#ffffff",
        titleFont: { family: "'Outfit', sans-serif", size: 13, weight: 700 },
        bodyColor: "#d1d5db",
        bodyFont: { family: "'JetBrains Mono', monospace", size: 12 },
        padding: 12,
        cornerRadius: 12,
      },
    },
    scales: {
      x: {
        ticks: {
          color: "#9ca3af",
          font: { family: "'JetBrains Mono', monospace", size: 10, weight: 500 },
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 12,
        },
        grid: { color: "rgba(255, 255, 255, 0.05)" },
      },
      ...(activeCategory === "nutrition"
        ? {
            yKcal: {
              type: "linear" as const,
              display: true,
              position: "left" as const,
              title: { display: true, text: "Kalorien (kcal)", color: "#f59e0b", font: { family: "'Outfit', sans-serif", size: 11, weight: 700 } },
              ticks: { color: "#f59e0b", font: { family: "'JetBrains Mono', monospace", size: 10, weight: 600 } },
              grid: { color: "rgba(255, 255, 255, 0.05)" },
            },
            yGrams: {
              type: "linear" as const,
              display: true,
              position: "right" as const,
              title: { display: true, text: "Makros (g)", color: "#3b82f6", font: { family: "'Outfit', sans-serif", size: 11, weight: 700 } },
              ticks: { color: "#3b82f6", font: { family: "'JetBrains Mono', monospace", size: 10, weight: 600 } },
              grid: { drawOnChartArea: false },
            },
          }
        : {
            yScore: {
              type: "linear" as const,
              display: true,
              position: "left" as const,
              min: 0,
              max: 100,
              ticks: { color: "#9ca3af", font: { family: "'JetBrains Mono', monospace", size: 10, weight: 600 } },
              grid: { color: "rgba(255, 255, 255, 0.05)" },
            },
          }),
    },
  };

  const hasCurrentData = activeCategory === "nutrition" ? hasNutritionData : hasBioData;

  return (
    <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md overflow-hidden space-y-4">
      {/* Header controls */}
      <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4 border-b border-neutral-800 pb-4">
        {/* Category Switcher (Curated: Only show when multiple data categories are present) */}
        {hasNutritionData && hasBioData && (
          <div className="flex items-center gap-2">
            <div className="flex bg-neutral-950 border border-neutral-800 rounded-xl p-1 text-xs">
              <button
                onClick={() => setDatasetCategory("nutrition")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold transition-colors ${
                  activeCategory === "nutrition"
                    ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                    : "text-neutral-400 hover:text-white"
                }`}
              >
                <Flame className="w-3.5 h-3.5" />
                <span>Yazio Ernährung</span>
              </button>
              <button
                onClick={() => setDatasetCategory("bio")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold transition-colors ${
                  activeCategory === "bio"
                    ? "bg-blue-500/20 text-blue-300 border border-blue-500/30"
                    : "text-neutral-400 hover:text-white"
                }`}
              >
                <Moon className="w-3.5 h-3.5" />
                <span>Schlaf & Bio-Scores</span>
              </button>
            </div>
          </div>
        )}

        {/* Date Range Picker Bar */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 text-xs font-semibold text-neutral-400 uppercase tracking-wider mr-1">
            <Calendar className="w-3.5 h-3.5 text-emerald-400" />
            <span>Zeitraum:</span>
          </div>

          <div className="flex bg-neutral-950 border border-neutral-800 rounded-xl p-1 text-xs">
            {[
              { id: "7d", label: "7 Tage" },
              { id: "14d", label: "14 Tage" },
              { id: "30d", label: "30 Tage" },
              { id: "90d", label: "90 Tage" },
              { id: "all", label: "Gesamt" },
              { id: "custom", label: "Datum..." },
            ].map((preset) => (
              <button
                key={preset.id}
                onClick={() => setDatePreset(preset.id as any)}
                className={`px-2.5 py-1 rounded-lg font-medium transition-colors ${
                  datePreset === preset.id
                    ? "bg-emerald-600 text-white"
                    : "text-neutral-400 hover:text-white"
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>

          {datePreset === "custom" && (
            <div className="flex items-center gap-1 text-xs">
              <input
                type="date"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                className="bg-neutral-950 border border-neutral-800 text-white rounded-lg px-2 py-1 outline-none focus:border-emerald-500 text-[11px]"
              />
              <span className="text-neutral-500">bis</span>
              <input
                type="date"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                className="bg-neutral-950 border border-neutral-800 text-white rounded-lg px-2 py-1 outline-none focus:border-emerald-500 text-[11px]"
              />
            </div>
          )}

          {/* Chart Type Selector */}
          <div className="flex bg-neutral-950 border border-neutral-800 rounded-xl p-1 text-xs ml-auto lg:ml-0">
            <button
              onClick={() => setChartType("area")}
              className={`p-1.5 rounded-lg transition-colors ${
                chartType === "area" ? "bg-purple-600 text-white" : "text-neutral-400 hover:text-white"
              }`}
              title="Flächendiagramm"
            >
              <AreaChart className="w-4 h-4" />
            </button>
            <button
              onClick={() => setChartType("line")}
              className={`p-1.5 rounded-lg transition-colors ${
                chartType === "line" ? "bg-purple-600 text-white" : "text-neutral-400 hover:text-white"
              }`}
              title="Liniendiagramm"
            >
              <TrendingUp className="w-4 h-4" />
            </button>
            <button
              onClick={() => setChartType("bar")}
              className={`p-1.5 rounded-lg transition-colors ${
                chartType === "bar" ? "bg-purple-600 text-white" : "text-neutral-400 hover:text-white"
              }`}
              title="Balkendiagramm"
            >
              <BarChart2 className="w-4 h-4" />
            </button>
          </div>

          <button
            onClick={onRefresh}
            className="p-2 text-xs font-semibold rounded-xl bg-neutral-800 hover:bg-neutral-700 text-white transition-colors"
            title="Diagramm aktualisieren"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Chart Canvas with STRICT Overflow Protection */}
      <div className="w-full relative h-[320px] sm:h-[380px] overflow-hidden">
        {hasCurrentData ? (
          chartType === "bar" ? (
            <Bar data={chartData} options={options} />
          ) : (
            <Line data={chartData} options={options} />
          )
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center text-xs text-neutral-500 space-y-2">
            <Flame className="w-8 h-8 text-neutral-700" />
            <p>Keine Datenpunkte für den ausgewählten Zeitraum vorhanden.</p>
          </div>
        )}
      </div>
    </div>
  );
}
