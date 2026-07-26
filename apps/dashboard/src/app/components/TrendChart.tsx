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
  const chartData = {
    labels: labels.length > 0 ? labels : ["Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Day 7"],
    datasets: [
      {
        label: "Sleep Score",
        data: sleepValues.length > 0 ? sleepValues : [82, 85, 78, 91, 88, 84, 89],
        borderColor: "#3b82f6",
        backgroundColor: "rgba(59, 130, 246, 0.1)",
        tension: 0.4,
        fill: true,
        pointRadius: 4,
      },
      {
        label: "Readiness Score",
        data: readinessValues.length > 0 ? readinessValues : [79, 82, 75, 88, 85, 80, 87],
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
        min: 50,
        max: 100,
      },
    },
  };

  return (
    <div className="glass-card p-6">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-base font-semibold text-white">Sleep & Readiness 30-Day Trends</h2>
        <button
          onClick={onRefresh}
          className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Refresh</span>
        </button>
      </div>

      <div className="w-full h-64 sm:h-80">
        <Line data={chartData} options={options} />
      </div>
    </div>
  );
}
