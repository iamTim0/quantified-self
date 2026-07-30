"use client";

import React, { useState } from "react";
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
import { RefreshCw, BarChart2, TrendingUp, AreaChart, Flame, Moon } from "lucide-react";

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

  const hasBioData = labels.length > 0 && (sleepValues.some((v) => v > 0) || readinessValues.some((v) => v > 0));
  const hasNutritionData = labels.length > 0 && (calorieValues.some((v) => v > 0) || proteinValues.some((v) => v > 0));

  // Default to bio if no nutrition data
  const activeCategory = datasetCategory === "nutrition" && !hasNutritionData && hasBioData ? "bio" : datasetCategory;

  const nutritionChartData = {
    labels,
    datasets: [
      {
        label: "Kalorien (kcal)",
        data: calorieValues,
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
        data: proteinValues,
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
        data: carbValues,
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
        data: fatValues,
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
    labels,
    datasets: [
      {
        label: "Sleep Score",
        data: sleepValues,
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
        data: readinessValues,
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
    maintainAspectRatio: false, // CRITICAL: Prevent container overflow
    interaction: {
      mode: "index" as const,
      intersect: false,
    },
    plugins: {
      legend: {
        position: "top" as const,
        labels: {
          color: "#d1d5db",
          font: { family: "Inter", size: 11 },
          usePointStyle: true,
          boxWidth: 8,
        },
      },
      tooltip: {
        backgroundColor: "rgba(10, 10, 10, 0.9)",
        borderColor: "rgba(255, 255, 255, 0.1)",
        borderWidth: 1,
        titleColor: "#ffffff",
        bodyColor: "#9ca3af",
        padding: 12,
        cornerRadius: 12,
      },
    },
    scales: {
      x: {
        ticks: {
          color: "#9ca3af",
          font: { size: 10 },
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
              title: { display: true, text: "Kalorien (kcal)", color: "#f59e0b", font: { size: 10 } },
              ticks: { color: "#f59e0b", font: { size: 10 } },
              grid: { color: "rgba(255, 255, 255, 0.05)" },
            },
            yGrams: {
              type: "linear" as const,
              display: true,
              position: "right" as const,
              title: { display: true, text: "Makros (g)", color: "#3b82f6", font: { size: 10 } },
              ticks: { color: "#3b82f6", font: { size: 10 } },
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
              ticks: { color: "#9ca3af", font: { size: 10 } },
              grid: { color: "rgba(255, 255, 255, 0.05)" },
            },
          }),
    },
  };

  const hasCurrentData = activeCategory === "nutrition" ? hasNutritionData : hasBioData;

  return (
    <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md overflow-hidden space-y-4">
      {/* Header controls */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 border-b border-neutral-800 pb-4">
        <div className="flex items-center gap-2">
          {/* Category Switcher */}
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

        <div className="flex items-center gap-2 self-end sm:self-auto">
          {/* Chart Type Selector */}
          <div className="flex bg-neutral-950 border border-neutral-800 rounded-xl p-1 text-xs">
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
