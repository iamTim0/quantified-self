"use client";

import React from "react";
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
  Filler,
);

ChartJS.defaults.font.family = "var(--font-outfit), 'Outfit', system-ui, sans-serif";

interface ExplorerChartProps {
  dates: string[];
  series: Array<{
    /** Canonical `metric_type` — the series identity, and what the data are keyed by. */
    metric: string;
    /**
     * What the legend reads: the metric's name in the reader's language, with its
     * unit. Absent falls back to the key, which is what the legend showed for every
     * series before — `strength_set_heart_rate_max` where a name belonged.
     */
    label?: string;
    color: string;
    values: number[];
  }>;
  chartType: "area" | "line" | "bar";
  aggregation: "sum" | "avg" | "max" | "raw";
}

export default function ExplorerChart({
  dates,
  series,
  chartType,
  aggregation,
}: ExplorerChartProps) {
  const t = useT();
  const chartData = {
    labels: dates,
    datasets: series.map((s) => ({
      label: s.label ?? s.metric,
      data: s.values,
      borderColor: s.color,
      backgroundColor: chartType === "area" ? `${s.color}25` : `${s.color}aa`,
      borderWidth: 2,
      tension: 0.3,
      fill: chartType === "area",
      pointRadius: chartType === "bar" ? 0 : 3,
      pointHoverRadius: 6,
    })),
  };

  const options: any = {
    responsive: true,
    maintainAspectRatio: false, // Strict overflow containment
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
        callbacks: {
          label: (ctx: any) => `${ctx.dataset.label}: ${ctx.raw} (${aggregation.toUpperCase()})`,
        },
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
      y: {
        type: "linear" as const,
        ticks: {
          color: "#64748b",
          font: { family: "var(--font-jetbrains-mono), monospace", size: 10, weight: 600 },
        },
        grid: { color: "#f1f5f9" },
      },
    },
  };

  return (
    <div className="w-full relative h-[320px] sm:h-[380px] overflow-hidden">
      {dates.length > 0 && series.length > 0 ? (
        chartType === "bar" ? (
          <Bar data={chartData} options={options} />
        ) : (
          <Line data={chartData} options={options} />
        )
      ) : (
        <div className="w-full h-full flex items-center justify-center text-xs text-neutral-500">
          {t("chart.emptyFilter")}
        </div>
      )}
    </div>
  );
}
