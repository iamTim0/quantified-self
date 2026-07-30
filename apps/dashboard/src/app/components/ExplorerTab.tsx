"use client";

import React, { useState, useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import { Filter, Search, ChevronRight, X, Bookmark, Save, Trash2, AreaChart, TrendingUp, BarChart2, Layers, Calendar, RefreshCw } from "lucide-react";

// Client-only dynamic import for ChartJS canvas
const ExplorerChart = dynamic(() => import("./ExplorerChart"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-80 rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 flex items-center justify-center text-xs text-neutral-500">
      Lade Diagramm...
    </div>
  ),
});

export interface DataPointItem {
  id: string;
  source_id: string;
  source_type?: string;
  metric_type: string;
  timestamp: string;
  value: number;
  metadata?: Record<string, any>;
  idempotency_key?: string;
}

export interface SavedView {
  id: string;
  name: string;
  category: string;
  source: string;
  metrics: string[];
  aggregation: "sum" | "avg" | "max" | "raw";
  chartType: "area" | "line" | "bar";
  search: string;
  isDefault?: boolean;
}

interface ExplorerTabProps {
  apiBase: string;
  token: string;
  tenantId: string;
}

const CATEGORIES: Record<string, string[]> = {
  Alle: [],
  "Ernährung & Tagebuch": [
    "consumed_item_calories",
    "consumed_product",
    "consumed_recipe_portion",
    "yazio_calories",
    "yazio_protein",
    "yazio_carbs",
    "yazio_fat",
    "calories",
    "protein",
    "carbohydrates",
    "fat",
  ],
  "Schlaf & Regeneration": [
    "sleep_score",
    "readiness_score",
    "total_sleep_duration",
    "deep_sleep_duration",
    "rem_sleep_duration",
    "hrv_balance",
    "resting_hr",
  ],
  "Fitness & Aktivität": ["activity_score", "steps", "active_calories", "total_calories"],
};

const DEFAULT_PRESET_VIEWS: SavedView[] = [
  {
    id: "preset_nutrition_macros",
    name: "🍏 Yazio Makronährstoffe (Summe)",
    category: "Ernährung & Tagebuch",
    source: "all",
    metrics: ["yazio_protein", "yazio_carbs", "yazio_fat"],
    aggregation: "sum",
    chartType: "bar",
    search: "",
    isDefault: true,
  },
  {
    id: "preset_calories",
    name: "🔥 Kalorien & Produkte",
    category: "Ernährung & Tagebuch",
    source: "all",
    metrics: ["consumed_item_calories", "consumed_product"],
    aggregation: "sum",
    chartType: "area",
    search: "",
    isDefault: true,
  },
  {
    id: "preset_sleep",
    name: "🌙 Schlaf & Regeneration",
    category: "Schlaf & Regeneration",
    source: "all",
    metrics: ["sleep_score", "readiness_score"],
    aggregation: "avg",
    chartType: "line",
    search: "",
    isDefault: true,
  },
];

const COLOR_PALETTE = ["#f59e0b", "#3b82f6", "#10b981", "#ec4899", "#a855f7", "#06b6d4", "#f43f5e"];

