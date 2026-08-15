"use client";

import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
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
import { describeMetric, type Aggregation } from "../lib/metrics/catalog";
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
  sample_count?: number;
  is_derived?: boolean;
  resolution?: string;
}

type Resolution = "auto" | "raw" | "minute" | "hour" | "day";

/** Which of the three views is on screen. Part of a saved view, so one restores it. */
type ExplorerView = "chart" | "raw" | "overview";

export interface BackendSavedView {
  id: string;
  name: string;
  query_config: {
    /** Connector instance ID; legacy views may still contain a source type. */
    source?: string;
    metrics?: string[];
    aggregation?: "sum" | "avg" | "max" | "raw";
    chartType?: "area" | "line" | "bar";
    dateRangePreset?: "7d" | "14d" | "30d" | "90d" | "all" | "custom";
    searchQuery?: string;
    view?: ExplorerView;
    importResolution?: Exclude<Resolution, "auto">;
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

const SERIES_POINT_LIMIT = 10000;
const RAW_POINT_LIMIT = 10000;

/** Metrics preselected on first load, so the chart is not empty on arrival. */
const INITIAL_METRICS = 3;

const VIEW_TABS: Array<{ id: ExplorerView; labelKey: MessageKey; icon: React.ElementType }> = [
  { id: "chart", labelKey: "explorer.tabChart", icon: LineChart },
  { id: "raw", labelKey: "explorer.tabRaw", icon: Table2 },
  { id: "overview", labelKey: "explorer.tabOverview", icon: List },
];

const AGGREGATION_LABEL_KEYS: Record<Aggregation, MessageKey> = {
  average: "explorer.aggAverage",
  sum: "explorer.aggSum",
  last: "explorer.aggLast",
  max: "explorer.aggMax",
};

/** `YYYY-MM-DD` in UTC, the bucket every day-wise comparison here is made in. */
function dayOf(isoString?: string): string {
  if (!isoString) return "";
  const date = new Date(isoString);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().split("T")[0];
}

function queryWindow(
  preset: "7d" | "14d" | "30d" | "90d" | "all" | "custom",
  customStart: string,
  customEnd: string,
): { start?: string; end?: string } {
  if (preset === "all") return {};
  if (preset === "custom") {
    return {
      start: customStart ? new Date(`${customStart}T00:00:00Z`).toISOString() : undefined,
      end: customEnd ? new Date(`${customEnd}T23:59:59.999Z`).toISOString() : undefined,
    };
  }
  const days = Number.parseInt(preset, 10);
  const now = new Date();
  const end = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 23, 59, 59, 999),
  );
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - days + 1);
  start.setUTCHours(0, 0, 0, 0);
  return { start: start.toISOString(), end: end.toISOString() };
}

function dayKeysBetween(start: string, end: string): string[] {
  const first = new Date(start);
  const last = new Date(end);
  if (Number.isNaN(first.getTime()) || Number.isNaN(last.getTime()) || first > last) return [];

  const keys: string[] = [];
  const cursor = new Date(first);
  while (cursor <= last && keys.length < SERIES_POINT_LIMIT) {
    keys.push(cursor.toISOString().split("T")[0]);
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return keys;
}

function queryLimit(
  preset: "7d" | "14d" | "30d" | "90d" | "all" | "custom",
  customStart: string,
  customEnd: string,
): number {
  if (preset === "all") return SERIES_POINT_LIMIT;
  if (preset === "custom" && customStart && customEnd) {
    const start = new Date(`${customStart}T00:00:00.000Z`);
    const end = new Date(`${customEnd}T00:00:00.000Z`);
    const days = Math.floor((end.getTime() - start.getTime()) / 86_400_000) + 1;
    return Math.min(SERIES_POINT_LIMIT, Math.max(1, days));
  }
  return Number.parseInt(preset, 10);
}

function pointResolution(point: DataPointItem): string {
  return point.resolution || point.metadata?.resolution || "raw";
}

function pointBucket(point: DataPointItem): string {
  return pointResolution(point) === "day" ? dayOf(point.timestamp) : point.timestamp;
}

function chartAggregation(aggregation: Aggregation): "sum" | "avg" | "max" | "raw" {
  if (aggregation === "sum") return "sum";
  if (aggregation === "average") return "avg";
  if (aggregation === "max") return "max";
  return "raw";
}

function mergePoints(pointSets: DataPointItem[][]): DataPointItem[] {
  const byId = new Map<string, DataPointItem>();
  pointSets.flat().forEach((point) => byId.set(point.id, point));
  return Array.from(byId.values()).sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
  );
}

