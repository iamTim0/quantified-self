"use client";

import React, { useState, useEffect, useMemo } from "react";
import { Filter, Search, ChevronRight, X } from "lucide-react";

interface DataPointItem {
  id: string;
  source_id: string;
  source_type?: string;
  metric_type: string;
  timestamp: string;
  value: number;
  metadata?: Record<string, any>;
  idempotency_key?: string;
}

interface ExplorerTabProps {
  apiBase: string;
  token: string;
  tenantId: string;
}

const CATEGORIES: Record<string, string[]> = {
  All: [],
  "Sleep & Recovery": [
    "sleep_score",
    "readiness_score",
    "total_sleep_duration",
    "deep_sleep_duration",
    "rem_sleep_duration",
    "hrv_balance",
    "resting_hr",
  ],
  "Nutrition & Macros": [
    "calories",
    "protein",
    "carbohydrates",
    "fat",
    "fiber",
    "breakfast_calories",
    "lunch_calories",
    "dinner_calories",
    "snack_calories",
    "consumed_item_calories",
  ],
  "Activity & Fitness": ["activity_score", "steps", "active_calories", "total_calories"],
};

const COLOR_PALETTE = ["#38bdf8", "#10b981", "#a855f7", "#f59e0b", "#f43f5e", "#06b6d4"];