export default function ExplorerTab({ apiBase, token, tenantId }: ExplorerTabProps) {
  const [dataPoints, setDataPoints] = useState<DataPointItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Active Filter Query State
  const [selectedCategory, setSelectedCategory] = useState("Alle");
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>([]);
  const [selectedSource, setSelectedSource] = useState("all");
  const [aggregation, setAggregation] = useState<"sum" | "avg" | "max" | "raw">("sum");
  const [chartType, setChartType] = useState<"area" | "line" | "bar">("area");
  const [searchQuery, setSearchQuery] = useState("");
  const [inspectPoint, setInspectPoint] = useState<DataPointItem | null>(null);

  // Saved Views State
  const [savedViews, setSavedViews] = useState<SavedView[]>(DEFAULT_PRESET_VIEWS);
  const [activeViewId, setActiveViewId] = useState<string>("preset_calories");
  const [newViewName, setNewViewName] = useState("");
  const [isSavingView, setIsSavingView] = useState(false);

  // Load saved views from localStorage
  useEffect(() => {
    try {
      const stored = localStorage.getItem(`qs_saved_views_${tenantId}`);
      if (stored) {
        const parsed: SavedView[] = JSON.parse(stored);
        if (parsed.length > 0) {
          setSavedViews([...DEFAULT_PRESET_VIEWS, ...parsed.filter((p) => !p.isDefault)]);
        }
      }
    } catch (e) {
      console.error("Failed to load saved views:", e);
    }
  }, [tenantId]);

  // Fetch metrics data points
  const fetchAllMetrics = async () => {
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
        if (uniqueTypes.length > 0 && selectedMetrics.length === 0) {
          setSelectedMetrics(uniqueTypes.slice(0, 2));
        }
      }
    } catch (err) {
      console.error("Failed to fetch data points for explorer:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (token && tenantId) {
      fetchAllMetrics();
    }
  }, [apiBase, token, tenantId]);

  // Extract available sources and metric types
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

  // Handle Load Saved View
  const handleLoadView = (view: SavedView) => {
    setActiveViewId(view.id);
    setSelectedCategory(view.category);
    setSelectedSource(view.source);
    setSelectedMetrics(view.metrics);
    setAggregation(view.aggregation);
    setChartType(view.chartType);
    setSearchQuery(view.search);
  };

  // Handle Save New View
  const handleSaveCurrentView = () => {
    if (!newViewName.trim()) return;
    const newView: SavedView = {
      id: `view_${Date.now()}`,
      name: newViewName.trim(),
      category: selectedCategory,
      source: selectedSource,
      metrics: [...selectedMetrics],
      aggregation,
      chartType,
      search: searchQuery,
      isDefault: false,
    };
    const updated = [...savedViews, newView];
    setSavedViews(updated);
    localStorage.setItem(
      `qs_saved_views_${tenantId}`,
      JSON.stringify(updated.filter((v) => !v.isDefault))
    );
    setActiveViewId(newView.id);
    setNewViewName("");
    setIsSavingView(false);
  };

  // Handle Delete View
  const handleDeleteView = (viewId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const updated = savedViews.filter((v) => v.id !== viewId);
    setSavedViews(updated);
    localStorage.setItem(
      `qs_saved_views_${tenantId}`,
      JSON.stringify(updated.filter((v) => !v.isDefault))
    );
    if (activeViewId === viewId) {
      setActiveViewId(DEFAULT_PRESET_VIEWS[0].id);
    }
  };

  // Compute chart timeline data with deterministic date formatting
  const timelineData = useMemo(() => {
    if (selectedMetrics.length === 0 || dataPoints.length === 0) return { dates: [], series: [] };

    const formatDate = (isoString?: string) => {
      if (!isoString) return "";
      try {
        const d = new Date(isoString);
        if (isNaN(d.getTime())) return "";
        return d.toISOString().split("T")[0];
      } catch {
        return "";
      }
    };

    // Filter points by source and searchQuery
    const filtered = dataPoints.filter((p) => {
      const src = p.source_type || p.metadata?.source_type || "unknown";
      if (selectedSource !== "all" && src !== selectedSource) return false;
      if (!selectedMetrics.includes(p.metric_type)) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const mStr = JSON.stringify(p.metadata || {}).toLowerCase();
        return p.metric_type.toLowerCase().includes(q) || mStr.includes(q);
      }
      return true;
    });

    const dates = Array.from(
      new Set(filtered.map((p) => formatDate(p.timestamp)).filter(Boolean))
    ).sort() as string[];

    const series = selectedMetrics.map((m, idx) => {
      const color = COLOR_PALETTE[idx % COLOR_PALETTE.length];
      const mPoints = filtered.filter((p) => p.metric_type === m);

      const values = dates.map((d) => {
        const matchingForDay = mPoints.filter((p) => formatDate(p.timestamp) === d);
        if (matchingForDay.length === 0) return 0;

        if (aggregation === "sum") {
          return matchingForDay.reduce((acc, curr) => acc + (curr.value || 0), 0);
        } else if (aggregation === "avg") {
          const sum = matchingForDay.reduce((acc, curr) => acc + (curr.value || 0), 0);
          return Math.round((sum / matchingForDay.length) * 100) / 100;
        } else if (aggregation === "max") {
          return Math.max(...matchingForDay.map((p) => p.value || 0));
        } else {
          return matchingForDay[0].value || 0;
        }
      });

      return { metric: m, color, values };
    });

    return { dates, series };
  }, [dataPoints, selectedMetrics, selectedSource, searchQuery, aggregation]);

  // Compute table data
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
      {/* Page Title & Actions */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-white">Universal Data Explorer & Analytics Engine</h2>
          <p className="text-xs text-neutral-400">
            Dynamisches Abfrage-System mit Multimetrik-Aggregaten, Volltextsuche und gespeicherten Ansichten.
          </p>
        </div>
        <button
          onClick={fetchAllMetrics}
          className="flex items-center gap-2 px-3 py-2 text-xs font-semibold rounded-xl bg-neutral-900 border border-neutral-800 text-neutral-300 hover:text-white transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          <span>Daten aktualisieren</span>
        </button>
      </div>

      {/* Saved Views Bar */}
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-4 backdrop-blur-md space-y-3">
        <div className="flex justify-between items-center">
          <span className="text-xs font-bold uppercase tracking-wider text-purple-400 flex items-center gap-1.5">
            <Bookmark className="w-3.5 h-3.5" /> Gespeicherte Ansichten & Presets
          </span>
          {!isSavingView ? (
            <button
              onClick={() => setIsSavingView(true)}
              className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-xl bg-purple-600/20 text-purple-300 border border-purple-500/30 hover:bg-purple-600/30 transition-colors"
            >
              <Save className="w-3.5 h-3.5" />
              <span>Ansicht speichern</span>
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <input
                type="text"
                placeholder="Name der Ansicht..."
                value={newViewName}
                onChange={(e) => setNewViewName(e.target.value)}
                className="px-3 py-1 text-xs bg-neutral-950 border border-purple-500 text-white rounded-lg outline-none"
              />
              <button
                onClick={handleSaveCurrentView}
                className="px-3 py-1 text-xs bg-purple-600 hover:bg-purple-500 text-white rounded-lg font-semibold"
              >
                Speichern
              </button>
              <button
                onClick={() => setIsSavingView(false)}
                className="p-1 text-neutral-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {savedViews.map((view) => (
            <button
              key={view.id}
              onClick={() => handleLoadView(view)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${
                activeViewId === view.id
                  ? "bg-purple-600 text-white shadow-lg shadow-purple-600/20"
                  : "bg-neutral-950 border border-neutral-800 text-neutral-400 hover:text-white"
              }`}
            >
              <span>{view.name}</span>
              {!view.isDefault && (
                <Trash2
                  className="w-3 h-3 text-neutral-400 hover:text-red-400 transition-colors"
                  onClick={(e) => handleDeleteView(view.id, e)}
                />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Universal Query & Filter Control Bar */}
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-neutral-800 pb-4">
          {/* Category Tabs */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400 flex items-center gap-1.5 mr-2">
              <Filter className="w-3.5 h-3.5 text-blue-400" /> Kategorie:
            </span>
            <div className="flex bg-neutral-950 border border-neutral-800 rounded-xl p-1 text-xs">
              {Object.keys(CATEGORIES).map((cat) => (
                <button
                  key={cat}
                  onClick={() => setSelectedCategory(cat)}
                  className={`px-3 py-1 rounded-lg font-medium transition-colors ${
                    selectedCategory === cat ? "bg-blue-600 text-white" : "text-neutral-400 hover:text-white"
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* Aggregation Mode & Chart Type Selector */}
          <div className="flex items-center gap-3">
            {/* Aggregation Mode */}
            <div className="flex items-center gap-1 bg-neutral-950 border border-neutral-800 rounded-xl p-1 text-xs">
              <span className="text-[10px] text-neutral-500 font-semibold px-2">Aggregat:</span>
              <button
                onClick={() => setAggregation("sum")}
                className={`px-2 py-1 rounded-lg transition-colors ${
                  aggregation === "sum" ? "bg-amber-500/20 text-amber-300 border border-amber-500/30" : "text-neutral-400"
                }`}
                title="Tages-Summe (z.B. Kalorien, Makros)"
              >
                Summe (SUM)
              </button>
              <button
                onClick={() => setAggregation("avg")}
                className={`px-2 py-1 rounded-lg transition-colors ${
                  aggregation === "avg" ? "bg-blue-500/20 text-blue-300 border border-blue-500/30" : "text-neutral-400"
                }`}
                title="Tages-Durchschnitt (z.B. Scores)"
              >
                Ø Schnitt (AVG)
              </button>
              <button
                onClick={() => setAggregation("max")}
                className={`px-2 py-1 rounded-lg transition-colors ${
                  aggregation === "max" ? "bg-purple-500/20 text-purple-300 border border-purple-500/30" : "text-neutral-400"
                }`}
                title="Tages-Maximalwert"
              >
                Peak (MAX)
              </button>
            </div>

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
          </div>
        </div>

        {/* Source Dropdown & Fulltext Search */}
        <div className="flex flex-col sm:flex-row justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-neutral-400">Quelle / Provider:</span>
            <select
              value={selectedSource}
              onChange={(e) => setSelectedSource(e.target.value)}
              className="bg-neutral-950 border border-neutral-800 text-xs text-neutral-200 rounded-xl px-3 py-1.5 focus:outline-none focus:border-purple-500"
            >
              <option value="all">Alle Quellen (Multi-Source)</option>
              {availableSources.map((src) => (
                <option key={src} value={src}>
                  {src.toUpperCase()}
                </option>
              ))}
            </select>
          </div>

          <div className="relative w-full sm:w-72">
            <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-neutral-500" />
            <input
              type="text"
              placeholder="Volltextsuche (z.B. Nektarine, Magerquark)..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-neutral-950 border border-neutral-800 text-xs text-white pl-9 pr-3 py-2 rounded-xl focus:outline-none focus:border-purple-500"
            />
          </div>
        </div>

        {/* Metric Selector Pills */}
        <div className="space-y-2 pt-2">
          <label className="text-xs font-semibold text-neutral-400">Aktive Metriken im Diagramm:</label>
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
                      : "bg-neutral-950/80 border-neutral-800 text-neutral-400 hover:text-white"
                  }`}
                >
                  {m}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Responsive Analytics Diagram Container */}
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md space-y-4 overflow-hidden">
        <div className="flex justify-between items-center border-b border-neutral-800 pb-3">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <Layers className="w-4 h-4 text-purple-400" /> Analytics Trend & Vergleichs-Diagramm
          </h3>
          <span className="text-[11px] text-neutral-400 font-mono">
            {timelineData.dates.length} Tage analysiert ({aggregation.toUpperCase()} Aggregation)
          </span>
        </div>

        <ExplorerChart
          dates={timelineData.dates}
          series={timelineData.series}
          chartType={chartType}
          aggregation={aggregation}
        />
      </div>

      {/* Raw Data Points Table */}
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md space-y-4">
        <div className="flex justify-between items-center">
          <div>
            <h3 className="text-sm font-semibold text-neutral-200">Gefilterte Datenpunkte Log</h3>
            <p className="text-xs text-neutral-400">Inspektion der Rohdaten ({tableData.length} Einträge)</p>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-neutral-800 text-neutral-400 uppercase tracking-wider font-semibold">
                <th className="pb-3 px-3">Zeitstempel</th>
                <th className="pb-3 px-3">Quelle</th>
                <th className="pb-3 px-3">Metrik Typ / Name</th>
                <th className="pb-3 px-3">Wert</th>
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
                      title="Metadata Inspektor öffnen"
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

      {/* Metadata Inspector Dialog */}
      {inspectPoint && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-md flex items-center justify-center p-4">
          <div className="w-full max-w-lg rounded-2xl bg-neutral-950 border border-neutral-800 p-6 shadow-2xl space-y-4">
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
                <pre className="bg-neutral-900 p-3 rounded-xl border border-neutral-800 text-emerald-400 font-mono text-[11px] overflow-x-auto max-h-60">
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
