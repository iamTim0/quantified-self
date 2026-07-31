"use client";

import React, { useState, useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import { Search, ChevronRight, X, AreaChart, TrendingUp, BarChart2, Layers, Calendar, RefreshCw, Database, Check, Cpu, Bookmark, Save, Trash2 } from "lucide-react";

// Client-only dynamic import for ChartJS canvas
const ExplorerChart = dynamic(() => import("./ExplorerChart"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-80 rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 flex items-center justify-center text-xs text-neutral-500">
      Lade Raw Analytics Diagramm...
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

export interface BackendSavedView {
  id: string;
  name: string;
  query_config: {
    source?: string;
    metrics?: string[];
    aggregation?: "sum" | "avg" | "max" | "raw";
    chartType?: "area" | "line" | "bar";
    dateRangePreset?: "7d" | "14d" | "30d" | "90d" | "all" | "custom";
    searchQuery?: string;
  };
  is_shared?: boolean;
  created_at?: string;
}

interface ExplorerTabProps {
  apiBase: string;
  token: string;
  tenantId: string;
}

const COLOR_PALETTE = ["#f59e0b", "#3b82f6", "#10b981", "#ec4899", "#a855f7", "#06b6d4", "#f43f5e", "#eab308"];

export default function ExplorerTab({ apiBase, token, tenantId }: ExplorerTabProps) {
  const [dataPoints, setDataPoints] = useState<DataPointItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Active Raw Filter Query State
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>([]);
  const [selectedSource, setSelectedSource] = useState("all");
  const [aggregation, setAggregation] = useState<"sum" | "avg" | "max" | "raw">("sum");
  const [chartType, setChartType] = useState<"area" | "line" | "bar">("area");
  const [dateRangePreset, setDateRangePreset] = useState<"7d" | "14d" | "30d" | "90d" | "all" | "custom">("30d");
  const [customStartDate, setCustomStartDate] = useState("");
  const [customEndDate, setCustomEndDate] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [inspectPoint, setInspectPoint] = useState<DataPointItem | null>(null);

  // SaaS Multi-Tenant Backend Saved Views (PostgreSQL)
  const [savedViews, setSavedViews] = useState<BackendSavedView[]>([]);
  const [activeViewId, setActiveViewId] = useState<string | null>(null);
  const [newViewName, setNewViewName] = useState("");
  const [isSavingView, setIsSavingView] = useState(false);

  // Fetch metrics data points from Core Data Service
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

        const uniqueTypes = Array.from(new Set(points.map((p) => p.metric_type))).sort();
        if (uniqueTypes.length > 0 && selectedMetrics.length === 0) {
          setSelectedMetrics(uniqueTypes.slice(0, 3));
        }
      }
    } catch (err) {
      console.error("Failed to fetch data points for raw explorer:", err);
    } finally {
      setLoading(false);
    }
  };

  // Fetch saved views directly from PostgreSQL Core Service
  const fetchSavedViews = async () => {
    try {
      const res = await fetch(`${apiBase}/api/v1/data/explorer/views`, {
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": tenantId,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setSavedViews(data.views || []);
      }
    } catch (e) {
      console.error("Failed to fetch saved views from PostgreSQL:", e);
    }
  };

  useEffect(() => {
    if (token && tenantId) {
      fetchAllMetrics();
      fetchSavedViews();
    }
  }, [apiBase, token, tenantId]);

  // Handle Save New View to PostgreSQL
  const handleSaveCurrentView = async () => {
    if (!newViewName.trim()) return;
    try {
      const res = await fetch(`${apiBase}/api/v1/data/explorer/views`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": tenantId,
        },
        body: JSON.stringify({
          name: newViewName.trim(),
          query_config: {
            source: selectedSource,
            metrics: selectedMetrics,
            aggregation,
            chartType,
            dateRangePreset,
            searchQuery,
          },
          is_shared: false,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setNewViewName("");
        setIsSavingView(false);
        fetchSavedViews();
        if (data.view_id) setActiveViewId(data.view_id);
      }
    } catch (e) {
      console.error("Failed to save view to PostgreSQL:", e);
    }
  };

  // Handle Delete View from PostgreSQL
  const handleDeleteView = async (viewId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await fetch(`${apiBase}/api/v1/data/explorer/views/${viewId}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": tenantId,
        },
      });
      if (res.ok) {
        if (activeViewId === viewId) setActiveViewId(null);
        fetchSavedViews();
      }
    } catch (e) {
      console.error("Failed to delete view from PostgreSQL:", e);
    }
  };

  // Handle Load Saved View
  const handleLoadView = (view: BackendSavedView) => {
    setActiveViewId(view.id);
    const cfg = view.query_config || {};
    if (cfg.source) setSelectedSource(cfg.source);
    if (cfg.metrics) setSelectedMetrics(cfg.metrics);
    if (cfg.aggregation) setAggregation(cfg.aggregation);
    if (cfg.chartType) setChartType(cfg.chartType);
    if (cfg.dateRangePreset) setDateRangePreset(cfg.dateRangePreset);
    if (cfg.searchQuery !== undefined) setSearchQuery(cfg.searchQuery);
  };

  // Extract available data sources
  const availableSources = useMemo(() => {
    const set = new Set<string>();
    dataPoints.forEach((p) => {
      const src = p.source_type || p.metadata?.source_type || "unknown";
      set.add(src);
    });
    return Array.from(set);
  }, [dataPoints]);

  // Extract ALL unique metrics present in DB with their item counts
  const availableMetricsWithCount = useMemo(() => {
    const map = new Map<string, number>();
    dataPoints.forEach((p) => {
      const src = p.source_type || p.metadata?.source_type || "unknown";
      if (selectedSource !== "all" && src !== selectedSource) return;
      map.set(p.metric_type, (map.get(p.metric_type) || 0) + 1);
    });
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
  }, [dataPoints, selectedSource]);

  const toggleMetric = (m: string) => {
    setSelectedMetrics((prev) =>
      prev.includes(m) ? prev.filter((item) => item !== m) : [...prev, m]
    );
  };

  const selectAllMetrics = () => {
    setSelectedMetrics(availableMetricsWithCount.map(([m]) => m));
  };

  const clearMetrics = () => {
    setSelectedMetrics([]);
  };

  // Compute chart timeline data with deterministic date formatting & date range filtering
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

    let dates = Array.from(
      new Set(filtered.map((p) => formatDate(p.timestamp)).filter(Boolean))
    ).sort() as string[];

    if (dateRangePreset === "7d") dates = dates.slice(Math.max(0, dates.length - 7));
    else if (dateRangePreset === "14d") dates = dates.slice(Math.max(0, dates.length - 14));
    else if (dateRangePreset === "30d") dates = dates.slice(Math.max(0, dates.length - 30));
    else if (dateRangePreset === "90d") dates = dates.slice(Math.max(0, dates.length - 90));
    else if (dateRangePreset === "custom") {
      dates = dates.filter((d) => {
        if (customStartDate && d < customStartDate) return false;
        if (customEndDate && d > customEndDate) return false;
        return true;
      });
    }

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
  }, [dataPoints, selectedMetrics, selectedSource, searchQuery, aggregation, dateRangePreset, customStartDate, customEndDate]);

  // Compute raw table data
  const tableData = useMemo(() => {
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

    return dataPoints.filter((p) => {
      const src = p.source_type || p.metadata?.source_type || "unknown";
      if (selectedSource !== "all" && src !== selectedSource) return false;
      if (selectedMetrics.length > 0 && !selectedMetrics.includes(p.metric_type)) return false;

      const d = formatDate(p.timestamp);
      if (dateRangePreset === "custom") {
        if (customStartDate && d < customStartDate) return false;
        if (customEndDate && d > customEndDate) return false;
      }

      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const mStr = JSON.stringify(p.metadata || {}).toLowerCase();
        return p.metric_type.toLowerCase().includes(q) || mStr.includes(q);
      }
      return true;
    });
  }, [dataPoints, selectedSource, selectedMetrics, searchQuery, dateRangePreset, customStartDate, customEndDate]);

  return (
    <div className="space-y-8">
      {/* Header & Refresh */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-purple-400" />
            <h2 className="text-xl font-bold text-white">Raw Data Explorer & Abfrage-Engine</h2>
          </div>
          <p className="text-xs text-neutral-400 mt-1">
            Direkter Zugriff auf alle Rohdatenpunkte in TimescaleDB. Ansichten werden dauerhaft in PostgreSQL gespeichert.
          </p>
        </div>
        <button
          onClick={fetchAllMetrics}
          className="flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-xl bg-neutral-900 border border-neutral-800 text-neutral-300 hover:text-white transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          <span>Daten Aktualisieren</span>
        </button>
      </div>

      {/* SaaS Multi-Tenant PostgreSQL Saved Views Bar */}
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-4 backdrop-blur-md space-y-3">
        <div className="flex justify-between items-center">
          <span className="text-xs font-bold uppercase tracking-wider text-purple-400 flex items-center gap-1.5">
            <Bookmark className="w-3.5 h-3.5" /> Gespeicherte Ansichten (PostgreSQL Synced)
          </span>
          {!isSavingView ? (
            <button
              onClick={() => setIsSavingView(true)}
              className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-xl bg-purple-600/20 text-purple-300 border border-purple-500/30 hover:bg-purple-600/30 transition-colors"
            >
              <Save className="w-3.5 h-3.5" /> Aktuelle Ansicht Speichern
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <input
                type="text"
                placeholder="Name der Ansicht..."
                value={newViewName}
                onChange={(e) => setNewViewName(e.target.value)}
                className="px-3 py-1 rounded-lg bg-neutral-950 border border-neutral-700 text-white text-xs outline-none focus:border-purple-500"
              />
              <button
                onClick={handleSaveCurrentView}
                className="px-3 py-1 rounded-lg bg-purple-600 text-white text-xs font-semibold hover:bg-purple-500"
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

        {savedViews.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {savedViews.map((view) => {
              const isActive = activeViewId === view.id;
              return (
                <div
                  key={view.id}
                  onClick={() => handleLoadView(view)}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border text-xs font-medium cursor-pointer transition-all ${
                    isActive
                      ? "bg-purple-600/20 text-purple-300 border-purple-500/50 shadow-md shadow-purple-600/10 font-bold"
                      : "bg-neutral-950 border-neutral-800/80 text-neutral-400 hover:text-white hover:border-neutral-700"
                  }`}
                >
                  <span>{view.name}</span>
                  <button
                    onClick={(e) => handleDeleteView(view.id, e)}
                    className="text-neutral-500 hover:text-red-400 transition-colors ml-1"
                    title="Ansicht aus PostgreSQL löschen"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-neutral-500">
            Noch keine benutzerdefinierten Ansichten in PostgreSQL gespeichert. Konfiguriere Filter und klicke auf "Aktuelle Ansicht Speichern".
          </p>
        )}
      </div>

      {/* Raw Query & Control Bar */}
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md space-y-5">
        {/* Controls Row: Source, Date Range, Aggregation, Chart Type */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-neutral-800 pb-4">
          <div className="flex flex-wrap items-center gap-4">
            {/* Source Provider Filter */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-blue-400" /> Quelle:
              </span>
              <select
                value={selectedSource}
                onChange={(e) => setSelectedSource(e.target.value)}
                className="px-3 py-1.5 rounded-xl bg-neutral-950 border border-neutral-800 text-white text-xs font-semibold outline-none focus:border-blue-500"
              >
                <option value="all">Alle Quellen</option>
                {availableSources.map((src) => (
                  <option key={src} value={src}>
                    {src.toUpperCase()}
                  </option>
                ))}
              </select>
            </div>

            {/* Date Range Picker Bar */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400 flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5 text-emerald-400" /> Zeitraum:
              </span>
              <div className="flex bg-neutral-950 border border-neutral-800 rounded-xl p-1 text-xs">
                {[
                  { id: "7d", label: "7T" },
                  { id: "14d", label: "14T" },
                  { id: "30d", label: "30T" },
                  { id: "90d", label: "90T" },
                  { id: "all", label: "Gesamt" },
                  { id: "custom", label: "Datum..." },
                ].map((preset) => (
                  <button
                    key={preset.id}
                    onClick={() => setDateRangePreset(preset.id as any)}
                    className={`px-2.5 py-1 rounded-lg font-medium transition-colors ${
                      dateRangePreset === preset.id
                        ? "bg-emerald-600 text-white font-semibold"
                        : "text-neutral-400 hover:text-white"
                    }`}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>

              {dateRangePreset === "custom" && (
                <div className="flex items-center gap-1 text-xs">
                  <input
                    type="date"
                    value={customStartDate}
                    onChange={(e) => setCustomStartDate(e.target.value)}
                    className="bg-neutral-950 border border-neutral-800 text-white rounded-lg px-2 py-1 outline-none focus:border-emerald-500 text-[11px]"
                  />
                  <span className="text-neutral-500">bis</span>
                  <input
                    type="date"
                    value={customEndDate}
                    onChange={(e) => setCustomEndDate(e.target.value)}
                    className="bg-neutral-950 border border-neutral-800 text-white rounded-lg px-2 py-1 outline-none focus:border-emerald-500 text-[11px]"
                  />
                </div>
              )}
            </div>
          </div>

          {/* Aggregation Mode & Chart Type Selector */}
          <div className="flex flex-wrap items-center gap-3">
            {/* Aggregation Mode */}
            <div className="flex items-center gap-1 bg-neutral-950 border border-neutral-800 rounded-xl p-1 text-xs">
              <span className="text-[10px] text-neutral-500 font-semibold px-2">Aggregat:</span>
              <button
                onClick={() => setAggregation("sum")}
                className={`px-2.5 py-1 rounded-lg transition-colors font-medium ${
                  aggregation === "sum" ? "bg-amber-500/20 text-amber-300 border border-amber-500/30" : "text-neutral-400 hover:text-white"
                }`}
                title="Tages-Summe"
              >
                SUM
              </button>
              <button
                onClick={() => setAggregation("avg")}
                className={`px-2.5 py-1 rounded-lg transition-colors font-medium ${
                  aggregation === "avg" ? "bg-blue-500/20 text-blue-300 border border-blue-500/30" : "text-neutral-400 hover:text-white"
                }`}
                title="Tages-Durchschnitt"
              >
                Ø AVG
              </button>
              <button
                onClick={() => setAggregation("max")}
                className={`px-2.5 py-1 rounded-lg transition-colors font-medium ${
                  aggregation === "max" ? "bg-purple-500/20 text-purple-300 border border-purple-500/30" : "text-neutral-400 hover:text-white"
                }`}
                title="Maximalwert"
              >
                MAX
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

        {/* Dynamic Metric Selection Pills */}
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <span className="text-xs font-semibold uppercase tracking-wider text-neutral-400 flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5 text-purple-400" /> Ausgewählte Metriken ({selectedMetrics.length}):
            </span>
            <div className="flex items-center gap-2 text-[11px]">
              <button
                onClick={selectAllMetrics}
                className="text-purple-400 hover:underline font-medium"
              >
                Alle auswählen
              </button>
              <span className="text-neutral-700">•</span>
              <button
                onClick={clearMetrics}
                className="text-neutral-400 hover:text-white font-medium"
              >
                Auswahl leeren
              </button>
            </div>
          </div>

          <div className="flex flex-wrap gap-2 max-h-36 overflow-y-auto pr-1">
            {availableMetricsWithCount.map(([m, count]) => {
              const selected = selectedMetrics.includes(m);
              return (
                <button
                  key={m}
                  onClick={() => toggleMetric(m)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-mono transition-all ${
                    selected
                      ? "bg-purple-600 text-white border-purple-500 shadow-md shadow-purple-600/20 font-bold"
                      : "bg-neutral-950/80 border-neutral-800 text-neutral-400 hover:text-white hover:border-neutral-700"
                  }`}
                >
                  {selected && <Check className="w-3 h-3 text-white shrink-0" />}
                  <span>{m}</span>
                  <span
                    className={`text-[9px] px-1.5 py-0.2 rounded-full font-sans ${
                      selected ? "bg-white/20 text-white" : "bg-neutral-800 text-neutral-500"
                    }`}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Fulltext Search Input */}
        <div className="relative pt-1">
          <Search className="w-4 h-4 text-neutral-500 absolute left-3.5 top-4" />
          <input
            type="text"
            placeholder="Volltextsuche in Rohdaten (Lebensmittelname, Kategorie, Metrik-Name oder JSON-Metadata...)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-neutral-950 border border-neutral-800 text-white text-xs outline-none focus:border-purple-500 transition-colors"
          />
        </div>
      </div>

      {/* Chart Render */}
      <ExplorerChart
        dates={timelineData.dates}
        series={timelineData.series}
        chartType={chartType}
        aggregation={aggregation}
      />

      {/* Raw Data Log Table */}
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md space-y-4">
        <div className="flex justify-between items-center">
          <h3 className="text-sm font-semibold text-neutral-200">
            Rohdatenpunkte Log ({tableData.length} Treffer)
          </h3>
          <span className="text-[11px] text-neutral-500">Live TimescaleDB Query</span>
        </div>

        {tableData.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-neutral-800 text-neutral-400 uppercase tracking-wider font-semibold text-[11px]">
                  <th className="pb-3 px-3">Zeitstempel</th>
                  <th className="pb-3 px-3">Quelle</th>
                  <th className="pb-3 px-3">Metrik</th>
                  <th className="pb-3 px-3">Wert</th>
                  <th className="pb-3 px-3">Metadata (JSON)</th>
                  <th className="pb-3 px-3 text-right">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/60">
                {tableData.slice(0, 100).map((pt) => {
                  const foodName = pt.metadata?.food_name || pt.metadata?.name;
                  return (
                    <tr key={pt.id} className="hover:bg-neutral-800/40 transition-colors font-mono">
                      <td className="py-2.5 px-3 text-neutral-400 text-[11px]">
                        {pt.timestamp?.replace("T", " ")?.replace("Z", "") || "N/A"}
                      </td>
                      <td className="py-2.5 px-3 font-bold text-white uppercase text-[10px]">
                        <span className="px-2 py-0.5 rounded bg-neutral-800 text-neutral-300">
                          {pt.source_type || pt.metadata?.source_type || "yazio"}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-purple-300 font-medium">
                        {pt.metric_type}
                      </td>
                      <td className="py-2.5 px-3 text-amber-400 font-bold">
                        {pt.value}
                      </td>
                      <td className="py-2.5 px-3 text-neutral-400 max-w-xs truncate text-[11px]">
                        {foodName ? (
                          <span className="text-emerald-400 font-sans font-semibold mr-1.5">
                            {foodName}
                          </span>
                        ) : null}
                        <span className="text-neutral-500">
                          {JSON.stringify(pt.metadata || {})}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        <button
                          onClick={() => setInspectPoint(pt)}
                          className="p-1 text-neutral-400 hover:text-purple-400 transition-colors"
                          title="JSON Inspizieren"
                        >
                          <ChevronRight className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-neutral-500 py-4">Keine Datenpunkte für die aktuelle Abfrage gefunden.</p>
        )}
      </div>

      {/* JSON Inspector Modal */}
      {inspectPoint && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 animate-in fade-in duration-200">
          <div className="w-full max-w-lg bg-neutral-950 border border-neutral-800 rounded-3xl p-6 shadow-2xl space-y-4">
            <div className="flex justify-between items-center pb-3 border-b border-neutral-800">
              <div className="flex items-center gap-2">
                <Database className="w-4 h-4 text-purple-400" />
                <h3 className="text-sm font-bold text-white">Rohdaten-Punkt Inspektor</h3>
              </div>
              <button
                onClick={() => setInspectPoint(null)}
                className="text-neutral-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-2 text-xs font-mono">
              <div className="flex justify-between text-neutral-400">
                <span>ID:</span>
                <span className="text-white">{inspectPoint.id}</span>
              </div>
              <div className="flex justify-between text-neutral-400">
                <span>Metric Type:</span>
                <span className="text-purple-300 font-bold">{inspectPoint.metric_type}</span>
              </div>
              <div className="flex justify-between text-neutral-400">
                <span>Value:</span>
                <span className="text-amber-400 font-bold">{inspectPoint.value}</span>
              </div>
              <div className="flex justify-between text-neutral-400">
                <span>Timestamp:</span>
                <span className="text-neutral-300">{inspectPoint.timestamp}</span>
              </div>
              <div className="flex justify-between text-neutral-400">
                <span>Idempotency Key:</span>
                <span className="text-neutral-500 text-[10px] truncate max-w-[200px]">{inspectPoint.idempotency_key}</span>
              </div>

              <div className="pt-2">
                <span className="text-neutral-400 block mb-1">Metadata (JSONB):</span>
                <pre className="bg-neutral-900 p-3 rounded-xl border border-neutral-800 text-emerald-300 text-[11px] overflow-x-auto max-h-48">
                  {JSON.stringify(inspectPoint.metadata || {}, null, 2)}
                </pre>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setInspectPoint(null)}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-neutral-800 hover:bg-neutral-700 text-white transition-colors"
              >
                Schließen
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
