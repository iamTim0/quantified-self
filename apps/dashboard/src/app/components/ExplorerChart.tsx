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
          color: "#d1d5db",
          font: { family: "Inter", size: 11 },
          usePointStyle: true,
          boxWidth: 8,
        },
      },
      tooltip: {
        backgroundColor: "rgba(10, 10, 10, 0.95)",
        borderColor: "rgba(255, 255, 255, 0.1)",
        borderWidth: 1,
        titleColor: "#ffffff",
        bodyColor: "#9ca3af",
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
          font: { size: 10 },
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 12,
        },
        grid: { color: "rgba(255, 255, 255, 0.05)" },
      },
      y: {
        type: "linear" as const,
        ticks: { color: "#9ca3af", font: { size: 10 } },
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