interface ExplorerSource {
  id: string;
  source_type: string;
  display_name?: string;
}

export default function ExplorerTab({ apiBase, tenantId }: ExplorerTabProps) {
  // `locale` because a metric carries both its labels in the registry, and
  // `describeMetric` defaults to German — which showed an English reader every
  // metric name in the other language.
  const { t, locale } = useI18n();

  const [view, setView] = useState<ExplorerView>("chart");
  const [chartPoints, setChartPoints] = useState<DataPointItem[]>([]);
  const [rawPoints, setRawPoints] = useState<DataPointItem[]>([]);
  const [summary, setSummary] = useState<Record<string, MetricSummaryEntry>>({});
  const [knownMetricTypes, setKnownMetricTypes] = useState<string[]>([]);
  const [metricDefinitions, setMetricDefinitions] = useState<
    Record<string, NonNullable<MetricSummaryEntry["definition"]>>
  >({});
  const [sources, setSources] = useState<ExplorerSource[]>([]);
  const [summaryFailed, setSummaryFailed] = useState(false);
  const [loading, setLoading] = useState(true);

  /**
   * Set to a metric name when the overview drill-down has narrowed the query to one
   * metric (`?metric_type=`). The query is still per metric everywhere; this state
   * only controls the explanatory banner and the way back to the full selection.
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
  const [importResolution, setImportResolution] = useState<Resolution>("auto");
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

  const chartRequestId = useRef(0);
  const rawRequestId = useRef(0);

  /**
   * Fetch one metric at a time. Core applies the metric registry's aggregation to
   * rollups; the dashboard never combines different metric types with one operator.
   */
  const requestMetricPoints = useCallback(
    async (
      metric: string,
      resolution: "day" | "raw",
      sourceRef: string,
    ): Promise<DataPointItem[]> => {
      const query = new URLSearchParams({
        metric_type: metric,
        limit: String(
          resolution === "day"
            ? queryLimit(dateRangePreset, customStartDate, customEndDate)
            : RAW_POINT_LIMIT,
        ),
        // Each metric is queried independently, so descending order returns its
        // newest complete series instead of letting busy metrics consume a shared cap.
        sort: "desc",
        resolution,
      });

      if (sourceRef !== "all") {
        const source = sources.find((item) => item.id === sourceRef);
        query.set(source ? "source_id" : "source_type", sourceRef);
      }

      const window = queryWindow(dateRangePreset, customStartDate, customEndDate);
      if (window.start) query.set("start_time", window.start);
      if (window.end) query.set("end_time", window.end);

      const res = await apiFetch(`${apiBase}/api/v1/data/metrics?${query}`, {
        headers: { "X-Tenant-ID": tenantId },
      });
      if (!res.ok) return [];

      const data = (await res.json()) as {
        data_points?: DataPointItem[];
        resolution?: string;
      };
      return (data.data_points || []).map((point) => ({
        ...point,
        // The response resolution is important for legacy data where Core has to
        // fall back to raw points because no rollup covers that interval.
        resolution: point.resolution || point.metadata?.resolution || data.resolution || resolution,
      }));
    },
    [apiBase, tenantId, sources, dateRangePreset, customStartDate, customEndDate],
  );

  const loadChartPoints = useCallback(
    async (metrics: string[]) => {
      const requestId = ++chartRequestId.current;
      if (metrics.length === 0) {
        setChartPoints([]);
        return;
      }

      setLoading(true);
      setChartPoints([]);
      try {
        const sourceRefs =
          selectedSource === "all" && sources.length > 0
            ? sources.map((source) => source.id)
            : [selectedSource];
        const pointSets = await Promise.all(
          metrics.flatMap((metric) =>
            sourceRefs.map((sourceRef) => requestMetricPoints(metric, "day", sourceRef)),
          ),
        );
        if (requestId === chartRequestId.current) setChartPoints(mergePoints(pointSets));
      } catch (err) {
        if (requestId === chartRequestId.current) {
          console.error("Failed to fetch metric series for the explorer:", err);
          setChartPoints([]);
        }
      } finally {
        if (requestId === chartRequestId.current) setLoading(false);
      }
    },
    [requestMetricPoints, selectedSource, sources],
  );

  const loadRawPoints = useCallback(
    async (metrics: string[]) => {
      const requestId = ++rawRequestId.current;
      if (metrics.length === 0) {
        setRawPoints([]);
        return;
      }

      setLoading(true);
      setRawPoints([]);
      try {
        const sourceRefs =
          selectedSource === "all" && sources.length > 0
            ? sources.map((source) => source.id)
            : [selectedSource];
        const pointSets = await Promise.all(
          metrics.flatMap((metric) =>
            sourceRefs.map((sourceRef) => requestMetricPoints(metric, "raw", sourceRef)),
          ),
        );
        if (requestId === rawRequestId.current) setRawPoints(mergePoints(pointSets));
      } catch (err) {
        if (requestId === rawRequestId.current) {
          console.error("Failed to fetch raw metric points for the explorer:", err);
          setRawPoints([]);
        }
      } finally {
        if (requestId === rawRequestId.current) setLoading(false);
      }
    },
    [requestMetricPoints, selectedSource, sources],
  );

  /**
   * Counts, ranges and latest timestamps over the tenant's whole history, grouped in
   * SQL. The overview needs this rather than the loaded chart series: a metric that stopped
   * arriving a year ago is exactly the one someone opens that view to find, and it is
   * not guaranteed to occur in a recent chart series.
   */
  const loadSummary = useCallback(async (): Promise<Record<string, MetricSummaryEntry>> => {
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/metrics/summary`, {
        headers: { "X-Tenant-ID": tenantId },
      });
      if (!res.ok) {
        setSummaryFailed(true);
        return {};
      }
      const data = await res.json();
      const metrics = (data.metrics || {}) as Record<string, MetricSummaryEntry>;
      setSummary(metrics);
      setMetricDefinitions((previous) => ({
        ...previous,
        ...Object.fromEntries(
          Object.entries(metrics).flatMap(([key, entry]) =>
            entry.definition ? [[key, entry.definition]] : [],
          ),
        ),
      }));
      setSummaryFailed(false);
      return metrics;
    } catch (err) {
      console.error("Failed to fetch the metric summary:", err);
      setSummaryFailed(true);
      return {};
    }
  }, [apiBase, tenantId]);

  const loadMetricTypes = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/metrics/types`, {
        headers: { "X-Tenant-ID": tenantId },
      });
      if (!res.ok) return;
      const data = (await res.json()) as {
        metric_types?: string[];
        definitions?: Record<string, NonNullable<MetricSummaryEntry["definition"]>>;
      };
      setKnownMetricTypes(data.metric_types || []);
      setMetricDefinitions((previous) => ({ ...previous, ...data.definitions }));
    } catch (err) {
      console.error("Failed to fetch the metric types:", err);
    }
  }, [apiBase, tenantId]);

  const loadSources = useCallback(async () => {
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/sources`, {
        headers: { "X-Tenant-ID": tenantId },
      });
      if (!res.ok) return;
      const data = (await res.json()) as { connectors?: ExplorerSource[] };
      setSources(data.connectors || []);
    } catch (err) {
      console.error("Failed to fetch the connector list:", err);
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
      await Promise.all([loadSummary(), loadMetricTypes(), loadSources(), loadSavedViews()]);
      if (!cancelled) setLoading(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [tenantId, loadSummary, loadMetricTypes, loadSources, loadSavedViews]);

  const visiblePoints = view === "raw" ? rawPoints : chartPoints;

  /** Every metric the workspace holds, most-recorded first. */
  const metricOptions = useMemo<MetricOption[]>(() => {
    const fromSummary = Object.entries(summary).map(([key, entry]) => ({
      key,
      count: entry.count,
    }));
    if (fromSummary.length > 0) return fromSummary.sort((a, b) => b.count - a.count);

    // The type endpoint keeps the picker useful even when summary statistics are
    // temporarily unavailable; it does not require a broad data-point query.
    if (knownMetricTypes.length > 0) {
      return knownMetricTypes.map((key) => ({ key, count: 0 }));
    }

    // Last-resort fallback for older deployments that do not expose the type route.
    const counts = new Map<string, number>();
    visiblePoints.forEach((p) => counts.set(p.metric_type, (counts.get(p.metric_type) || 0) + 1));
    return Array.from(counts, ([key, count]) => ({ key, count })).sort((a, b) => b.count - a.count);
  }, [summary, knownMetricTypes, visiblePoints]);

  /** The reader's choice, or the busiest few metrics so the chart arrives populated. */
  const selectedMetrics = useMemo(
    () => chosenMetrics ?? metricOptions.slice(0, INITIAL_METRICS).map(({ key }) => key),
    [chosenMetrics, metricOptions],
  );

  const metricAggregation = useCallback(
    (metric: string): Aggregation =>
      metricDefinitions[metric]?.aggregation ||
      summary[metric]?.definition?.aggregation ||
      describeMetric(metric, locale).aggregation,
    [metricDefinitions, summary, locale],
  );

  /** ExplorerChart accepts one tooltip mode; only expose it when all series agree. */
  const chartTooltipAggregation = useMemo(() => {
    const aggregations = new Set(selectedMetrics.map((metric) => metricAggregation(metric)));
    return aggregations.size === 1
      ? chartAggregation(Array.from(aggregations)[0])
      : ("raw" as const);
  }, [selectedMetrics, metricAggregation]);

  useEffect(() => {
    if (!tenantId || view !== "chart") return;
    void loadChartPoints(selectedMetrics);
  }, [tenantId, view, selectedMetrics, loadChartPoints]);

  useEffect(() => {
    if (!tenantId || view !== "raw") return;
    void loadRawPoints(selectedMetrics);
  }, [tenantId, view, selectedMetrics, loadRawPoints]);

  const saveImportResolution = useCallback(
    async (resolution: Resolution) => {
      if (resolution === "auto" || selectedMetrics.length === 0) return;
      await Promise.all(
        selectedMetrics.map((metric) =>
          apiFetch(`${apiBase}/api/v1/data/metrics/ingest-policy/${metric}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json", "X-Tenant-ID": tenantId },
            body: JSON.stringify({ resolution, raw_retention_days: 90 }),
          }),
        ),
      );
      if (view === "raw") await loadRawPoints(selectedMetrics);
      else await loadChartPoints(selectedMetrics);
    },
    [apiBase, tenantId, selectedMetrics, loadChartPoints, loadRawPoints, view],
  );

  const availableSources = useMemo<ExplorerSource[]>(() => {
    if (sources.length > 0) {
      if (selectedSource !== "all" && !sources.some((source) => source.id === selectedSource)) {
        return [{ id: selectedSource, source_type: selectedSource }, ...sources];
      }
      return sources;
    }

    const byId = new Map<string, ExplorerSource>();
    visiblePoints.forEach((point) => {
      const id = point.source_id || point.source_type || "unknown";
      byId.set(id, {
        id,
        source_type: point.source_type || point.metadata?.source_type || "unknown",
      });
    });
    return Array.from(byId.values()).sort((a, b) =>
      `${a.source_type}:${a.id}`.localeCompare(`${b.source_type}:${b.id}`),
    );
  }, [sources, visiblePoints, selectedSource]);

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
            aggregation: chartTooltipAggregation,
            chartType,
            dateRangePreset,
            searchQuery,
            view,
            importResolution: importResolution === "auto" ? undefined : importResolution,
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
    if (cfg.chartType) setChartType(cfg.chartType);
    if (cfg.dateRangePreset) setDateRangePreset(cfg.dateRangePreset);
    if (cfg.searchQuery !== undefined) setSearchQuery(cfg.searchQuery);
    if (cfg.view) setView(cfg.view);
    if (cfg.importResolution) setImportResolution(cfg.importResolution);
    // A saved view describes a query across all metrics, so a single-metric scope
    // left over from a drill-down would silently contradict it.
    if (metricScope !== null) {
      setMetricScope(null);
    }
  };

  const handleImportResolutionChange = (resolution: Resolution) => {
    setImportResolution(resolution);
    void saveImportResolution(resolution);
  };

  /** Changing the selection triggers one fresh request per selected metric. */
  const handleMetricChange = (next: string[]) => {
    setChosenMetrics(next);
    if (metricScope !== null && (next.length !== 1 || next[0] !== metricScope)) {
      setMetricScope(null);
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
  };

  const clearScope = () => {
    setMetricScope(null);
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
      if (point.source_id === selectedSource) return true;
      // Keep old saved views usable when they stored a source type rather than
      // the connector instance ID now used by the picker.
      if (sources.some((source) => source.id === selectedSource)) return false;
      return (point.source_type || point.metadata?.source_type || "unknown") === selectedSource;
    },
    [selectedSource, sources],
  );

  const timelineData = useMemo(() => {
    if (selectedMetrics.length === 0 || chartPoints.length === 0) {
      return { dates: [], series: [] };
    }

    const filtered = chartPoints.filter(
      (p) => matchesSource(p) && selectedMetrics.includes(p.metric_type) && matchesSearch(p),
    );
    if (filtered.length === 0) return { dates: [], series: [] };

    const allPointsAreDaily = filtered.every((point) => pointResolution(point) === "day");
    const window = queryWindow(dateRangePreset, customStartDate, customEndDate);
    let dates: string[];
    if (allPointsAreDaily) {
      const pointDays = filtered
        .map((point) => dayOf(point.timestamp))
        .filter(Boolean)
        .sort();
      const firstDay = pointDays[0];
      const lastDay = pointDays[pointDays.length - 1];
      const start = window.start || (firstDay ? `${firstDay}T00:00:00.000Z` : undefined);
      const end = window.end || (lastDay ? `${lastDay}T23:59:59.999Z` : undefined);
      dates = start && end ? dayKeysBetween(start, end) : [];
    } else {
      // If a deployment has no rollup for a legacy interval, Core explicitly
      // returns raw fallback points. Keep their timestamps instead of pretending
      // that the browser performed an aggregation it did not perform.
      dates = Array.from(new Set(filtered.map(pointBucket).filter(Boolean))).sort();
    }

    const sourceById = new Map(sources.map((source) => [source.id, source]));
    let colorIndex = 0;
    const series = selectedMetrics.flatMap((metric) => {
      const metricPoints = filtered.filter((point) => point.metric_type === metric);
      const sourceKeys = Array.from(
        new Set(metricPoints.map((point) => point.source_id || point.source_type || "")),
      );
      if (sourceKeys.length === 0) sourceKeys.push("");

      return sourceKeys.map((sourceKey) => {
        const sourcePoints = metricPoints.filter(
          (point) => (point.source_id || point.source_type || "") === sourceKey,
        );
        const pointsByBucket = new Map<string, DataPointItem>();
        sourcePoints.forEach((point) => {
          const bucket = pointBucket(point);
          const previous = pointsByBucket.get(bucket);
          if (
            !previous ||
            (pointResolution(point) === "day" && pointResolution(previous) !== "day") ||
            (point.is_derived === false && previous.is_derived !== false)
          ) {
            pointsByBucket.set(bucket, point);
          }
        });

        const values = dates.map((date) => pointsByBucket.get(date)?.value ?? null);
        const { label, unit } = describeMetric(metric, locale);
        const aggregation = metricAggregation(metric);
        const metricLabel = unit ? `${label} (${unit})` : label;
        const source = sourceById.get(sourceKey);
        const sourcePoint = sourcePoints[0];
        const sourceType = source?.source_type || sourcePoint?.source_type || sourceKey;
        const sourceLabel =
          source?.display_name?.trim() ||
          (sourceType === "unknown" ? t("common.unknown") : sourceType.toUpperCase());
        const aggregationLabel = t(AGGREGATION_LABEL_KEYS[aggregation]);
        const seriesLabel = sourceKey
          ? t("explorer.seriesMetricSourceLabel", {
              metric: metricLabel,
              source: sourceLabel,
              aggregation: aggregationLabel,
            })
          : t("explorer.seriesMetricLabel", {
              metric: metricLabel,
              aggregation: aggregationLabel,
            });

        const seriesItem = {
          metric: sourceKey ? `${metric}:${sourceKey}` : metric,
          label: seriesLabel,
          color: COLOR_PALETTE[colorIndex % COLOR_PALETTE.length],
          values: values as unknown as number[],
        };
        colorIndex += 1;
        return seriesItem;
      });
    });

    return { dates, series };
  }, [
    chartPoints,
    selectedMetrics,
    matchesSource,
    matchesSearch,
    dateRangePreset,
    customStartDate,
    customEndDate,
    locale,
    metricAggregation,
    sources,
    t,
  ]);

  const tableData = useMemo(() => {
    return rawPoints.filter((p) => {
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
    rawPoints,
    matchesSource,
    matchesSearch,
    selectedMetrics,
    dateRangePreset,
    customStartDate,
    customEndDate,
  ]);

  const refresh = () => {
    if (view === "raw") void loadRawPoints(selectedMetrics);
    else if (view === "chart") void loadChartPoints(selectedMetrics);
    void loadSummary();
    void loadMetricTypes();
    void loadSources();
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
        {availableSources.map((source) => (
          <option key={source.id} value={source.id}>
            {source.display_name?.trim() ||
              (source.source_type === "unknown"
                ? t("common.unknown")
                : source.source_type.toUpperCase())}
          </option>
        ))}
      </select>
    </div>
  );

  const importResolutionFilter = (
    <div className="flex items-center gap-2">
      <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
        {t("explorer.importResolution")}
      </span>
      <select
        value={importResolution}
        onChange={(event) => handleImportResolutionChange(event.target.value as Resolution)}
        title={t("explorer.importResolutionHint")}
        className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-bold text-slate-900 outline-none focus:border-[#0d5c3a]"
      >
        <option value="auto">{t("explorer.resolutionAuto")}</option>
        <option value="raw">{t("explorer.resolutionRaw")}</option>
        <option value="minute">{t("explorer.resolutionMinute")}</option>
        <option value="hour">{t("explorer.resolutionHour")}</option>
        <option value="day">{t("explorer.resolutionDay")}</option>
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

  const seriesQueryNote =
    selectedMetrics.length > 0 ? (
      <p className="text-[11px] leading-relaxed text-slate-400">
        {t(view === "chart" ? "explorer.seriesQueryNote" : "explorer.rawSeriesQueryNote")}
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
                {importResolutionFilter}
              </div>

              <div className="flex flex-wrap items-center gap-3">
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
            {seriesQueryNote}
          </div>

          <ExplorerChart
            dates={timelineData.dates}
            series={timelineData.series}
            chartType={chartType}
            aggregation={chartTooltipAggregation}
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
              {importResolutionFilter}
            </div>
            {periodFilter}
            {fullTextSearch}
            {scopeBanner}
            {seriesQueryNote}
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
                <span>{t("explorer.colId")}</span>
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
                <span>{t("explorer.colIdempotencyKey")}</span>
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
