"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { getConnectorDirection } from "./ConnectorModal";
import ImportDialog from "./ImportDialog";
import ImportRunsOverview from "./ImportRunsOverview";
import ImporterDetailPage from "./ImporterDetailPage";
import { plural, useI18n, type MessageKey, type Translate } from "../lib/i18n/provider";
import {
  Activity,
  ArrowUpRight,
  BookOpen,
  CalendarDays,
  Clock3,
  CloudSun,
  Dumbbell,
  Flame,
  GitBranch,
  HousePlug,
  Key,
  MapPin,
  Plus,
  Radio,
  RefreshCw,
  Settings,
  Smartphone,
  Trash2,
  X,
} from "lucide-react";
import { apiFetch } from "../lib/api";
import { usePolling } from "../lib/polling";
import { useDialog } from "../lib/useDialog";

export interface ConnectorItem {
  id: string;
  tenant_id: string;
  source_type: string;
  /** What the user called this instance. The only thing separating two calendars. */
  display_name: string;
  status: string;
  masked_token: string;
  poll_interval_hours: number;
  lookback_days: number;
  lookback_hours: number;
  created_at?: string;
  updated_at?: string;
  sync_status?: string;
  last_sync_at?: string;
  last_sync_message?: string;
  last_request_id?: string;
  nats_subject?: string;
  nats_queue_group?: string;
  /** `"file"` for a connector fed by uploads alone, absent for the ordinary kind. */
  import_mode?: string | null;
  /** Whether this provider hands its users an export file this platform can read. */
  supports_file_import?: boolean;
}

interface ConnectorsPageProps {
  apiBase: string;
  tenantId: string;
  userRole: string;
  /** Refresh data without remounting an open import dialog. */
  refreshTrigger: number;
  onOpenConfigureModal: (connector?: ConnectorItem, sourceType?: string) => void;
  /** Set by the `/connectors/[connectorId]` route: show that instance in detail. */
  connectorId?: string;
}

interface CatalogConnector {
  id: string;
  name?: string;
  nameKey?: MessageKey;
  descriptionKey: MessageKey;
  icon: React.ElementType;
  available: boolean;
  docsPath: string;
}

/** The connector's own name, or a translation of it where the name is a word. */
function catalogName(t: Translate, cat: CatalogConnector): string {
  return cat.nameKey ? t(cat.nameKey) : (cat.name ?? cat.id);
}

/** How often the table refreshes queue status. Stated in the badge above it. */
const POLL_INTERVAL_MS = 10_000;
type ConnectorTab = "current" | "available";

const CONNECTOR_CATALOG: CatalogConnector[] = [
  {
    id: "yazio",
    name: "Yazio",
    descriptionKey: "connectors.desc.yazio",
    icon: Flame,
    available: true,
    docsPath: "/docs/importers/yazio/",
  },
  {
    id: "dawarich",
    name: "Dawarich",
    descriptionKey: "connectors.desc.dawarich",
    icon: MapPin,
    available: true,
    docsPath: "/docs/importers/dawarich/",
  },
  {
    id: "whoop",
    name: "WHOOP",
    descriptionKey: "connectors.desc.whoop",
    icon: Activity,
    available: true,
    docsPath: "/docs/importers/whoop/",
  },
  {
    id: "apple_health",
    name: "Apple Health",
    descriptionKey: "connectors.desc.apple_health",
    icon: Smartphone,
    available: true,
    docsPath: "/docs/importers/apple-health/",
  },
  {
    id: "streak",
    name: "Streak — gym log",
    descriptionKey: "connectors.desc.streak",
    icon: Dumbbell,
    available: true,
    docsPath: "/docs/importers/streak/",
  },
  {
    id: "home_assistant",
    name: "Home Assistant",
    descriptionKey: "connectors.desc.home_assistant",
    icon: HousePlug,
    available: true,
    docsPath: "/docs/importers/home-assistant/",
  },
  {
    id: "weather",
    nameKey: "connectors.nameWeather",
    descriptionKey: "connectors.desc.weather",
    icon: CloudSun,
    available: true,
    docsPath: "/docs/importers/weather/",
  },
  {
    id: "calendar",
    nameKey: "connectors.nameCalendar",
    descriptionKey: "connectors.desc.calendar",
    icon: CalendarDays,
    available: true,
    docsPath: "/docs/importers/calendar/",
  },
  {
    id: "github",
    name: "GitHub",
    descriptionKey: "connectors.desc.github",
    icon: GitBranch,
    available: true,
    docsPath: "/docs/importers/github/",
  },
];

