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

import { useT } from "../lib/i18n/provider";

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

ChartJS.defaults.font.family = "var(--font-outfit), 'Outfit', system-ui, sans-serif";

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
  const t = useT();
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
        label: t("chart.calories"),
        data: filtered.cal,
        borderColor: "#0d5c3a",
        backgroundColor: chartType === "area" ? "rgba(13, 92, 58, 0.15)" : "rgba(13, 92, 58, 0.8)",
        borderWidth: 2.5,
        tension: 0.3,
        fill: chartType === "area",
        pointRadius: 3,
        pointHoverRadius: 6,
        yAxisID: "yKcal",
      },
      {
        label: t("chart.protein"),
        data: filtered.prot,
        borderColor: "#10b981",
        backgroundColor: chartType === "area" ? "rgba(16, 185, 129, 0.12)" : "rgba(16, 185, 129, 0.8)",
        borderWidth: 2,
        tension: 0.3,
        fill: chartType === "area",
        pointRadius: 3,
        pointHoverRadius: 6,
        yAxisID: "yGrams",
      },
      {
        label: t("chart.carbs"),
        data: filtered.carb,
        borderColor: "#f59e0b",
        backgroundColor: chartType === "area" ? "rgba(245, 158, 11, 0.12)" : "rgba(245, 158, 11, 0.8)",
        borderWidth: 2,
        tension: 0.3,
        fill: chartType === "area",
        pointRadius: 3,
        pointHoverRadius: 6,
        yAxisID: "yGrams",
      },
      {
        label: t("chart.fat"),
        data: filtered.fat,
        borderColor: "#06b6d4",
        backgroundColor: chartType === "area" ? "rgba(6, 182, 212, 0.12)" : "rgba(6, 182, 212, 0.8)",
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
        label: t("chart.sleepScore"),
        data: filtered.sleep,
        borderColor: "#0d5c3a",
        backgroundColor: chartType === "area" ? "rgba(13, 92, 58, 0.15)" : "rgba(13, 92, 58, 0.8)",
        borderWidth: 2.5,
        tension: 0.4,
        fill: chartType === "area",
        pointRadius: 4,
        yAxisID: "yScore",
      },
      {
        label: t("chart.readinessScore"),
        data: filtered.readiness,
        borderColor: "#10b981",
        backgroundColor: chartType === "area" ? "rgba(16, 185, 129, 0.15)" : "rgba(16, 185, 129, 0.8)",
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
          color: "#334155",
          font: { family: "var(--font-outfit), 'Outfit', sans-serif", size: 12, weight: 600 },
          usePointStyle: true,
          boxWidth: 8,
        },
      },
      tooltip: {
        backgroundColor: "#0f172a",
        borderColor: "#334155",
        borderWidth: 1,
        titleColor: "#ffffff",
        titleFont: { family: "var(--font-outfit), sans-serif", size: 13, weight: 700 },
        bodyColor: "#cbd5e1",
        bodyFont: { family: "var(--font-jetbrains-mono), monospace", size: 12 },
        padding: 12,
        cornerRadius: 12,
      },
    },
    scales: {
      x: {
        ticks: {
          color: "#64748b",
          font: { family: "var(--font-jetbrains-mono), monospace", size: 10, weight: 500 },
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 12,
        },
        grid: { color: "#f1f5f9" },
      },
      ...(activeCategory === "nutrition"
        ? {
            yKcal: {
              type: "linear" as const,
              display: true,
              position: "left" as const,
              title: { display: true, text: "Kalorien (kcal)", color: "#0d5c3a", font: { family: "var(--font-outfit), sans-serif", size: 11, weight: 700 } },
              ticks: { color: "#0d5c3a", font: { family: "var(--font-jetbrains-mono), monospace", size: 10, weight: 600 } },
              grid: { color: "#f1f5f9" },
            },
            yGrams: {
              type: "linear" as const,
              display: true,
              position: "right" as const,
              title: { display: true, text: "Makros (g)", color: "#10b981", font: { family: "var(--font-outfit), sans-serif", size: 11, weight: 700 } },
              ticks: { color: "#10b981", font: { family: "var(--font-jetbrains-mono), monospace", size: 10, weight: 600 } },
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
              ticks: { color: "#64748b", font: { family: "var(--font-jetbrains-mono), monospace", size: 10, weight: 600 } },
              grid: { color: "#f1f5f9" },
            },
          }),
    },
  };

  const hasCurrentData = activeCategory === "nutrition" ? hasNutritionData : hasBioData;

  return (
    <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-4">
      {/* Header controls */}
      <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4 border-b border-slate-100 pb-4">
        {/* Category Switcher */}
        {hasNutritionData && hasBioData && (
          <div className="flex items-center gap-2">
            <div className="flex bg-slate-100 border border-slate-200 rounded-2xl p-1 text-xs">
              <button
                onClick={() => setDatasetCategory("nutrition")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-semibold transition-all ${
                  activeCategory === "nutrition"
                    ? "bg-[#0d5c3a] text-white shadow-sm"
                    : "text-slate-500 hover:text-slate-900"
                }`}
              >
                <Flame className="w-3.5 h-3.5" />
                <span>{t("chart.categoryNutrition")}</span>
              </button>
              <button
                onClick={() => setDatasetCategory("bio")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-semibold transition-all ${
                  activeCategory === "bio"
                    ? "bg-[#0d5c3a] text-white shadow-sm"
                    : "text-slate-500 hover:text-slate-900"
                }`}
              >
                <Moon className="w-3.5 h-3.5" />
                <span>{t("chart.categoryBio")}</span>
              </button>
            </div>
          </div>
        )}

        {/* Date Range Picker Bar */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 text-xs font-bold text-slate-400 uppercase tracking-wider mr-1">
            <Calendar className="w-3.5 h-3.5 text-[#0d5c3a]" />
            <span>{t("chart.period")}</span>
          </div>

          <div className="flex bg-slate-100 border border-slate-200 rounded-2xl p-1 text-xs">
            {[
              { id: "7d", label: t("quality.windowDays", { count: 7 }) },
              { id: "14d", label: t("quality.windowDays", { count: 14 }) },
              { id: "30d", label: t("quality.windowDays", { count: 30 }) },
              { id: "90d", label: t("quality.windowDays", { count: 90 }) },
              { id: "all", label: t("chart.presetAll") },
              { id: "custom", label: t("chart.presetCustom") },
            ].map((preset) => (
              <button
                key={preset.id}
                onClick={() => setDatePreset(preset.id as any)}
                className={`px-3 py-1.5 rounded-xl font-semibold transition-all ${
                  datePreset === preset.id
                    ? "bg-[#0d5c3a] text-white shadow-sm"
                    : "text-slate-500 hover:text-slate-900"
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
                className="bg-white border border-slate-200 text-slate-800 rounded-xl px-2.5 py-1.5 outline-none focus:border-[#0d5c3a] text-[11px]"
              />
              <span className="text-slate-400">{t("chart.rangeTo")}</span>
              <input
                type="date"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                className="bg-white border border-slate-200 text-slate-800 rounded-xl px-2.5 py-1.5 outline-none focus:border-[#0d5c3a] text-[11px]"
              />
            </div>
          )}

          {/* Chart Type Selector */}
          <div className="flex bg-slate-100 border border-slate-200 rounded-2xl p-1 text-xs ml-auto lg:ml-0">
            <button
              onClick={() => setChartType("area")}
              className={`p-2 rounded-xl transition-all ${
                chartType === "area" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-slate-500 hover:text-slate-900"
              }`}
              title={t("chart.typeArea")}
            >
              <AreaChart className="w-4 h-4" />
            </button>
            <button
              onClick={() => setChartType("line")}
              className={`p-2 rounded-xl transition-all ${
                chartType === "line" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-slate-500 hover:text-slate-900"
              }`}
              title={t("chart.typeLine")}
            >
              <TrendingUp className="w-4 h-4" />
            </button>
            <button
              onClick={() => setChartType("bar")}
              className={`p-2 rounded-xl transition-all ${
                chartType === "bar" ? "bg-[#0d5c3a] text-white shadow-sm" : "text-slate-500 hover:text-slate-900"
              }`}
              title={t("chart.typeBar")}
            >
              <BarChart2 className="w-4 h-4" />
            </button>
          </div>

          <button
            onClick={onRefresh}
            className="p-2 text-xs font-semibold rounded-xl bg-neutral-800 hover:bg-neutral-700 text-white transition-colors"
            title={t("chart.refresh")}
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
            <p>{t("chart.emptyPeriod")}</p>
          </div>
        )}
      </div>
    </div>
  );
}
