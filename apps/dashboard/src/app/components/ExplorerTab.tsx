"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import {
  Search,
  X,
  AreaChart,
  TrendingUp,
  BarChart2,
  Layers,
  Calendar,
  RefreshCw,
  Database,
  Bookmark,
  Save,
  Trash2,
  List,
  Table2,
  LineChart,
} from "lucide-react";
import { apiFetch } from "../lib/api";
import { useI18n, type MessageKey } from "../lib/i18n/provider";
import { describeMetric } from "../lib/metrics/catalog";
import ExplorerMetricSelect, { type MetricOption } from "./ExplorerMetricSelect";
import ExplorerRawTable from "./ExplorerRawTable";
import ExplorerMetricOverview, { type MetricSummaryEntry } from "./ExplorerMetricOverview";

const ExplorerChart = dynamic(() => import("./ExplorerChart"), {
  ssr: false,
  loading: () => <div className="h-80 w-full rounded-2xl border border-slate-200 bg-slate-50" />,
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

/** Which of the three views is on screen. Part of a saved view, so one restores it. */
type ExplorerView = "chart" | "raw" | "overview";

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
    view?: ExplorerView;
  };
  is_shared?: boolean;
  created_at?: string;
}

interface ExplorerTabProps {
  apiBase: string;
  tenantId: string;
}

const COLOR_PALETTE = [
  "#f59e0b",
  "#3b82f6",
  "#10b981",
  "#ec4899",
  "#a855f7",
  "#06b6d4",
  "#f43f5e",
  "#eab308",
];

/**
 * Points fetched for the chart and the table. It is the endpoint's ceiling, and it is
 * a *sample* — the newest N points across every metric. The note under the filter bar
 * says so, and opening one metric from the overview loads that metric on its own
 * instead, which is the honest way to read a metric whose history is longer than the
 * sample.
 */
const POINT_LIMIT = 1000;

/** Metrics preselected on first load, so the chart is not empty on arrival. */
const INITIAL_METRICS = 3;

const VIEW_TABS: Array<{ id: ExplorerView; labelKey: MessageKey; icon: React.ElementType }> = [
  { id: "chart", labelKey: "explorer.tabChart", icon: LineChart },
  { id: "raw", labelKey: "explorer.tabRaw", icon: Table2 },
  { id: "overview", labelKey: "explorer.tabOverview", icon: List },
];

/** `YYYY-MM-DD` in UTC, the bucket every day-wise comparison here is made in. */
function dayOf(isoString?: string): string {
  if (!isoString) return "";
  const date = new Date(isoString);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().split("T")[0];
}

