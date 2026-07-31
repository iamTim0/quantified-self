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
    <div className="space-y-6">
      {/* Header & Refresh */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-[#0d5c3a]" />
            <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Raw Data Explorer</h1>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Direkter Zugriff auf alle Rohdatenpunkte in TimescaleDB. Ansichten werden dauerhaft in PostgreSQL gespeichert.
          </p>
        </div>
        <button
          onClick={fetchAllMetrics}
          className="flex items-center gap-2 px-4 py-2.5 text-xs font-bold rounded-2xl bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 transition-all shadow-xs"
        >
          <RefreshCw className={`w-3.5 h-3.5 text-slate-500 ${loading ? "animate-spin" : ""}`} />
          <span>Daten Aktualisieren</span>
        </button>
      </div>

      {/* SaaS Multi-Tenant PostgreSQL Saved Views Bar */}
      <div className="glass-card p-5 bg-white border border-slate-200/80 rounded-3xl space-y-3">
        <div className="flex justify-between items-center">
          <span className="text-xs font-bold uppercase tracking-wider text-[#0d5c3a] flex items-center gap-1.5">
            <Bookmark className="w-3.5 h-3.5" /> Gespeicherte Ansichten (PostgreSQL Synced)
          </span>
          {!isSavingView ? (
            <button
              onClick={() => setIsSavingView(true)}
              className="flex items-center gap-1.5 text-xs font-bold px-3.5 py-1.5 rounded-xl bg-emerald-50 text-[#0d5c3a] border border-emerald-200 hover:bg-emerald-100 transition-colors"
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
                className="px-3 py-1.5 rounded-xl bg-white border border-slate-200 text-slate-900 text-xs outline-none focus:border-[#0d5c3a]"
              />
              <button
                onClick={handleSaveCurrentView}
                className="px-3 py-1.5 rounded-xl bg-[#0d5c3a] text-white text-xs font-bold hover:bg-[#08432a]"
              >
                Speichern
              </button>
              <button
                onClick={() => setIsSavingView(false)}
                className="p-1 text-slate-400 hover:text-slate-900"
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
                  className={`flex items-center gap-2 px-3.5 py-1.5 rounded-2xl border text-xs font-semibold cursor-pointer transition-all ${
                    isActive
                      ? "bg-[#0d5c3a] text-white border-[#0d5c3a] shadow-xs"
                      : "bg-slate-50 border-slate-200 text-slate-600 hover:text-slate-900 hover:border-slate-300"
                  }`}
                >
                  <span>{view.name}</span>
                  <button
                    onClick={(e) => handleDeleteView(view.id, e)}
                    className="text-slate-400 hover:text-rose-500 transition-colors ml-1"
                    title="Ansicht aus PostgreSQL löschen"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-slate-400">
            Noch keine benutzerdefinierten Ansichten in PostgreSQL gespeichert. Konfiguriere Filter und klicke auf "Aktuelle Ansicht Speichern".
          </p>
        )}
      </div>

      {/* Raw Query & Control Bar */}
      <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-5">
        {/* Controls Row: Source, Date Range, Aggregation, Chart Type */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-4">
          <div className="flex flex-wrap items-center gap-4">
            {/* Source Provider Filter */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-[#0d5c3a]" /> Quelle:
              </span>
              <select
                value={selectedSource}
                onChange={(e) => setSelectedSource(e.target.value)}
                className="px-3 py-1.5 rounded-2xl bg-slate-50 border border-slate-200 text-slate-900 text-xs font-bold outline-none focus:border-[#0d5c3a]"
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
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5 text-emerald-600" /> Zeitraum:
              </span>
              <div className="flex bg-slate-100 border border-slate-200 rounded-2xl p-1 text-xs">
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
                    className={`px-3 py-1 rounded-xl font-bold transition-all ${
                      dateRangePreset === preset.id
                        ? "bg-[#0d5c3a] text-white shadow-xs"
                        : "text-slate-500 hover:text-slate-900"
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
                    className="bg-white border border-slate-200 text-slate-800 rounded-xl px-2.5 py-1 outline-none focus:border-[#0d5c3a] text-[11px]"
                  />
                  <span className="text-slate-400">bis</span>
                  <input
                    type="date"
                    value={customEndDate}
                    onChange={(e) => setCustomEndDate(e.target.value)}
                    className="bg-white border border-slate-200 text-slate-800 rounded-xl px-2.5 py-1 outline-none focus:border-[#0d5c3a] text-[11px]"
                  />
                </div>
              )}
            </div>
          </div>

          {/* Aggregation Mode & Chart Type Selector */}
          <div className="flex flex-wrap items-center gap-3">
            {/* Aggregation Mode */}
            <div className="flex items-center gap-1 bg-slate-100 border border-slate-200 rounded-2xl p-1 text-xs">
              <span className="text-[10px] text-slate-400 font-bold px-2">Aggregat:</span>
              <button
                onClick={() => setAggregation("sum")}
                className={`px-2.5 py-1 rounded-xl transition-all font-bold ${
                  aggregation === "sum" ? "bg-[#0d5c3a] text-white shadow-xs" : "text-slate-500 hover:text-slate-900"
                }`}
                title="Tages-Summe"
              >
                SUM
              </button>
              <button
                onClick={() => setAggregation("avg")}
                className={`px-2.5 py-1 rounded-xl transition-all font-bold ${
                  aggregation === "avg" ? "bg-[#0d5c3a] text-white shadow-xs" : "text-slate-500 hover:text-slate-900"
                }`}
                title="Tages-Durchschnitt"
              >
                Ø AVG
              </button>
              <button
                onClick={() => setAggregation("max")}
                className={`px-2.5 py-1 rounded-xl transition-all font-bold ${
                  aggregation === "max" ? "bg-[#0d5c3a] text-white shadow-xs" : "text-slate-500 hover:text-slate-900"
                }`}
                title="Maximalwert"
              >
                MAX
              </button>
            </div>

            {/* Chart Type Selector */}
            <div className="flex bg-slate-100 border border-slate-200 rounded-2xl p-1 text-xs">
              <button
                onClick={() => setChartType("area")}
                className={`p-1.5 rounded-xl transition-all ${
                  chartType === "area" ? "bg-[#0d5c3a] text-white shadow-xs" : "text-slate-500 hover:text-slate-900"
                }`}
                title="Flächendiagramm"
              >
                <AreaChart className="w-4 h-4" />
              </button>
              <button
                onClick={() => setChartType("line")}
                className={`p-1.5 rounded-xl transition-all ${
                  chartType === "line" ? "bg-[#0d5c3a] text-white shadow-xs" : "text-slate-500 hover:text-slate-900"
                }`}
                title="Liniendiagramm"
              >
                <TrendingUp className="w-4 h-4" />
              </button>
              <button
                onClick={() => setChartType("bar")}
                className={`p-1.5 rounded-xl transition-all ${
                  chartType === "bar" ? "bg-[#0d5c3a] text-white shadow-xs" : "text-slate-500 hover:text-slate-900"
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
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5 text-[#0d5c3a]" /> Ausgewählte Metriken ({selectedMetrics.length}):
            </span>
            <div className="flex items-center gap-2 text-[11px]">
              <button
                onClick={selectAllMetrics}
                className="text-[#0d5c3a] hover:underline font-bold"
              >
                Alle auswählen
              </button>
              <span className="text-slate-300">•</span>
              <button
                onClick={clearMetrics}
                className="text-slate-400 hover:text-slate-900 font-bold"
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
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-2xl border text-xs font-mono transition-all ${
                    selected
                      ? "bg-[#0d5c3a] text-white border-[#0d5c3a] shadow-xs font-bold"
                      : "bg-slate-50 border-slate-200 text-slate-600 hover:text-slate-900 hover:border-slate-300"
                  }`}
                >
                  {selected && <Check className="w-3 h-3 text-white shrink-0" />}
                  <span>{m}</span>
                  <span
                    className={`text-[9px] px-1.5 py-0.2 rounded-full font-sans ${
                      selected ? "bg-white/20 text-white" : "bg-slate-200 text-slate-500"
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
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-4" />
          <input
            type="text"
            placeholder="Volltextsuche in Rohdaten (Lebensmittelname, Kategorie, Metrik-Name oder JSON-Metadata...)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-xs outline-none focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 transition-all"
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
      <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-4">
        <div className="flex justify-between items-center">
          <h3 className="text-sm font-bold text-slate-900">
            Rohdatenpunkte Log ({tableData.length} Treffer)
          </h3>
          <span className="text-[11px] text-slate-400 font-mono">Live TimescaleDB Query</span>
        </div>

        {tableData.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-400 uppercase tracking-wider font-bold text-[11px]">
                  <th className="pb-3 px-3">Zeitstempel</th>
                  <th className="pb-3 px-3">Quelle</th>
                  <th className="pb-3 px-3">Metrik</th>
                  <th className="pb-3 px-3">Wert</th>
                  <th className="pb-3 px-3">Metadata (JSON)</th>
                  <th className="pb-3 px-3 text-right">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {tableData.slice(0, 100).map((pt) => {
                  const foodName = pt.metadata?.food_name || pt.metadata?.name;
                  return (
                    <tr key={pt.id} className="hover:bg-slate-50 transition-colors font-mono">
                      <td className="py-2.5 px-3 text-slate-500 text-[11px]">
                        {pt.timestamp?.replace("T", " ")?.replace("Z", "") || "N/A"}
                      </td>
                      <td className="py-2.5 px-3 font-bold text-slate-900 uppercase text-[10px]">
                        <span className="px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 border border-slate-200">
                          {pt.source_type || pt.metadata?.source_type || "yazio"}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-[#0d5c3a] font-bold">
                        {pt.metric_type}
                      </td>
                      <td className="py-2.5 px-3 text-slate-900 font-bold">
                        {pt.value}
                      </td>
                      <td className="py-2.5 px-3 text-slate-500 max-w-xs truncate text-[11px]">
                        {foodName ? (
                          <span className="text-emerald-700 font-sans font-bold mr-1.5">
                            {foodName}
                          </span>
                        ) : null}
                        <span className="text-slate-400">
                          {JSON.stringify(pt.metadata || {})}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        <button
                          onClick={() => setInspectPoint(pt)}
                          className="p-1 text-slate-400 hover:text-[#0d5c3a] transition-colors"
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
          <p className="text-xs text-slate-400 py-4">Keine Datenpunkte für die aktuelle Abfrage gefunden.</p>
        )}
      </div>

      {/* JSON Inspector Modal */}
      {inspectPoint && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-md p-4 animate-in fade-in duration-200">
          <div className="w-full max-w-lg bg-white border border-slate-200/90 rounded-3xl p-6 shadow-2xl space-y-4">
            <div className="flex justify-between items-center pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2">
                <Database className="w-4 h-4 text-[#0d5c3a]" />
                <h3 className="text-sm font-bold text-slate-900">Rohdaten-Punkt Inspektor</h3>
              </div>
              <button
                onClick={() => setInspectPoint(null)}
                className="text-slate-400 hover:text-slate-900"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-2 text-xs font-mono">
              <div className="flex justify-between text-slate-500">
                <span>ID:</span>
                <span className="text-slate-900 font-bold">{inspectPoint.id}</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Metric Type:</span>
                <span className="text-[#0d5c3a] font-bold">{inspectPoint.metric_type}</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Value:</span>
                <span className="text-slate-900 font-bold">{inspectPoint.value}</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Timestamp:</span>
                <span className="text-slate-700">{inspectPoint.timestamp}</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Idempotency Key:</span>
                <span className="text-slate-400 text-[10px] truncate max-w-[200px]">{inspectPoint.idempotency_key}</span>
              </div>

              <div className="pt-2">
                <span className="text-slate-500 block mb-1 font-sans font-bold">Metadata (JSONB):</span>
                <pre className="bg-slate-950 p-3 rounded-2xl border border-slate-800 text-emerald-400 text-[11px] overflow-x-auto max-h-48">
                  {JSON.stringify(inspectPoint.metadata || {}, null, 2)}
                </pre>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setInspectPoint(null)}
                className="px-4 py-2 text-xs font-bold rounded-2xl bg-slate-100 border border-slate-200 hover:bg-slate-200 text-slate-700 transition-colors"
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
