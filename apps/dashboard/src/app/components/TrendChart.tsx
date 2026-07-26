"use client";

import React from "react";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from "chart.js";
import { Line } from "react-chartjs-2";
import { RefreshCw } from "lucide-react";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

interface TrendChartProps {
  labels: string[];
  sleepValues: number[];
  readinessValues: number[];
  onRefresh: () => void;
}

export default function TrendChart({ labels, sleepValues, readinessValues, onRefresh }: TrendChartProps) {
  const hasData = labels.length > 0 && (sleepValues.length > 0 || readinessValues.length > 0);

  const chartData = {
    labels,
    datasets: [
      {
        label: "Sleep Score",
        data: sleepValues,
        borderColor: "#3b82f6",
        backgroundColor: "rgba(59, 130, 246, 0.1)",
        tension: 0.4,
        fill: true,
        pointRadius: 4,
      },
      {
        label: "Readiness Score",
        data: readinessValues,
        borderColor: "#06b6d4",
        backgroundColor: "rgba(6, 182, 212, 0.05)",
        tension: 0.4,
        fill: true,
        pointRadius: 4,
      },
    ],
  };

  const options = {
    responsive: true,
    plugins: {
      legend: {
        labels: {
          color: "#9ca3af",
          font: { family: "Inter" },
        },
      },
    },
    scales: {
      x: {
        ticks: { color: "#9ca3af" },
        grid: { color: "rgba(255, 255, 255, 0.05)" },
      },
      y: {
        ticks: { color: "#9ca3af" },
        grid: { color: "rgba(255, 255, 255, 0.05)" },
        min: 0,
        max: 100,
      },
    },
  };

  return (
    <div className="glass-card p-6">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-base font-semibold text-white">Sleep & Readiness Trends</h2>
        <button
          onClick={onRefresh}
          className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Refresh</span>
        </button>
      </div>

      {hasData ? (
        <div className="w-full h-64 sm:h-80">
          <Line data={chartData} options={options} />
        </div>
      ) : (
        <div className="w-full h-48 flex items-center justify-center text-xs text-neutral-500">
          No trend data available for Sleep or Readiness yet.
        </div>
      )}
    </div>
  );
}