export default function ExplorerTab({ apiBase, tenantId }: ExplorerTabProps) {
  // `locale` because a metric carries both its labels in the registry, and
  // `describeMetric` defaults to German — which showed an English reader every
  // metric name in the other language.
  const { t, locale, formatNumber } = useI18n();

  const [view, setView] = useState<ExplorerView>("chart");
  const [dataPoints, setDataPoints] = useState<DataPointItem[]>([]);
  const [summary, setSummary] = useState<Record<string, MetricSummaryEntry>>({});
  const [summaryFailed, setSummaryFailed] = useState(false);
  const [loading, setLoading] = useState(true);

  /**
   * Set to a metric name when the points on screen were fetched for that metric
   * alone (`?metric_type=`), rather than sampled across all of them. This is what
   * makes the overview's drill-down show a metric's real history instead of
   * whichever of its points happened to survive in the shared sample.
   */
  const [metricScope, setMetricScope] = useState<string | null>(null);

  /**
   * `null` until the reader picks, which is what lets the default below be derived
   * rather than written into state by an effect. Storing the preselection instead
   * needed a second "have I already done this?" flag, because the obvious test —
   * an empty array — is also a legitimate choice, and refilling it on the next
   * render made clearing the selection impossible.
   */
  const [chosenMetrics, setChosenMetrics] = useState<string[] | null>(null);
  const [selectedSource, setSelectedSource] = useState("all");
  const [aggregation, setAggregation] = useState<"sum" | "avg" | "max" | "raw">("sum");
  const [chartType, setChartType] = useState<"area" | "line" | "bar">("area");
  const [dateRangePreset, setDateRangePreset] = useState<
    "7d" | "14d" | "30d" | "90d" | "all" | "custom"
  >("30d");
  const [customStartDate, setCustomStartDate] = useState("");
  const [customEndDate, setCustomEndDate] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  // Kept apart from `searchQuery`: that one is a full-text search over the stored
  // JSON, this one narrows a list of names. Sharing one box would carry a metadata
  // query into the overview and quietly empty it.
  const [overviewSearch, setOverviewSearch] = useState("");
  const [inspectPoint, setInspectPoint] = useState<DataPointItem | null>(null);

  const [savedViews, setSavedViews] = useState<BackendSavedView[]>([]);
  const [activeViewId, setActiveViewId] = useState<string | null>(null);
  const [newViewName, setNewViewName] = useState("");
  const [isSavingView, setIsSavingView] = useState(false);

  /**
   * Newest first, because this is a log: the previous version took the endpoint's
   * default ascending order, so the "raw data" on screen were the *oldest* 500
   * points the workspace had ever stored.
   */
  const loadPoints = useCallback(
    async (scope: string | null) => {
      setLoading(true);
      try {
        const query = new URLSearchParams({ limit: String(POINT_LIMIT), sort: "desc" });
        if (scope) query.set("metric_type", scope);
        const res = await apiFetch(`${apiBase}/api/v1/data/metrics?${query}`, {
          headers: { "X-Tenant-ID": tenantId },
        });
        if (res.ok) {
          const data = await res.json();
          setDataPoints(data.data_points || []);
        }
      } catch (err) {
        console.error("Failed to fetch data points for the raw explorer:", err);
      } finally {
        setLoading(false);
      }
    },
    [apiBase, tenantId],
  );

  /**
   * Counts, ranges and latest timestamps over the tenant's whole history, grouped in
   * SQL. The overview needs this rather than the loaded sample: a metric that stopped
   * arriving a year ago is exactly the one someone opens that view to find, and it is
   * nowhere in the newest thousand points.
   */
  const loadSummary = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/metrics/summary`, {
        headers: { "X-Tenant-ID": tenantId },
      });
      if (!res.ok) {
        setSummaryFailed(true);
        return;
      }
      const data = await res.json();
      setSummary(data.metrics || {});
      setSummaryFailed(false);
    } catch (err) {
      console.error("Failed to fetch the metric summary:", err);
      setSummaryFailed(true);
    }
  }, [apiBase, tenantId]);

  const loadSavedViews = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/explorer/views`, {
        headers: { "X-Tenant-ID": tenantId },
      });
      if (res.ok) {
        const data = await res.json();
        setSavedViews(data.views || []);
      }
    } catch (e) {
      console.error("Failed to fetch saved views:", e);
    }
  }, [apiBase, tenantId]);

  // The work is deferred past the synchronous effect body on purpose, the same way
  // ImportDialog does it: each loader flips a loading flag, and doing that during
  // the effect triggers a cascading render. The cancellation flag stops a slow
  // response from writing state after the tab has been left.
  useEffect(() => {
    if (!tenantId) return;
    let cancelled = false;

    void (async () => {
      await Promise.resolve();
      if (cancelled) return;
      await Promise.all([loadPoints(null), loadSummary(), loadSavedViews()]);
    })();

    return () => {
      cancelled = true;
    };
  }, [tenantId, loadPoints, loadSummary, loadSavedViews]);

  /** Every metric the workspace holds, most-recorded first. */
  const metricOptions = useMemo<MetricOption[]>(() => {
    const fromSummary = Object.entries(summary).map(([key, entry]) => ({
      key,
      count: entry.count,
    }));
    if (fromSummary.length > 0) return fromSummary.sort((a, b) => b.count - a.count);

    // Only until the summary answers, or if it fails: the sample still names the
    // metrics it contains, which is better than an empty picker.
    const counts = new Map<string, number>();
    dataPoints.forEach((p) => counts.set(p.metric_type, (counts.get(p.metric_type) || 0) + 1));
    return Array.from(counts, ([key, count]) => ({ key, count })).sort((a, b) => b.count - a.count);
  }, [summary, dataPoints]);

  /** The reader's choice, or the busiest few metrics so the chart arrives populated. */
  const selectedMetrics = useMemo(
    () => chosenMetrics ?? metricOptions.slice(0, INITIAL_METRICS).map(({ key }) => key),
    [chosenMetrics, metricOptions],
  );

  const availableSources = useMemo(() => {
    const set = new Set<string>();
    dataPoints.forEach((p) => {
      set.add(p.source_type || p.metadata?.source_type || "unknown");
    });
    return Array.from(set).sort();
  }, [dataPoints]);

  const handleSaveCurrentView = async () => {
    if (!newViewName.trim()) return;
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/explorer/views`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Tenant-ID": tenantId },
        body: JSON.stringify({
          name: newViewName.trim(),
          query_config: {
            source: selectedSource,
            metrics: selectedMetrics,
            aggregation,
            chartType,
            dateRangePreset,
            searchQuery,
            view,
          },
          is_shared: false,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setNewViewName("");
        setIsSavingView(false);
        void loadSavedViews();
        if (data.view_id) setActiveViewId(data.view_id);
      }
    } catch (e) {
      console.error("Failed to save the view:", e);
    }
  };

  const handleDeleteView = async (viewId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/explorer/views/${viewId}`, {
        method: "DELETE",
        headers: { "X-Tenant-ID": tenantId },
      });
      if (res.ok) {
        if (activeViewId === viewId) setActiveViewId(null);
        void loadSavedViews();
      }
    } catch (e) {
      console.error("Failed to delete the view:", e);
    }
  };

  const handleLoadView = (saved: BackendSavedView) => {
    setActiveViewId(saved.id);
    const cfg = saved.query_config || {};
    if (cfg.source) setSelectedSource(cfg.source);
    if (cfg.metrics) setChosenMetrics(cfg.metrics);
    if (cfg.aggregation) setAggregation(cfg.aggregation);
    if (cfg.chartType) setChartType(cfg.chartType);
    if (cfg.dateRangePreset) setDateRangePreset(cfg.dateRangePreset);
    if (cfg.searchQuery !== undefined) setSearchQuery(cfg.searchQuery);
    if (cfg.view) setView(cfg.view);
    // A saved view describes a query across all metrics, so a single-metric scope
    // left over from a drill-down would silently contradict it.
    if (metricScope !== null) {
      setMetricScope(null);
      void loadPoints(null);
    }
  };

  /** Changing the selection by hand leaves the drill-down's single-metric fetch. */
  const handleMetricChange = (next: string[]) => {
    setChosenMetrics(next);
    if (metricScope !== null && (next.length !== 1 || next[0] !== metricScope)) {
      setMetricScope(null);
      void loadPoints(null);
    }
  };

  /**
   * The overview's way in: this metric alone, its own history, in the log view.
   *
   * The other filters are cleared rather than carried over, because every one of
   * them can empty the view the reader just asked to see — drilling into an Apple
   * Health metric with the source still set to WHOOP, or with a custom date range
   * from an earlier question, lands on "no data points" for a metric the overview
   * has just finished reporting thousands of.
   */
  const handleShowRaw = (metricType: string) => {
    setChosenMetrics([metricType]);
    setMetricScope(metricType);
    setSearchQuery("");
    setSelectedSource("all");
    setDateRangePreset("all");
    setView("raw");
    void loadPoints(metricType);
  };

  const clearScope = () => {
    setMetricScope(null);
    void loadPoints(null);
  };

  const matchesSearch = useCallback(
    (point: DataPointItem) => {
      if (!searchQuery) return true;
      const needle = searchQuery.toLowerCase();
      return (
        point.metric_type.toLowerCase().includes(needle) ||
        describeMetric(point.metric_type, locale).label.toLowerCase().includes(needle) ||
        JSON.stringify(point.metadata || {})
          .toLowerCase()
          .includes(needle)
      );
    },
    [searchQuery, locale],
  );

  const matchesSource = useCallback(
    (point: DataPointItem) => {
      if (selectedSource === "all") return true;
      return (point.source_type || point.metadata?.source_type || "unknown") === selectedSource;
    },
    [selectedSource],
  );

  const timelineData = useMemo(() => {
    if (selectedMetrics.length === 0 || dataPoints.length === 0) return { dates: [], series: [] };

    const filtered = dataPoints.filter(
      (p) => matchesSource(p) && selectedMetrics.includes(p.metric_type) && matchesSearch(p),
    );

    let dates = Array.from(new Set(filtered.map((p) => dayOf(p.timestamp)).filter(Boolean))).sort();

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

    const series = selectedMetrics.map((metric, idx) => {
      const points = filtered.filter((p) => p.metric_type === metric);
      const values = dates.map((day) => {
        const forDay = points.filter((p) => dayOf(p.timestamp) === day);
        if (forDay.length === 0) return 0;
        if (aggregation === "sum") return forDay.reduce((acc, p) => acc + (p.value || 0), 0);
        if (aggregation === "avg") {
          const sum = forDay.reduce((acc, p) => acc + (p.value || 0), 0);
          return Math.round((sum / forDay.length) * 100) / 100;
        }
        if (aggregation === "max") return Math.max(...forDay.map((p) => p.value || 0));
        return forDay[0].value || 0;
      });

      // The legend reads the metric's name in the reader's language; the key stays
      // the series identity, because that is what the data are keyed by.
      const { label, unit } = describeMetric(metric, locale);
      return {
        metric,
        label: unit ? `${label} (${unit})` : label,
        color: COLOR_PALETTE[idx % COLOR_PALETTE.length],
        values,
      };
    });

    return { dates, series };
  }, [
    dataPoints,
    selectedMetrics,
    matchesSource,
    matchesSearch,
    aggregation,
    dateRangePreset,
    customStartDate,
    customEndDate,
    locale,
  ]);

  const tableData = useMemo(() => {
    return dataPoints.filter((p) => {
      if (!matchesSource(p)) return false;
      if (selectedMetrics.length > 0 && !selectedMetrics.includes(p.metric_type)) return false;

      if (dateRangePreset === "custom") {
        const day = dayOf(p.timestamp);
        if (customStartDate && day < customStartDate) return false;
        if (customEndDate && day > customEndDate) return false;
      }

      return matchesSearch(p);
    });
  }, [
    dataPoints,
    matchesSource,
    matchesSearch,
    selectedMetrics,
    dateRangePreset,
    customStartDate,
    customEndDate,
  ]);

  const refresh = () => {
    void loadPoints(metricScope);
    void loadSummary();
  };

  const sourceFilter = (
    <div className="flex items-center gap-2">
      <span className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-400">
        <Layers className="h-3.5 w-3.5 text-[#0d5c3a]" /> {t("explorer.source")}
      </span>
      <select
        value={selectedSource}
        onChange={(e) => setSelectedSource(e.target.value)}
        className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-bold text-slate-900 outline-none focus:border-[#0d5c3a]"
      >
        <option value="all">{t("explorer.allSources")}</option>
        {availableSources.map((src) => (
          <option key={src} value={src}>
            {src === "unknown" ? t("common.unknown") : src.toUpperCase()}
          </option>
        ))}
      </select>
    </div>
  );

  const periodFilter = (
    <div className="flex items-center gap-2">
      <span className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-400">
        <Calendar className="h-3.5 w-3.5 text-emerald-600" /> {t("explorer.period")}
      </span>
      <div className="flex rounded-2xl border border-slate-200 bg-slate-100 p-1 text-xs">
        {[
          { id: "7d", label: t("quality.windowDays", { count: 7 }) },
          { id: "14d", label: t("quality.windowDays", { count: 14 }) },
          { id: "30d", label: t("quality.windowDays", { count: 30 }) },
          { id: "90d", label: t("quality.windowDays", { count: 90 }) },
          { id: "all", label: t("chart.presetAll") },
          { id: "custom", label: t("chart.presetCustom") },
        ].map((preset) => (
          <button
            key={preset.id}
            onClick={() => setDateRangePreset(preset.id as typeof dateRangePreset)}
            className={`rounded-xl px-3 py-1 font-bold transition-all ${
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
            className="rounded-xl border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-800 outline-none focus:border-[#0d5c3a]"
          />
          <span className="text-slate-400">{t("chart.rangeTo")}</span>
          <input
            type="date"
            value={customEndDate}
            onChange={(e) => setCustomEndDate(e.target.value)}
            className="rounded-xl border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-800 outline-none focus:border-[#0d5c3a]"
          />
        </div>
      )}
    </div>
  );

  const fullTextSearch = (
    <div className="relative">
      <Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-400" />
      <input
        type="text"
        placeholder={t("explorer.searchPlaceholder")}
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        className="w-full rounded-2xl border border-slate-200 bg-white py-2.5 pl-10 pr-4 text-xs text-slate-900 outline-none transition-all focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20"
      />
    </div>
  );

  /*
    A cap the reader is told about. The sample is the newest POINT_LIMIT points across
    every metric, so a chart over a busy workspace can end earlier than the data do —
    and a cap nobody mentions reads as "this is everything".
  */
  const sampleNote =
    metricScope === null && dataPoints.length >= POINT_LIMIT ? (
      <p className="text-[11px] leading-relaxed text-slate-400">
        {t("explorer.sampleNote", {
          count: formatNumber(POINT_LIMIT),
          tab: t("explorer.tabOverview"),
        })}
      </p>
    ) : null;

  const scopeBanner =
    metricScope !== null ? (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-emerald-200 bg-emerald-50 px-3.5 py-2.5">
        <span className="text-[11px] font-bold text-emerald-900">
          {t("explorer.scopeActive", {
            metric: describeMetric(metricScope, locale).label,
          })}
        </span>
        <button
          onClick={clearScope}
          className="rounded-xl border border-emerald-300 bg-white px-2.5 py-1 text-[11px] font-bold text-emerald-800 transition-colors hover:bg-emerald-100"
        >
          {t("explorer.scopeClear")}
        </button>
      </div>
    ) : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2">
            <Database className="h-5 w-5 text-[#0d5c3a]" />
            <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">
              {t("explorer.title")}
            </h1>
          </div>
          <p className="mt-1 text-xs text-slate-500">{t("explorer.subtitle")}</p>
        </div>
        <button
          onClick={refresh}
          className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-700 shadow-xs transition-all hover:bg-slate-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 text-slate-500 ${loading ? "animate-spin" : ""}`} />
          <span>{t("explorer.refresh")}</span>
        </button>
      </div>

      {/* The three views. Which controls make sense depends on the one chosen, so the
          filter bar below is composed per view rather than shown whole and half-inert. */}
      <div className="flex flex-wrap gap-1 rounded-2xl border border-slate-200 bg-slate-100 p-1">
        {VIEW_TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = view === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setView(tab.id)}
              aria-current={isActive}
              className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold transition-all ${
                isActive
                  ? "bg-white text-[#0d5c3a] shadow-xs"
                  : "text-slate-500 hover:text-slate-900"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {t(tab.labelKey)}
            </button>
          );
        })}
      </div>

      {view !== "overview" && (
        <div className="glass-card space-y-3 rounded-3xl border border-slate-200/80 bg-white p-5">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-[#0d5c3a]">
              <Bookmark className="h-3.5 w-3.5" /> {t("explorer.savedViews")}
            </span>
            {!isSavingView ? (
              <button
                onClick={() => setIsSavingView(true)}
                className="flex items-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-1.5 text-xs font-bold text-[#0d5c3a] transition-colors hover:bg-emerald-100"
              >
                <Save className="h-3.5 w-3.5" /> {t("explorer.saveCurrent")}
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  autoFocus
                  placeholder={t("explorer.viewNamePlaceholder")}
                  value={newViewName}
                  onChange={(e) => setNewViewName(e.target.value)}
                  className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-900 outline-none focus:border-[#0d5c3a]"
                />
                <button
                  onClick={handleSaveCurrentView}
                  className="rounded-xl bg-[#0d5c3a] px-3 py-1.5 text-xs font-bold text-white hover:bg-[#08432a]"
                >
                  {t("common.save")}
                </button>
                <button
                  onClick={() => setIsSavingView(false)}
                  aria-label={t("common.cancel")}
                  className="p-1 text-slate-400 hover:text-slate-900"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>

          {savedViews.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {savedViews.map((saved) => (
                <div
                  key={saved.id}
                  onClick={() => handleLoadView(saved)}
                  className={`flex cursor-pointer items-center gap-2 rounded-2xl border px-3.5 py-1.5 text-xs font-semibold transition-all ${
                    activeViewId === saved.id
                      ? "border-[#0d5c3a] bg-[#0d5c3a] text-white shadow-xs"
                      : "border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300 hover:text-slate-900"
                  }`}
                >
                  <span>{saved.name}</span>
                  <button
                    onClick={(e) => handleDeleteView(saved.id, e)}
                    className="ml-1 text-slate-400 transition-colors hover:text-rose-500"
                    title={t("explorer.deleteView")}
                    aria-label={t("explorer.deleteView")}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-400">{t("explorer.noViews")}</p>
          )}
        </div>
      )}

      {view === "chart" && (
        <>
          <div className="glass-card space-y-4 rounded-3xl border border-slate-200/80 bg-white p-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex flex-wrap items-center gap-4">
                <ExplorerMetricSelect
                  options={metricOptions}
                  selected={selectedMetrics}
                  onChange={handleMetricChange}
                />
                {sourceFilter}
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-1 rounded-2xl border border-slate-200 bg-slate-100 p-1 text-xs">
                  <span className="px-2 text-[10px] font-bold text-slate-400">
                    {t("explorer.aggregation")}
                  </span>
                  {(
                    [
                      { id: "sum", label: "SUM", titleKey: "explorer.dailySum" },
                      { id: "avg", label: "Ø AVG", titleKey: "explorer.dailyAverage" },
                      { id: "max", label: "MAX", titleKey: "explorer.dailyMax" },
                    ] as const
                  ).map((mode) => (
                    <button
                      key={mode.id}
                      onClick={() => setAggregation(mode.id)}
                      title={t(mode.titleKey)}
                      className={`rounded-xl px-2.5 py-1 font-bold transition-all ${
                        aggregation === mode.id
                          ? "bg-[#0d5c3a] text-white shadow-xs"
                          : "text-slate-500 hover:text-slate-900"
                      }`}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>

                <div className="flex rounded-2xl border border-slate-200 bg-slate-100 p-1 text-xs">
                  {(
                    [
                      { id: "area", icon: AreaChart, titleKey: "chart.typeArea" },
                      { id: "line", icon: TrendingUp, titleKey: "chart.typeLine" },
                      { id: "bar", icon: BarChart2, titleKey: "chart.typeBar" },
                    ] as const
                  ).map((option) => {
                    const Icon = option.icon;
                    return (
                      <button
                        key={option.id}
                        onClick={() => setChartType(option.id)}
                        title={t(option.titleKey)}
                        aria-label={t(option.titleKey)}
                        className={`rounded-xl p-1.5 transition-all ${
                          chartType === option.id
                            ? "bg-[#0d5c3a] text-white shadow-xs"
                            : "text-slate-500 hover:text-slate-900"
                        }`}
                      >
                        <Icon className="h-4 w-4" />
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {periodFilter}
            {scopeBanner}
            {sampleNote}
          </div>

          <ExplorerChart
            dates={timelineData.dates}
            series={timelineData.series}
            chartType={chartType}
            aggregation={aggregation}
          />
        </>
      )}

      {view === "raw" && (
        <>
          <div className="glass-card space-y-4 rounded-3xl border border-slate-200/80 bg-white p-6">
            <div className="flex flex-wrap items-center gap-4">
              <ExplorerMetricSelect
                options={metricOptions}
                selected={selectedMetrics}
                onChange={handleMetricChange}
              />
              {sourceFilter}
            </div>
            {periodFilter}
            {fullTextSearch}
            {scopeBanner}
            {sampleNote}
          </div>

          <ExplorerRawTable points={tableData} onInspect={setInspectPoint} />
        </>
      )}

      {view === "overview" && (
        <>
          <div className="glass-card rounded-3xl border border-slate-200/80 bg-white p-5">
            <div className="relative">
              <Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-400" />
              <input
                type="text"
                placeholder={t("explorer.metricFilterPlaceholder")}
                value={overviewSearch}
                onChange={(e) => setOverviewSearch(e.target.value)}
                className="w-full rounded-2xl border border-slate-200 bg-white py-2.5 pl-10 pr-4 text-xs text-slate-900 outline-none transition-all focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20"
              />
            </div>
          </div>

          <ExplorerMetricOverview
            summary={summary}
            failed={summaryFailed}
            search={overviewSearch}
            onShowRaw={handleShowRaw}
          />
        </>
      )}

      {inspectPoint && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-md">
          <div className="w-full max-w-lg space-y-4 rounded-3xl border border-slate-200/90 bg-white p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Database className="h-4 w-4 text-[#0d5c3a]" />
                <h3 className="text-sm font-bold text-slate-900">{t("explorer.inspectorTitle")}</h3>
              </div>
              <button
                onClick={() => setInspectPoint(null)}
                aria-label={t("common.close")}
                className="text-slate-400 hover:text-slate-900"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-2 font-mono text-xs">
              <div className="flex justify-between gap-4 text-slate-500">
                <span>ID</span>
                <span className="truncate font-bold text-slate-900">{inspectPoint.id}</span>
              </div>
              <div className="flex justify-between gap-4 text-slate-500">
                <span>{t("explorer.colMetric")}</span>
                <span className="truncate font-bold text-[#0d5c3a]">
                  {inspectPoint.metric_type}
                </span>
              </div>
              <div className="flex justify-between gap-4 text-slate-500">
                <span>{t("explorer.colValue")}</span>
                <span className="font-bold text-slate-900">
                  {inspectPoint.value}
                  {describeMetric(inspectPoint.metric_type, locale).unit && (
                    <span className="ml-1 font-normal text-slate-500">
                      {describeMetric(inspectPoint.metric_type, locale).unit}
                    </span>
                  )}
                </span>
              </div>
              <div className="flex justify-between gap-4 text-slate-500">
                <span>{t("explorer.colTimestamp")}</span>
                <span className="text-slate-700">{inspectPoint.timestamp}</span>
              </div>
              <div className="flex justify-between gap-4 text-slate-500">
                <span>Idempotency key</span>
                <span className="max-w-50 truncate text-[10px] text-slate-400">
                  {inspectPoint.idempotency_key}
                </span>
              </div>

              <div className="pt-2">
                <span className="mb-1 block font-sans font-bold text-slate-500">
                  {t("explorer.inspectorMetadata")}
                </span>
                <pre className="max-h-48 overflow-x-auto rounded-2xl border border-slate-800 bg-slate-950 p-3 text-[11px] text-emerald-400">
                  {JSON.stringify(inspectPoint.metadata || {}, null, 2)}
                </pre>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setInspectPoint(null)}
                className="rounded-2xl border border-slate-200 bg-slate-100 px-4 py-2 text-xs font-bold text-slate-700 transition-colors hover:bg-slate-200"
              >
                {t("common.close")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
