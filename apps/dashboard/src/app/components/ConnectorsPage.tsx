"use client";

import React, { useState, useEffect } from "react";
import { getConnectorDirection } from "./ConnectorModal";
import ImportDialog from "./ImportDialog";
import { plural, useI18n, type MessageKey, type Translate } from "../lib/i18n/provider";
import { 
  Key, 
  RefreshCw, 
  Settings, 
  ArrowUpRight, 
  Activity, 
  CheckCircle, 
  Plus, 
  Radio, 
  Flame,
  MapPin,
  Smartphone,
  Trash2,
  Dumbbell,
  CloudSun,
  HousePlug,
  CalendarDays,
  BookOpen
} from "lucide-react";
import { apiFetch } from "../lib/api";

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
  created_at?: string;
  updated_at?: string;
  sync_status?: string;
  last_sync_at?: string;
  last_sync_message?: string;
  last_request_id?: string;
  nats_subject?: string;
  nats_queue_group?: string;
}

interface ConnectorsPageProps {
  apiBase: string;
  tenantId: string;
  onOpenConfigureModal: (connector?: ConnectorItem, sourceType?: string) => void;
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

const CONNECTOR_CATALOG: CatalogConnector[] = [
  { id: "yazio", name: "Yazio", descriptionKey: "connectors.desc.yazio", icon: Flame, available: true, docsPath: "/docs/importers/yazio/" },
  { id: "dawarich", name: "Dawarich", descriptionKey: "connectors.desc.dawarich", icon: MapPin, available: true, docsPath: "/docs/importers/dawarich/" },
  { id: "whoop", name: "WHOOP", descriptionKey: "connectors.desc.whoop", icon: Activity, available: true, docsPath: "/docs/importers/whoop/" },
  { id: "apple_health", name: "Apple Health", descriptionKey: "connectors.desc.apple_health", icon: Smartphone, available: true, docsPath: "/docs/importers/apple-health/" },
  { id: "streak", name: "Streak — gym log", descriptionKey: "connectors.desc.streak", icon: Dumbbell, available: true, docsPath: "/docs/importers/streak/" },
  { id: "home_assistant", name: "Home Assistant", descriptionKey: "connectors.desc.home_assistant", icon: HousePlug, available: true, docsPath: "/docs/importers/home-assistant/" },
  { id: "weather", nameKey: "connectors.nameWeather", descriptionKey: "connectors.desc.weather", icon: CloudSun, available: true, docsPath: "/docs/importers/weather/" },
  { id: "calendar", nameKey: "connectors.nameCalendar", descriptionKey: "connectors.desc.calendar", icon: CalendarDays, available: true, docsPath: "/docs/importers/calendar/" },
];

export default function ConnectorsPage({
  apiBase,
  tenantId,
  onOpenConfigureModal,
}: ConnectorsPageProps) {
  const { t, formatDateTime } = useI18n();
  const [connectors, setConnectors] = useState<ConnectorItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncingSource, setSyncingSource] = useState<string | null>(null);
  const [deletingSource, setDeletingSource] = useState<string | null>(null);
  // Which connector the import dialog is open for, if any.
  const [importDialogFor, setImportDialogFor] = useState<
    { id: string; name: string; passive: boolean } | null
  >(null);

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
  }, [apiBase, tenantId]);

  // Live refresh of queue status and last-sync timestamps. The badge above the
  // table states this interval, and reads it from here so the two cannot drift.
  useEffect(() => {
    if (!tenantId) return;
    const interval = setInterval(() => {
      fetchConnectors();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [apiBase, tenantId]);

  const handleTriggerSync = async (sourceType: string) => {
    setSyncingSource(sourceType);
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/sources/sync`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-ID": tenantId,
        },
        body: JSON.stringify({ source_type: sourceType }),
      });
      if (res.ok) {
        fetchConnectors();
      }
    } catch (err) {
      console.error("Error triggering sync:", err);
    } finally {
      setTimeout(() => setSyncingSource(null), 1000);
    }
  };

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

  return (
    <div className="space-y-8">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">{t("connectors.title")}</h1>
          <p className="text-xs text-slate-500 mt-1">
            {t("connectors.subtitle")}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchConnectors}
            className="flex items-center gap-2 text-xs font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 px-3.5 py-2 rounded-2xl shadow-sm transition-all"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-slate-500 ${loading ? "animate-spin" : ""}`} />
            <span>{t("header.refresh")}</span>
          </button>
          <button
            onClick={() => onOpenConfigureModal()}
            className="flex items-center gap-2 text-xs font-bold bg-[#0d5c3a] hover:bg-[#08432a] text-white px-4 py-2 rounded-2xl shadow-md shadow-[#0d5c3a]/20 transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>{t("connectors.newConnector")}</span>
          </button>
        </div>
      </div>

      {/*
        One card per configured connector *instance*, then one per catalog entry to
        add another. Previously the gallery iterated the catalog and looked each
        type up with `.find()`, which could only ever show one — so a second
        calendar was invisible even once the backend could store it.
      */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {connectors.map((connector) => {
          const cat = CONNECTOR_CATALOG.find((c) => c.id === connector.source_type);
          const Icon = cat?.icon ?? Key;
          const direction = getConnectorDirection(connector.source_type);
          const isPassive = direction === "passive";
          const typeName = cat ? catalogName(t, cat) : connector.source_type;
          const docsPath = cat?.docsPath ?? "/docs/importers/";

          return (
            <div
              key={connector.id}
              className={`glass-card p-6 bg-white border rounded-3xl flex flex-col justify-between transition-all hover:-translate-y-1 ${
                "border-emerald-200/80 shadow-md"
              }`}
            >
              <div>
                <div className="flex justify-between items-start mb-4">
                  <div className={"p-3 rounded-2xl bg-emerald-50 text-[#0d5c3a]"}>
                    <Icon className="w-6 h-6" />
                  </div>
                  <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-100 text-emerald-800 border border-emerald-300 px-2.5 py-1 rounded-full flex items-center gap-1">
                    <CheckCircle className="w-3 h-3 text-emerald-600" /> {isPassive ? t("connectors.passive") : t("connectors.active")}
                  </span>
                </div>

                <div className="flex items-center gap-2 mb-1">
                  {/* The instance name leads: it is what distinguishes two calendars. */}
                  <h3 className="text-lg font-extrabold text-slate-900 truncate">
                    {connector.display_name || typeName}
                  </h3>
                  <a
                    href={docsPath}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 px-2 py-1 text-[10px] font-bold rounded-lg bg-emerald-50 border border-emerald-200 hover:bg-emerald-100 text-emerald-800 transition-colors"
                    title={t("connectors.docsFor", { name: typeName })}
                  >
                    <BookOpen className="w-3 h-3" />
                    <span>{t("connectors.docs")}</span>
                  </a>
                </div>
                <p className="text-[11px] font-semibold text-slate-400 mb-1">{typeName}</p>
                <span className={isPassive
                  ? "inline-flex text-[10px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full mb-2 bg-violet-50 text-violet-800 border border-violet-200"
                  : "inline-flex text-[10px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full mb-2 bg-sky-50 text-sky-800 border border-sky-200"}>
                  {isPassive ? t("connectors.passiveHint") : t("connectors.activeHint")}
                </span>
                {cat && (
                  <p className="text-xs text-slate-500 leading-relaxed mb-4">
                    {t(cat.descriptionKey)}
                  </p>
                )}

                {/* Queue Status Live Badge */}
                <div className="mb-4 pt-3 border-t border-slate-100">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-[10px] font-bold uppercase text-slate-400">
                      {t("connectors.queueStatus")}
                    </span>
                    <span className={`font-bold uppercase text-[10px] px-2 py-0.5 rounded-full ${
                      connector.sync_status === "queued"
                        ? "bg-amber-100 text-amber-800 border border-amber-300 animate-pulse"
                        : connector.sync_status === "error"
                        ? "bg-rose-100 text-rose-800 border border-rose-300"
                        : "bg-emerald-100 text-emerald-800 border border-emerald-200"
                    }`}>
                      {connector.sync_status === "queued"
                        ? t("connectors.eventQueued")
                        : connector.sync_status === "error"
                        ? t("connectors.authError")
                        : t("connectors.standby")}
                    </span>
                  </div>
                </div>
              </div>

              {/*
                The cards sit four to a row on `lg`, so the icon-only buttons squeeze the
                Import label until it clips. `min-w-0` lets the flex-1 button actually
                shrink, and `flex-wrap` gives it its own line rather than overflowing.
              */}
              <div className="flex flex-wrap gap-2 pt-2 border-t border-slate-100">
                {/*
                  Offered for push connectors too. The dialog is where an import's
                  progress and history live, and a pushed import had neither —
                  `!isPassive` hid the only place it could have been shown.
                */}
                <button
                  onClick={() =>
                    setImportDialogFor({
                      id: connector.id,
                      name: connector.display_name || typeName,
                      passive: isPassive,
                    })
                  }
                  className="flex-1 min-w-0 flex items-center justify-center gap-2 py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all shadow-md shadow-[#0d5c3a]/20"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>{isPassive ? t("connectors.history") : t("connectors.import")}</span>
                </button>
                <button
                  onClick={() => onOpenConfigureModal(connector, connector.source_type)}
                  className="p-2.5 text-xs font-semibold rounded-2xl bg-slate-100 border border-slate-200 hover:bg-slate-200 text-slate-700 transition-colors"
                  title={t("connectors.editCredentials")}
                >
                  <Settings className="w-4 h-4" />
                </button>
                <button
                  onClick={() => handleDeleteConnector(connector)}
                  disabled={deletingSource === connector.id}
                  className="p-2.5 text-xs font-semibold rounded-2xl bg-rose-50 border border-rose-200 hover:bg-rose-100 text-rose-600 transition-colors disabled:opacity-50"
                  title={t("connectors.disconnect")}
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          );
        })}

        {/*
          One "add" card per catalog entry, always offered -- adding a second
          calendar is the point, so a configured type must not disappear from here.
        */}
        {CONNECTOR_CATALOG.map((cat) => {
          const Icon = cat.icon;
          const count = connectors.filter((c) => c.source_type === cat.id).length;
          return (
            <div
              key={`add-${cat.id}`}
              className="glass-card p-6 bg-white border border-dashed border-slate-300 rounded-3xl flex flex-col justify-between transition-all hover:-translate-y-1"
            >
              <div>
                <div className="flex justify-between items-start mb-4">
                  <div className="p-3 rounded-2xl bg-slate-100 text-slate-500">
                    <Icon className="w-6 h-6" />
                  </div>
                  {count > 0 && (
                    <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-50 text-emerald-800 border border-emerald-200 px-2.5 py-1 rounded-full">
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
                <h3 className="text-lg font-extrabold text-slate-900 mb-1">
                  {catalogName(t, cat)}
                </h3>
                <p className="text-xs text-slate-500 leading-relaxed mb-4">
                  {t(cat.descriptionKey)}
                </p>
              </div>
              <button
                onClick={() => onOpenConfigureModal(undefined, cat.id)}
                disabled={!cat.available}
                className="w-full py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all disabled:opacity-40 shadow-md shadow-[#0d5c3a]/20 flex items-center justify-center gap-1.5"
              >
                <span>
                  {!cat.available
                    ? t("connectors.soon")
                    : count > 0
                    ? t("connectors.addAnother")
                    : t("connectors.connectNow")}
                </span>
                {cat.available && <ArrowUpRight className="w-3.5 h-3.5" />}
              </button>
            </div>
          );
        })}
      </div>

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
              plural(connectors.length, "connectors.configuredCount_one", "connectors.configuredCount_other"),
              { count: connectors.length },
            )}
          </span>
        </div>

        {loading ? (
          <div className="p-8 text-center text-xs text-slate-400">{t("connectors.loadingDetails")}</div>
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
                  const rowIsPassive = getConnectorDirection(c.source_type) === "passive";
                  return (
                  <tr key={c.id} className="hover:bg-slate-50 transition-colors">
                    <td className="py-3.5 px-3">
                      <div className="flex items-center gap-2.5">
                        <Key className="w-4 h-4 text-[#0d5c3a]" />
                        <div>
                          <div className="flex items-center gap-2">
                            {/* Name first, type beneath: two calendars differ only by name. */}
                            <div className="font-bold text-slate-900">
                              {c.display_name || c.source_type}
                            </div>
                            <a
                              href={CONNECTOR_CATALOG.find((cat) => cat.id === c.source_type)?.docsPath ?? "/docs/importers/"}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 text-emerald-800 font-semibold transition-colors"
                              title={t("connectors.openDocs")}
                            >
                              <BookOpen className="w-3 h-3" />
                              <span className="text-[10px]">{t("connectors.docs")}</span>
                            </a>
                          </div>
                          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                            {c.source_type}
                          </div>
                          <div className={rowIsPassive ? "text-[10px] font-bold uppercase tracking-wider text-violet-700" : "text-[10px] font-bold uppercase tracking-wider text-sky-700"}>
                            {rowIsPassive
                              ? t("connectors.passiveHint")
                              : t("connectors.activeHint")}
                          </div>
                          <div className="text-[10px] text-slate-400 font-mono">Fernet AES-256 Encrypted</div>
                        </div>
                      </div>
                    </td>
                    <td className="py-3.5 px-3">
                      <div className="space-y-1">
                        <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase border inline-flex items-center gap-1.5 ${
                          c.sync_status === "queued"
                            ? "bg-amber-50 text-amber-800 border-amber-300 animate-pulse"
                            : c.sync_status === "error"
                            ? "bg-rose-50 text-rose-800 border-rose-300"
                            : "bg-emerald-50 text-emerald-800 border-emerald-200"
                        }`}>
                          <Radio className={`w-3 h-3 ${
                            c.sync_status === "queued"
                              ? "text-amber-600 animate-spin"
                              : c.sync_status === "error"
                              ? "text-rose-600"
                              : "text-emerald-600"
                          }`} />
                          <span>
                            {c.sync_status === "queued"
                              ? t("connectors.processing")
                              : c.sync_status === "error"
                              ? t("connectors.authErrorShort")
                              : t("connectors.readyActive")}
                          </span>
                        </span>
                        {c.last_sync_message && (
                          <div className={`text-[10px] font-mono leading-tight ${
                            c.sync_status === "error" ? "text-rose-600 font-semibold" : "text-slate-500"
                          }`}>
                            {c.last_sync_message}
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="py-3.5 px-3 text-slate-600 font-mono text-[11px]">
                      {c.last_sync_at ? formatDateTime(c.last_sync_at) : t("common.pending")}
                    </td>
                    <td className="py-3.5 px-3 text-slate-600">
                      {rowIsPassive
                        ? t("connectors.webhookDriven")
                        : t("connectors.everyHours", { hours: c.poll_interval_hours, days: c.lookback_days })}
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
                      {/*
                        Offered for push connectors too, matching the cards: the
                        dialog is where progress and history live, and a pushed
                        import has both. The guard here also made the `passive`
                        flag below dead — it could only ever be computed inside a
                        branch that had already excluded passive connectors.
                      */}
                      <button
                        onClick={() =>
                          setImportDialogFor({
                            id: c.id,
                            name: c.display_name || c.source_type,
                            passive: rowIsPassive,
                          })
                        }
                        disabled={c.sync_status === "queued"}
                        className="px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 font-semibold transition-colors disabled:opacity-50 inline-flex items-center gap-1.5 whitespace-nowrap"
                      >
                        <RefreshCw className={`w-3 h-3 ${c.sync_status === "queued" ? "animate-spin" : ""}`} />
                        <span>
                          {c.sync_status === "queued"
                            ? t("connectors.queued")
                            : rowIsPassive
                            ? t("connectors.history")
                            : t("connectors.import")}
                        </span>
                      </button>
                      <button
                        onClick={() => onOpenConfigureModal(c)}
                        className={`px-3 py-1.5 rounded-xl font-semibold transition-colors shadow-xs inline-flex items-center gap-1 whitespace-nowrap ${
                          c.sync_status === "error"
                            ? "bg-rose-600 hover:bg-rose-700 text-white"
                            : "bg-[#0d5c3a] hover:bg-[#08432a] text-white"
                        }`}
                      >
                        <Settings className="w-3 h-3" />
                        <span>{c.sync_status === "error" ? t("connectors.renewToken") : t("connectors.edit")}</span>
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
              onClick={() => onOpenConfigureModal()}
              className="px-4 py-2 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all shadow-md shadow-[#0d5c3a]/20"
            >
              {t("connectors.addFirst")}
            </button>
          </div>
        )}
      </div>

      {importDialogFor && (
        <ImportDialog
          key={importDialogFor.id}
          apiBase={apiBase}
          sourceType={importDialogFor.id}
          sourceName={importDialogFor.name}
          passive={importDialogFor.passive}
          isOpen={true}
          onClose={() => setImportDialogFor(null)}
          onQueued={fetchConnectors}
        />
      )}
    </div>
  );
}