export default function ExplorerTab({ apiBase, token, tenantId }: ExplorerTabProps) {
  const [dataPoints, setDataPoints] = useState<DataPointItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedCategory, setSelectedCategory] = useState("All");
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>([]);
  const [selectedSource, setSelectedSource] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [inspectPoint, setInspectPoint] = useState<DataPointItem | null>(null);

  useEffect(() => {
    async function fetchAllMetrics() {
      setLoading(true);
      try {
        const res = await fetch(`${apiBase}/api/v1/data/metrics?limit=500`, {
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Tenant-ID": tenantId,
          },
        });
        if (res.ok) {
          const data = await res.json();
          const points: DataPointItem[] = data.data_points || [];
          setDataPoints(points);

          const uniqueTypes = Array.from(new Set(points.map((p) => p.metric_type)));
          if (uniqueTypes.length > 0) {
            setSelectedMetrics(uniqueTypes.slice(0, 2));
          }
        }
      } catch (err) {
        console.error("Failed to fetch data points for explorer:", err);
      } finally {
        setLoading(false);
      }
    }
    if (token && tenantId) {
      fetchAllMetrics();
    }
  }, [apiBase, token, tenantId]);

  const availableSources = useMemo(() => {
    const set = new Set<string>();
    dataPoints.forEach((p) => {
      const src = p.source_type || p.metadata?.source_type || "unknown";
      set.add(src);
    });
    return Array.from(set);
  }, [dataPoints]);

  const availableMetricTypes = useMemo(() => {
    const catMetrics = CATEGORIES[selectedCategory] || [];
    const set = new Set<string>();
    dataPoints.forEach((p) => {
      if (catMetrics.length === 0 || catMetrics.includes(p.metric_type)) {
        set.add(p.metric_type);
      }
    });
    return Array.from(set);
  }, [dataPoints, selectedCategory]);

  const toggleMetric = (m: string) => {
    setSelectedMetrics((prev) =>
      prev.includes(m) ? prev.filter((item) => item !== m) : [...prev, m]
    );
  };

  const timelineData = useMemo(() => {
    if (selectedMetrics.length === 0 || dataPoints.length === 0) return { dates: [], series: [] };

    const filtered = dataPoints.filter((p) => {
      const src = p.source_type || p.metadata?.source_type || "unknown";
      if (selectedSource !== "all" && src !== selectedSource) return false;
      return selectedMetrics.includes(p.metric_type);
    });

    const datesSet = new Set<string>();
    filtered.forEach((p) => {
      datesSet.add(new Date(p.timestamp).toLocaleDateString());
    });
    const dates = Array.from(datesSet).sort();

    const series = selectedMetrics.map((m, idx) => {
      const color = COLOR_PALETTE[idx % COLOR_PALETTE.length];
      const mPoints = filtered.filter((p) => p.metric_type === m);
      const values = dates.map((d) => {
        const match = mPoints.find((p) => new Date(p.timestamp).toLocaleDateString() === d);
        return match ? match.value : 0;
      });
      return { metric: m, color, values };
    });

    return { dates, series };
  }, [dataPoints, selectedMetrics, selectedSource]);

  const tableData = useMemo(() => {
    return dataPoints.filter((p) => {
      const src = p.source_type || p.metadata?.source_type || "unknown";
      if (selectedSource !== "all" && src !== selectedSource) return false;
      if (selectedMetrics.length > 0 && !selectedMetrics.includes(p.metric_type)) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const mStr = JSON.stringify(p.metadata || {}).toLowerCase();
        return p.metric_type.toLowerCase().includes(q) || mStr.includes(q);
      }
      return true;
    });
  }, [dataPoints, selectedSource, selectedMetrics, searchQuery]);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-bold text-white">Data Explorer & Metric Comparison</h2>
        <p className="text-xs text-neutral-400">
          Compare multiple metrics across sources on a single timeline chart. Zero demo data.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 p-4 rounded-2xl bg-neutral-900/60 border border-neutral-800 backdrop-blur-md">
        <div className="flex items-center gap-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mr-2">
          <Filter className="w-3.5 h-3.5 text-purple-400" />
          <span>Category:</span>
        </div>
        {Object.keys(CATEGORIES).map((cat) => (
          <button
            key={cat}
            onClick={() => setSelectedCategory(cat)}
            className={`px-3 py-1.5 text-xs font-semibold rounded-xl transition-all ${
              selectedCategory === cat
                ? "bg-purple-600 text-white shadow-md shadow-purple-600/20"
                : "bg-neutral-900 border border-neutral-800 text-neutral-400 hover:text-white"
            }`}
          >
            {cat}
          </button>
        ))}

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-neutral-400 font-medium">Source:</span>
          <select
            value={selectedSource}
            onChange={(e) => setSelectedSource(e.target.value)}
            className="bg-neutral-950 border border-neutral-800 text-xs text-neutral-200 rounded-xl px-3 py-1.5 focus:outline-none focus:border-purple-500"
          >
            <option value="all">All Sources</option>
            {availableSources.map((src) => (
              <option key={src} value={src}>
                {src.toUpperCase()}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-xs font-medium text-neutral-400">Select Metrics to Compare:</label>
        <div className="flex flex-wrap gap-2">
          {availableMetricTypes.map((m) => {
            const isSelected = selectedMetrics.includes(m);
            const idx = selectedMetrics.indexOf(m);
            const color = isSelected ? COLOR_PALETTE[idx % COLOR_PALETTE.length] : undefined;

            return (
              <button
                key={m}
                onClick={() => toggleMetric(m)}
                style={isSelected ? { backgroundColor: `${color}20`, borderColor: color, color } : undefined}
                className={`px-3 py-1.5 text-xs font-medium rounded-xl border transition-all ${
                  isSelected
                    ? "font-semibold shadow-sm"
                    : "bg-neutral-900/80 border-neutral-800 text-neutral-400 hover:text-white"
                }`}
              >
                {m}
              </button>
            );
          })}
        </div>
      </div>

      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md">
        <div className="flex justify-between items-center mb-6">
          <h3 className="text-sm font-semibold text-neutral-200">Comparison Graph</h3>
          <div className="flex items-center gap-4 text-xs">
            {timelineData.series.map((s) => (
              <div key={s.metric} className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: s.color }} />
                <span className="text-neutral-300 font-medium">{s.metric}</span>
              </div>
            ))}
          </div>
        </div>

        {timelineData.dates.length > 0 ? (
          <div className="h-64 flex items-end gap-2 pt-6 border-b border-neutral-800">
            {timelineData.dates.map((date, dIdx) => (
              <div key={date} className="flex-1 flex flex-col items-center gap-2 group relative">
                <div className="w-full flex items-end justify-center gap-1 h-48">
                  {timelineData.series.map((s) => {
                    const maxVal = Math.max(...s.values, 1);
                    const val = s.values[dIdx] || 0;
                    const heightPct = Math.min(100, Math.max(8, (val / maxVal) * 100));

                    return (
                      <div
                        key={s.metric}
                        style={{ height: `${heightPct}%`, backgroundColor: s.color }}
                        className="w-2 rounded-t-sm opacity-80 hover:opacity-100 transition-opacity"
                        title={`${s.metric}: ${val} (${date})`}
                      />
                    );
                  })}
                </div>
                <span className="text-[10px] text-neutral-500 group-hover:text-neutral-300 truncate w-full text-center">
                  {date}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="h-48 flex items-center justify-center text-xs text-neutral-500">
            {loading ? "Loading metrics..." : "No metrics selected or no data available for current selection."}
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
          <div>
            <h3 className="text-sm font-semibold text-neutral-200">Raw Data Points Log</h3>
            <p className="text-xs text-neutral-400">Inspecting ingested records ({tableData.length} entries)</p>
          </div>
          <div className="relative w-full sm:w-64">
            <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-neutral-500" />
            <input
              type="text"
              placeholder="Search metrics or metadata..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-neutral-950 border border-neutral-800 text-xs text-white pl-9 pr-3 py-2 rounded-xl focus:outline-none focus:border-purple-500"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-neutral-800 text-neutral-400 uppercase tracking-wider font-semibold">
                <th className="pb-3 px-3">Timestamp</th>
                <th className="pb-3 px-3">Source</th>
                <th className="pb-3 px-3">Metric Type</th>
                <th className="pb-3 px-3">Value</th>
                <th className="pb-3 px-3 text-right">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800/60">
              {tableData.slice(0, 50).map((dp) => (
                <tr key={dp.id || dp.idempotency_key} className="hover:bg-neutral-800/40 transition-colors">
                  <td className="py-3 px-3 text-neutral-300 font-mono">
                    {new Date(dp.timestamp).toLocaleString()}
                  </td>
                  <td className="py-3 px-3">
                    <span className="px-2 py-0.5 rounded-full text-[10px] uppercase font-bold bg-neutral-800 border border-neutral-700 text-purple-300">
                      {dp.source_type || dp.metadata?.source_type || "api"}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-white font-medium">
                    <div>{dp.metric_type}</div>
                    {dp.metadata?.food_name && (
                      <div className="text-xs text-blue-400 font-normal">{dp.metadata.food_name}</div>
                    )}
                  </td>
                  <td className="py-3 px-3 text-emerald-400 font-bold font-mono">{dp.value}</td>
                  <td className="py-3 px-3 text-right">
                    <button
                      onClick={() => setInspectPoint(dp)}
                      className="p-1 text-neutral-400 hover:text-white transition-colors"
                      title="Inspect Metadata"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {inspectPoint && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-lg rounded-2xl bg-neutral-900 border border-neutral-800 p-6 shadow-2xl space-y-4">
            <div className="flex justify-between items-center border-b border-neutral-800 pb-3">
              <h4 className="text-sm font-bold text-white">DataPoint Metadata Inspector</h4>
              <button onClick={() => setInspectPoint(null)} className="text-neutral-400 hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-2 text-xs">
              <p><span className="text-neutral-400">ID:</span> <span className="font-mono text-white">{inspectPoint.id}</span></p>
              <p><span className="text-neutral-400">Metric:</span> <span className="text-purple-300 font-semibold">{inspectPoint.metric_type}</span></p>
              <p><span className="text-neutral-400">Idempotency Key:</span> <span className="font-mono text-neutral-400 break-all">{inspectPoint.idempotency_key}</span></p>
              <div className="mt-3">
                <span className="text-neutral-400 block mb-1">Metadata Payload:</span>
                <pre className="bg-neutral-950 p-3 rounded-xl border border-neutral-800 text-emerald-400 font-mono text-[11px] overflow-x-auto max-h-60">
                  {JSON.stringify(inspectPoint.metadata || {}, null, 2)}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