export default function ConnectorsPage({
  apiBase,
  tenantId,
  userRole,
  refreshTrigger,
  onOpenConfigureModal,
  connectorId,
}: ConnectorsPageProps) {
  const { t, formatDateTime } = useI18n();
  const [connectors, setConnectors] = useState<ConnectorItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<ConnectorTab>("current");
  const [deletingSource, setDeletingSource] = useState<string | null>(null);
  /*
    The run history is behind this, and mounted only while it is true.

    It used to sit above the connector table, which put a page of history between
    the reader and the thing the page is named after — and, worse, kept polling
    `/sync-runs` every 2.5 s for as long as anything was running, on a tab nobody
    was looking at the history on. Unmounted means not polling.
  */
  const [runsOpen, setRunsOpen] = useState(false);
  const closeRuns = React.useCallback(() => setRunsOpen(false), []);
  const runsDialogRef = useDialog<HTMLDivElement>(runsOpen, closeRuns);
  // Which connector the import dialog is open for, if any.
  const [importDialogFor, setImportDialogFor] = useState<{
    id: string;
    name: string;
    passive: boolean;
    sourceType: string;
    fileImport: boolean;
  } | null>(null);

  const fetchConnectors = async () => {
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/sources`, {
        headers: {
          "X-Tenant-ID": tenantId,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setConnectors(data.connectors || []);
      }
    } catch (err) {
      console.error("Error fetching connectors:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (tenantId) {
      fetchConnectors();
    }
  }, [apiBase, tenantId, refreshTrigger]);

  // Live refresh of queue status and last-sync timestamps. The badge above the
  // table states this interval, and reads it from here so the two cannot drift.
  usePolling(fetchConnectors, tenantId ? POLL_INTERVAL_MS : null);

  /*
    How many connectors are mid-import, for the badge on the history button.

    Derived from the connector list this page already loads rather than from the
    run endpoint: the point of moving the history behind a button was to stop
    querying it on a page that is not showing it, and a badge that reintroduced
    that query would have undone exactly that.
  */
  const busyCount = connectors.filter((connector) =>
    ["queued", "running", "loading"].includes(connector.sync_status ?? ""),
  ).length;

  const detailId = connectorId ?? null;
  const detailConnector = detailId
    ? connectors.find((connector) => connector.id === detailId)
    : null;

  // Disconnect one connector instance. Addressed by id, not type: with two
  // calendars configured, deleting "calendar" would remove an arbitrary one.
  const handleDeleteConnector = async (connector: ConnectorItem) => {
    const label = connector.display_name || connector.source_type;
    if (!confirm(t("connectors.confirmDelete", { source: label }))) {
      return;
    }
    setDeletingSource(connector.id);
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/sources/${connector.id}`, {
        method: "DELETE",
        headers: {
          "X-Tenant-ID": tenantId,
        },
      });
      if (res.ok) {
        fetchConnectors();
      }
    } catch (err) {
      console.error("Error deleting connector:", err);
    } finally {
      setDeletingSource(null);
    }
  };

  if (detailId && loading) {
    return (
      <div className="py-16 text-center text-xs text-slate-500">{t("importerDetail.loading")}</div>
    );
  }

  if (detailId && !detailConnector) {
    return (
      <div className="space-y-4 rounded-3xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <h1 className="text-lg font-bold text-slate-900">{t("importerDetail.notFound")}</h1>
        <p className="text-xs text-slate-500">{t("importerDetail.notFoundHint")}</p>
        <Link
          href="/connectors"
          className="inline-flex rounded-2xl bg-brand px-4 py-2.5 text-xs font-bold text-brand-ink hover:bg-brand-hover"
        >
          {t("importerDetail.backToConnectors")}
        </Link>
      </div>
    );
  }

  if (detailConnector) {
    return (
      <ImporterDetailPage
        apiBase={apiBase}
        tenantId={tenantId}
        userRole={userRole}
        connector={detailConnector}
        refreshTrigger={refreshTrigger}
        onOpenConfigureModal={(connector) => onOpenConfigureModal(connector)}
      />
    );
  }

  return (
    <div className="space-y-8">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">
            {t("connectors.title")}
          </h1>
          <p className="text-xs text-slate-500 mt-1">{t("connectors.subtitle")}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={fetchConnectors}
            className="flex items-center gap-2 text-xs font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 px-3.5 py-2 rounded-2xl shadow-sm [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow]"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-slate-500 ${loading ? "animate-spin" : ""}`} />
            <span>{t("header.refresh")}</span>
          </button>
          <button
            onClick={() => setRunsOpen(true)}
            className="flex items-center gap-2 text-xs font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 px-3.5 py-2 rounded-2xl shadow-sm [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow]"
          >
            <Clock3 className="w-3.5 h-3.5 text-slate-500" />
            <span>{t("connectors.showRuns")}</span>
            {busyCount > 0 && (
              <span
                title={t("connectors.runsActiveHint", { count: busyCount })}
                className="rounded-full border border-amber-300 bg-amber-50 px-1.5 text-[10px] font-bold text-amber-800"
              >
                {busyCount}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab("available")}
            className="flex items-center gap-2 text-xs font-bold bg-brand hover:bg-brand-hover text-brand-ink px-4 py-2 rounded-2xl shadow-md shadow-brand/20 [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow]"
          >
            <Plus className="w-4 h-4" />
            <span>{t("connectors.newConnector")}</span>
          </button>
        </div>
      </div>

      <div
        role="tablist"
        aria-label={t("connectors.tabs")}
        className="flex w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-1 shadow-sm"
      >
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "current"}
          onClick={() => setActiveTab("current")}
          className={`flex-1 rounded-xl px-4 py-2.5 text-xs font-bold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
            activeTab === "current"
              ? "bg-brand text-brand-ink shadow-sm"
              : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
          }`}
        >
          {t("connectors.tabCurrent")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "available"}
          onClick={() => setActiveTab("available")}
          className={`flex-1 rounded-xl px-4 py-2.5 text-xs font-bold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
            activeTab === "available"
              ? "bg-brand text-brand-ink shadow-sm"
              : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
          }`}
        >
          {t("connectors.tabAvailable")}
        </button>
      </div>

      {activeTab === "current" ? (
        <>
          {/* Main Connected Sources & Queue Status Table */}
          <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-4">
            <div className="flex justify-between items-center">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold text-slate-900">{t("connectors.tableTitle")}</h3>
                <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded-full border border-emerald-200 flex items-center gap-1">
                  <Radio className="w-2.5 h-2.5 text-emerald-600 animate-pulse" />{" "}
                  {t("connectors.autoRefresh", { seconds: POLL_INTERVAL_MS / 1000 })}
                </span>
              </div>
              <span className="text-xs font-semibold text-slate-400">
                {t(
                  plural(
                    connectors.length,
                    "connectors.configuredCount_one",
                    "connectors.configuredCount_other",
                  ),
                  { count: connectors.length },
                )}
              </span>
            </div>

            {loading ? (
              <div className="p-8 text-center text-xs text-slate-400">
                {t("connectors.loadingDetails")}
              </div>
            ) : connectors.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 text-slate-400 uppercase tracking-wider font-bold text-[11px]">
                      <th className="pb-3 px-3">{t("connectors.colSource")}</th>
                      <th className="pb-3 px-3">{t("connectors.colQueue")}</th>
                      <th className="pb-3 px-3">{t("connectors.colLastSync")}</th>
                      <th className="pb-3 px-3">{t("connectors.colTransfer")}</th>
                      <th className="pb-3 px-3 text-right">{t("connectors.colActions")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {connectors.map((c) => {
                      const rowFileOnly = c.import_mode === "file";
                      const rowIsBusy = ["queued", "running", "loading"].includes(
                        c.sync_status ?? "",
                      );
                      const rowIsPassive =
                        getConnectorDirection(c.source_type) === "passive" || rowFileOnly;
                      /*
                    A passive connector has nothing to trigger, so the dialog held
                    only a run history for it — the same history the detail page
                    already shows in full, one column to the left. The action
                    survives where the dialog can still do something: uploading an
                    export archive, which for such a connector is the only way in.
                  */
                      const rowUploadOnly =
                        rowIsPassive && (rowFileOnly || Boolean(c.supports_file_import));
                      const rowHasImportAction = !rowIsPassive || rowUploadOnly;
                      return (
                        <tr key={c.id} className="hover:bg-slate-50 transition-colors">
                          <td className="py-3.5 px-3">
                            <div className="flex items-center gap-2.5">
                              <Key className="w-4 h-4 text-brand" />
                              <div>
                                <div className="flex items-center gap-2">
                                  {/* Name first, type beneath: two calendars differ only by name. */}
                                  <div className="font-bold text-slate-900">
                                    {c.display_name || c.source_type}
                                  </div>
                                  <a
                                    href={
                                      CONNECTOR_CATALOG.find((cat) => cat.id === c.source_type)
                                        ?.docsPath ?? "/docs/importers/"
                                    }
                                    target="_blank"
                                    rel="noreferrer"
                                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 text-emerald-800 font-semibold transition-colors"
                                    title={t("connectors.openDocs")}
                                  >
                                    <BookOpen className="w-3 h-3" />
                                    <span className="text-[10px]">{t("connectors.docs")}</span>
                                  </a>
                                  <Link
                                    href={`/connectors/${encodeURIComponent(c.id)}`}
                                    className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-900"
                                    title={t("connectors.openDetails")}
                                  >
                                    <Activity className="h-3 w-3" />
                                    <span className="text-[10px]">{t("connectors.details")}</span>
                                  </Link>
                                </div>
                                <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                                  {c.source_type}
                                </div>
                                <div
                                  className={
                                    rowIsPassive
                                      ? "text-[10px] font-bold uppercase tracking-wider text-violet-700"
                                      : "text-[10px] font-bold uppercase tracking-wider text-sky-700"
                                  }
                                >
                                  {rowIsPassive
                                    ? t("connectors.passiveHint")
                                    : t("connectors.activeHint")}
                                </div>
                                <div className="text-[10px] text-slate-400 font-mono">
                                  Fernet AES-256 Encrypted
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="py-3.5 px-3">
                            <div className="space-y-1">
                              <span
                                className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase border inline-flex items-center gap-1.5 ${
                                  rowIsBusy
                                    ? "bg-amber-50 text-amber-800 border-amber-300 animate-pulse"
                                    : c.sync_status === "error"
                                      ? "bg-rose-50 text-rose-800 border-rose-300"
                                      : "bg-emerald-50 text-emerald-800 border-emerald-200"
                                }`}
                              >
                                <Radio
                                  className={`w-3 h-3 ${
                                    rowIsBusy
                                      ? "text-amber-600 animate-spin"
                                      : c.sync_status === "error"
                                        ? "text-rose-600"
                                        : "text-emerald-600"
                                  }`}
                                />
                                <span>
                                  {c.sync_status === "loading"
                                    ? t("connectors.loadingCore")
                                    : rowIsBusy
                                      ? t("connectors.processing")
                                      : c.sync_status === "error"
                                        ? t("connectors.syncFailed")
                                        : t("connectors.readyActive")}
                                </span>
                              </span>
                              {c.last_sync_message && (
                                <div
                                  className={`text-[10px] font-mono leading-tight ${
                                    c.sync_status === "error"
                                      ? "text-rose-600 font-semibold"
                                      : "text-slate-500"
                                  }`}
                                >
                                  {c.last_sync_message}
                                </div>
                              )}
                            </div>
                          </td>
                          <td className="py-3.5 px-3 text-slate-600 font-mono text-[11px]">
                            {c.last_sync_at ? formatDateTime(c.last_sync_at) : t("common.pending")}
                          </td>
                          <td className="py-3.5 px-3 text-slate-600">
                            {rowFileOnly
                              ? t("connectors.fileDriven")
                              : rowIsPassive
                                ? t("connectors.webhookDriven")
                                : t("connectors.everyHours", {
                                    hours: c.poll_interval_hours,
                                    lookback: c.lookback_hours ?? c.lookback_days * 24,
                                  })}
                          </td>
                          {/*
                      `text-right space-x-2` wrapped badly: Tailwind's space-x-* is a
                      sibling margin, so a button pushed onto a second line kept its left
                      margin and sat indented instead of flush right. A flex row with
                      `gap` puts the space between the items rather than beside them, and
                      wraps to the right edge.
                    */}
                          <td className="py-3.5 px-3">
                            <div className="flex flex-wrap items-center justify-end gap-2">
                              {rowHasImportAction && (
                                <button
                                  onClick={() =>
                                    setImportDialogFor({
                                      id: c.id,
                                      name: c.display_name || c.source_type,
                                      passive: rowIsPassive,
                                      sourceType: c.source_type,
                                      fileImport: Boolean(c.supports_file_import),
                                    })
                                  }
                                  disabled={rowIsBusy}
                                  className="px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 font-semibold transition-colors disabled:opacity-50 inline-flex items-center gap-1.5 whitespace-nowrap"
                                >
                                  <RefreshCw
                                    className={`w-3 h-3 ${rowIsBusy ? "animate-spin" : ""}`}
                                  />
                                  <span>
                                    {c.sync_status === "loading"
                                      ? t("connectors.loadingCore")
                                      : rowIsBusy
                                        ? t("connectors.queued")
                                        : rowUploadOnly
                                          ? t("connectors.upload")
                                          : t("connectors.import")}
                                  </span>
                                </button>
                              )}
                              <button
                                onClick={() => onOpenConfigureModal(c)}
                                className={`px-3 py-1.5 rounded-xl font-semibold transition-colors shadow-xs inline-flex items-center gap-1 whitespace-nowrap ${
                                  c.sync_status === "error"
                                    ? "bg-rose-600 hover:bg-rose-700 text-white"
                                    : "bg-brand hover:bg-brand-hover text-brand-ink"
                                }`}
                              >
                                <Settings className="w-3 h-3" />
                                {/*
                                  Red because something is wrong, but the label stays
                                  "Edit": the button opens the same dialog either way,
                                  and "Renew the token" asserted a cause this page
                                  cannot know. A failed run carries a status and a
                                  message, not an error code (AGENTS.md rule 17), so
                                  the message below the badge is what names the reason
                                  — and a connector fed by an export archive has no
                                  token to renew in the first place.
                                */}
                                <span>{t("connectors.edit")}</span>
                              </button>
                              <button
                                onClick={() => handleDeleteConnector(c)}
                                disabled={deletingSource === c.id}
                                className="px-3 py-1.5 rounded-xl bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-600 font-semibold transition-colors disabled:opacity-50 inline-flex items-center gap-1 whitespace-nowrap"
                                title={t("connectors.disconnect")}
                              >
                                <Trash2 className="w-3 h-3" />
                                <span>{t("common.delete")}</span>
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-8 text-center bg-slate-50 border border-slate-200 rounded-2xl">
                <p className="text-xs text-slate-500 mb-3">{t("connectors.emptyList")}</p>
                <button
                  onClick={() => setActiveTab("available")}
                  className="px-4 py-2 text-xs font-bold rounded-2xl bg-brand hover:bg-brand-hover text-brand-ink [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] shadow-md shadow-brand/20"
                >
                  {t("connectors.addFirst")}
                </button>
              </div>
            )}
          </div>
        </>
      ) : (
        <section className="space-y-4">
          <div>
            <h2 className="text-sm font-bold text-slate-900">{t("connectors.tabAvailable")}</h2>
            <p className="mt-1 text-xs text-slate-500">{t("connectors.availableHint")}</p>
          </div>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
            {CONNECTOR_CATALOG.map((cat) => {
              const Icon = cat.icon;
              const count = connectors.filter((c) => c.source_type === cat.id).length;
              return (
                <div
                  key={`add-${cat.id}`}
                  className="glass-card flex flex-col justify-between rounded-3xl border border-dashed border-slate-300 bg-white p-6 [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,transform] hover:-translate-y-1"
                >
                  <div>
                    <div className="mb-4 flex items-start justify-between">
                      <div className="rounded-2xl bg-slate-100 p-3 text-slate-500">
                        <Icon className="h-6 w-6" />
                      </div>
                      {count > 0 && (
                        <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-emerald-800">
                          {t(
                            plural(
                              count,
                              "connectors.instanceCount_one",
                              "connectors.instanceCount_other",
                            ),
                            { count },
                          )}
                        </span>
                      )}
                    </div>
                    <h3 className="mb-1 text-lg font-extrabold text-slate-900">
                      {catalogName(t, cat)}
                    </h3>
                    <p className="mb-4 text-xs leading-relaxed text-slate-500">
                      {t(cat.descriptionKey)}
                    </p>
                  </div>
                  <button
                    onClick={() => onOpenConfigureModal(undefined, cat.id)}
                    disabled={!cat.available}
                    className="flex w-full items-center justify-center gap-1.5 rounded-2xl bg-brand py-2.5 text-xs font-bold text-brand-ink shadow-md shadow-brand/20 [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] hover:bg-brand-hover disabled:opacity-40"
                  >
                    <span>
                      {!cat.available
                        ? t("connectors.soon")
                        : count > 0
                          ? t("connectors.addAnother")
                          : t("connectors.connectNow")}
                    </span>
                    {cat.available && <ArrowUpRight className="h-3.5 w-3.5" />}
                  </button>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {runsOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div
            ref={runsDialogRef}
            role="dialog"
            aria-modal="true"
            aria-label={t("importOverview.title")}
            tabIndex={-1}
            className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-3xl bg-white shadow-xl"
          >
            {/* Only the close button: the run overview carries its own heading,
                and a second copy of it in a title bar said the same thing twice. */}
            <div className="flex justify-end border-b border-slate-100 px-4 py-2">
              <button
                onClick={() => setRunsOpen(false)}
                aria-label={t("common.close")}
                className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="overflow-y-auto p-4">
              <ImportRunsOverview
                apiBase={apiBase}
                tenantId={tenantId}
                refreshTrigger={refreshTrigger}
                userRole={userRole}
              />
            </div>
          </div>
        </div>
      )}

      {importDialogFor && (
        <ImportDialog
          key={importDialogFor.id}
          apiBase={apiBase}
          sourceType={importDialogFor.id}
          sourceName={importDialogFor.name}
          providerType={importDialogFor.sourceType}
          fileImport={importDialogFor.fileImport}
          passive={importDialogFor.passive}
          isOpen={true}
          onClose={() => setImportDialogFor(null)}
          onQueued={fetchConnectors}
        />
      )}
    </div>
  );
}
