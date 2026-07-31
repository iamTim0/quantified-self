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

interface ExplorerChartProps {
  dates: string[];
  series: Array<{
    metric: string;
    color: string;
    values: number[];
  }>;
  chartType: "area" | "line" | "bar";
  aggregation: "sum" | "avg" | "max" | "raw";
}

export default function ExplorerChart({ dates, series, chartType, aggregation }: ExplorerChartProps) {
  const chartData = {
    labels: dates,
    datasets: series.map((s) => ({
      label: s.metric,
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
        callbacks: {
          label: (ctx: any) => `${ctx.dataset.label}: ${ctx.raw} (${aggregation.toUpperCase()})`,
        },
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
      y: {
        type: "linear" as const,
        ticks: { color: "#9ca3af", font: { family: "'JetBrains Mono', monospace", size: 10, weight: 600 } },
        grid: { color: "rgba(255, 255, 255, 0.05)" },
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
          Keine Datenpunkte für die aktuelle Filterauswahl vorhanden.
        </div>
      )}
    </div>
  );
}
