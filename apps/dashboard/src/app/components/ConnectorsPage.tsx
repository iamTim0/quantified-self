"use client";

import React, { useState, useEffect } from "react";
import { getConnectorDirection } from "./ConnectorModal";
import ImportDialog from "./ImportDialog";
import { useI18n, type MessageKey, type Translate } from "../lib/i18n/provider";
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
  const [importDialogFor, setImportDialogFor] = useState<{ id: string; name: string } | null>(null);

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

  // 10s Live Auto-Polling for Queue Status & Last Sync Timestamps
  useEffect(() => {
    if (!tenantId) return;
    const interval = setInterval(() => {
      fetchConnectors();
    }, 10000);
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

  // 1-Click Delete Specific Connector & Remove Credentials
  const handleDeleteConnector = async (sourceType: string) => {
    if (!confirm(t("connectors.confirmDelete", { source: sourceType.toUpperCase() }))) {
      return;
    }
    setDeletingSource(sourceType);
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/sources/${sourceType}`, {
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
            <span>Neuer Connector</span>
          </button>
        </div>
      </div>

      {/* Connector Catalog Cards Gallery */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {CONNECTOR_CATALOG.map((cat) => {
          const configured = connectors.find((c) => c.source_type === cat.id);
          const isConfigured = Boolean(configured);
          const Icon = cat.icon;
          const direction = getConnectorDirection(cat.id);
          const isPassive = direction === "passive";

          return (
            <div
              key={cat.id}
              className={`glass-card p-6 bg-white border rounded-3xl flex flex-col justify-between transition-all hover:-translate-y-1 ${
                isConfigured ? "border-emerald-200/80 shadow-md" : "border-slate-200/80"
              }`}
            >
              <div>
                <div className="flex justify-between items-start mb-4">
                  <div className={`p-3 rounded-2xl ${isConfigured ? "bg-emerald-50 text-[#0d5c3a]" : "bg-slate-100 text-slate-500"}`}>
                    <Icon className="w-6 h-6" />
                  </div>
                  {isConfigured ? (
                    <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-100 text-emerald-800 border border-emerald-300 px-2.5 py-1 rounded-full flex items-center gap-1">
                      <CheckCircle className="w-3 h-3 text-emerald-600" /> {isPassive ? t("connectors.passive") : t("connectors.active")}
                    </span>
                  ) : cat.available ? (
                    <span className="text-[10px] font-bold uppercase tracking-wider bg-slate-100 text-slate-600 border border-slate-200 px-2.5 py-1 rounded-full">
                      {t("connectors.ready")}
                    </span>
                  ) : (
                    <span className="text-[10px] font-bold uppercase tracking-wider bg-slate-100 text-slate-400 border border-slate-200 px-2.5 py-1 rounded-full">
                      {t("connectors.soon")}
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2 mb-1">
                  <h3 className="text-lg font-extrabold text-slate-900">{catalogName(t, cat)}</h3>
                  <a
                    href={cat.docsPath}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 px-2 py-1 text-[10px] font-bold rounded-lg bg-emerald-50 border border-emerald-200 hover:bg-emerald-100 text-emerald-800 transition-colors"
                    title={t("connectors.docsFor", { name: catalogName(t, cat) })}
                  >
                    <BookOpen className="w-3 h-3" />
                    <span>Docs</span>
                  </a>
                </div>
                <span className={isPassive
                  ? "inline-flex text-[10px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full mb-2 bg-violet-50 text-violet-800 border border-violet-200"
                  : "inline-flex text-[10px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full mb-2 bg-sky-50 text-sky-800 border border-sky-200"}>
                  {isPassive ? t("connectors.passiveHint") : t("connectors.activeHint")}
                </span>
                <p className="text-xs text-slate-500 leading-relaxed mb-4">{t(cat.descriptionKey)}</p>

                {/* Queue Status Live Badge */}
                {isConfigured && configured && (
                  <div className="mb-4 pt-3 border-t border-slate-100">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-[10px] font-bold uppercase text-slate-400">Queue Status</span>
                      <span className={`font-bold uppercase text-[10px] px-2 py-0.5 rounded-full ${
                        configured.sync_status === "queued"
                          ? "bg-amber-100 text-amber-800 border border-amber-300 animate-pulse"
                          : configured.sync_status === "error"
                          ? "bg-rose-100 text-rose-800 border border-rose-300"
                          : "bg-emerald-100 text-emerald-800 border border-emerald-200"
                      }`}>
                        {configured.sync_status === "queued"
                          ? "🟡 Event in Queue"
                          : configured.sync_status === "error"
                          ? t("connectors.authError")
                          : "🟢 Standby / Bereit"}
                      </span>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex gap-2 pt-2 border-t border-slate-100">
                {isConfigured && configured ? (
                  <>
                    {!isPassive && (
                    <button
                      onClick={() => setImportDialogFor({ id: cat.id, name: catalogName(t, cat) })}
                      className="flex-1 flex items-center justify-center gap-2 py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all shadow-md shadow-[#0d5c3a]/20"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                      <span>{t("connectors.import")}</span>
                    </button>
                    )}
                    <button
                      onClick={() => onOpenConfigureModal(configured, cat.id)}
                      className="p-2.5 text-xs font-semibold rounded-2xl bg-slate-100 border border-slate-200 hover:bg-slate-200 text-slate-700 transition-colors"
                      title={t("connectors.editCredentials")}
                    >
                      <Settings className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDeleteConnector(cat.id)}
                      disabled={deletingSource === cat.id}
                      className="p-2.5 text-xs font-semibold rounded-2xl bg-rose-50 border border-rose-200 hover:bg-rose-100 text-rose-600 transition-colors disabled:opacity-50"
                      title={t("connectors.disconnect")}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => onOpenConfigureModal(undefined, cat.id)}
                    disabled={!cat.available}
                    className="w-full py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all disabled:opacity-40 shadow-md shadow-[#0d5c3a]/20 flex items-center justify-center gap-1.5"
                  >
                    <span>{cat.available ? t("connectors.connectNow") : t("connectors.soon")}</span>
                    {cat.available && <ArrowUpRight className="w-3.5 h-3.5" />}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Main Connected Sources & Queue Status Table */}
      <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-4">
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-slate-900">Konfigurierte Connections & Live Queue Status</h3>
            <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded-full border border-emerald-200 flex items-center gap-1">
              <Radio className="w-2.5 h-2.5 text-emerald-600 animate-pulse" /> Auto-Polling 10s
            </span>
          </div>
          <span className="text-xs font-semibold text-slate-400">
            {connectors.length} Connector{connectors.length === 1 ? "" : "en"} konfiguriert
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
                  <th className="pb-3 px-3">NATS Queue & Status</th>
                  <th className="pb-3 px-3">Letzter Sync</th>
                  <th className="pb-3 px-3">{t("connectors.colTransfer")}</th>
                  <th className="pb-3 px-3 text-right">Aktionen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {connectors.map((c) => (
                  <tr key={c.id} className="hover:bg-slate-50 transition-colors">
                    <td className="py-3.5 px-3">
                      <div className="flex items-center gap-2.5">
                        <Key className="w-4 h-4 text-[#0d5c3a]" />
                        <div>
                          <div className="flex items-center gap-2">
                            <div className="font-bold text-slate-900 uppercase tracking-wide">{c.source_type}</div>
                            <a
                              href={CONNECTOR_CATALOG.find((cat) => cat.id === c.source_type)?.docsPath ?? "/docs/importers/"}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 text-emerald-800 font-semibold transition-colors"
                              title={t("connectors.openDocs")}
                            >
                              <BookOpen className="w-3 h-3" />
                              <span className="text-[10px]">Docs</span>
                            </a>
                          </div>
                          <div className={getConnectorDirection(c.source_type) === "passive" ? "text-[10px] font-bold uppercase tracking-wider text-violet-700" : "text-[10px] font-bold uppercase tracking-wider text-sky-700"}>
                            {getConnectorDirection(c.source_type) === "passive"
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
                              ? "Event gequeut (Processing)"
                              : c.sync_status === "error"
                              ? t("connectors.authErrorShort")
                              : "Bereit / Active"}
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
                      {getConnectorDirection(c.source_type) === "passive"
                        ? "Webhook · ereignisbasiert"
                        : t("connectors.everyHours", { hours: c.poll_interval_hours, days: c.lookback_days })}
                    </td>
                    <td className="py-3.5 px-3 text-right space-x-2">
                      {getConnectorDirection(c.source_type) === "active" && (
                      <button
                        onClick={() =>
                          setImportDialogFor({
                            id: c.source_type,
                            name: CONNECTOR_CATALOG.find((x) => x.id === c.source_type)?.name ?? c.source_type,
                          })
                        }
                        disabled={c.sync_status === "queued"}
                        className="px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 font-semibold transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
                      >
                        <RefreshCw className={`w-3 h-3 ${c.sync_status === "queued" ? "animate-spin" : ""}`} />
                        <span>{c.sync_status === "queued" ? "Queued" : "Importieren"}</span>
                      </button>
                      )}
                      <button
                        onClick={() => onOpenConfigureModal(c)}
                        className={`px-3 py-1.5 rounded-xl font-semibold transition-colors shadow-xs inline-flex items-center gap-1 ${
                          c.sync_status === "error"
                            ? "bg-rose-600 hover:bg-rose-700 text-white"
                            : "bg-[#0d5c3a] hover:bg-[#08432a] text-white"
                        }`}
                      >
                        <Settings className="w-3 h-3" />
                        <span>{c.sync_status === "error" ? t("connectors.renewToken") : t("connectors.edit")}</span>
                      </button>
                      <button
                        onClick={() => handleDeleteConnector(c.source_type)}
                        disabled={deletingSource === c.source_type}
                        className="px-3 py-1.5 rounded-xl bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-600 font-semibold transition-colors disabled:opacity-50 inline-flex items-center gap-1"
                        title={t("connectors.disconnect")}
                      >
                        <Trash2 className="w-3 h-3" />
                        <span>{t("common.delete")}</span>
                      </button>
                    </td>
                  </tr>
                ))}
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
          isOpen={true}
          onClose={() => setImportDialogFor(null)}
          onQueued={fetchConnectors}
        />
      )}
    </div>
  );
}
