"use client";

import React, { useState, useEffect } from "react";
import { 
  Key, 
  RefreshCw, 
  Settings, 
  ArrowUpRight, 
  ShieldCheck, 
  Activity, 
  CheckCircle, 
  Plus, 
  Radio, 
  Database,
  Flame,
  MapPin,
  Heart,
  Smartphone,
  AlertTriangle,
  Trash2
} from "lucide-react";

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
  token: string;
  tenantId: string;
  onOpenConfigureModal: (connector?: ConnectorItem, sourceType?: string) => void;
}

interface CatalogConnector {
  id: string;
  name: string;
  description: string;
  icon: React.ElementType;
  available: boolean;
}

const CONNECTOR_CATALOG: CatalogConnector[] = [
  {
    id: "yazio",
    name: "Yazio",
    description: "Kalorien, Makronährstoffe (Protein, Kohlenhydrate, Fett) & Mahlzeitentagebuch.",
    icon: Flame,
    available: true,
  },
  {
    id: "dawarich",
    name: "Dawarich",
    description: "GPS-Standortdaten, Bewegungsstrecken & Geofencing über PostGIS Spatial Index.",
    icon: MapPin,
    available: true,
  },
  {
    id: "whoop",
    name: "Whoop",
    description: "Herzfrequenzvariabilität (HRV), Schlafphasen & Strain Score Integration.",
    icon: Activity,
    available: true,
  },
  {
    id: "apple_health",
    name: "Apple Health",
    description: "Schritte, Aktivitätsenergie, Ruheherzfrequenz & Blutsauerstoff.",
    icon: Smartphone,
    available: false,
  },
];

export default function ConnectorsPage({
  apiBase,
  token,
  tenantId,
  onOpenConfigureModal,
}: ConnectorsPageProps) {
  const [connectors, setConnectors] = useState<ConnectorItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncingSource, setSyncingSource] = useState<string | null>(null);
  const [deletingSource, setDeletingSource] = useState<string | null>(null);

  const fetchConnectors = async () => {
    try {
      const res = await fetch(`${apiBase}/api/v1/data/sources`, {
        headers: {
          Authorization: `Bearer ${token}`,
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
    if (token && tenantId) {
      fetchConnectors();
    }
  }, [apiBase, token, tenantId]);

  // 10s Live Auto-Polling for Queue Status & Last Sync Timestamps
  useEffect(() => {
    if (!token || !tenantId) return;
    const interval = setInterval(() => {
      fetchConnectors();
    }, 10000);
    return () => clearInterval(interval);
  }, [apiBase, token, tenantId]);

  const handleTriggerSync = async (sourceType: string) => {
    setSyncingSource(sourceType);
    try {
      const res = await fetch(`${apiBase}/api/v1/data/sources/sync`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
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
    if (!confirm(`Möchtest du die Anbindung zu ${sourceType.toUpperCase()} und das gespeicherte Token wirklich löschen?`)) {
      return;
    }
    setDeletingSource(sourceType);
    try {
      const res = await fetch(`${apiBase}/api/v1/data/sources/${sourceType}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
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
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Connectoren & Ingestion Pipeline</h1>
          <p className="text-xs text-slate-500 mt-1">
            Verwalte deine Datenquellen, API-Tokens und überwache den NATS JetStream Event Broker live.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchConnectors}
            className="flex items-center gap-2 text-xs font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 px-3.5 py-2 rounded-2xl shadow-sm transition-all"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-slate-500 ${loading ? "animate-spin" : ""}`} />
            <span>Aktualisieren</span>
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
                      <CheckCircle className="w-3 h-3 text-emerald-600" /> Aktiver Connector
                    </span>
                  ) : cat.available ? (
                    <span className="text-[10px] font-bold uppercase tracking-wider bg-slate-100 text-slate-600 border border-slate-200 px-2.5 py-1 rounded-full">
                      Bereit
                    </span>
                  ) : (
                    <span className="text-[10px] font-bold uppercase tracking-wider bg-slate-100 text-slate-400 border border-slate-200 px-2.5 py-1 rounded-full">
                      Demnächst
                    </span>
                  )}
                </div>

                <h3 className="text-lg font-extrabold text-slate-900 mb-1">{cat.name}</h3>
                <p className="text-xs text-slate-500 leading-relaxed mb-4">{cat.description}</p>

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
                          ? "🔴 Auth Fehler (401)"
                          : "🟢 Standby / Bereit"}
                      </span>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex gap-2 pt-2 border-t border-slate-100">
                {isConfigured && configured ? (
                  <>
                    <button
                      onClick={() => handleTriggerSync(cat.id)}
                      disabled={syncingSource === cat.id}
                      className="flex-1 flex items-center justify-center gap-2 py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all disabled:opacity-50 shadow-md shadow-[#0d5c3a]/20"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${syncingSource === cat.id ? "animate-spin" : ""}`} />
                      <span>{syncingSource === cat.id ? "Queuing..." : "Jetzt Sync"}</span>
                    </button>
                    <button
                      onClick={() => onOpenConfigureModal(configured, cat.id)}
                      className="p-2.5 text-xs font-semibold rounded-2xl bg-slate-100 border border-slate-200 hover:bg-slate-200 text-slate-700 transition-colors"
                      title="Zugangsdaten bearbeiten"
                    >
                      <Settings className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDeleteConnector(cat.id)}
                      disabled={deletingSource === cat.id}
                      className="p-2.5 text-xs font-semibold rounded-2xl bg-rose-50 border border-rose-200 hover:bg-rose-100 text-rose-600 transition-colors disabled:opacity-50"
                      title="1-Klick Connector Trennen & Löschen"
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
                    <span>{cat.available ? "Jetzt Verknüpfen" : "Demnächst"}</span>
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
            {connectors.length} Connector{connectors.length === 1 ? "" : "en"} aktiv
          </span>
        </div>

        {loading ? (
          <div className="p-8 text-center text-xs text-slate-400">Lade Connector & Queue Details...</div>
        ) : connectors.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-400 uppercase tracking-wider font-bold text-[11px]">
                  <th className="pb-3 px-3">Connection / Quelle</th>
                  <th className="pb-3 px-3">NATS Queue & Status</th>
                  <th className="pb-3 px-3">Letzter Sync</th>
                  <th className="pb-3 px-3">Abfrage-Frequenz</th>
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
                          <div className="font-bold text-slate-900 uppercase tracking-wide">{c.source_type}</div>
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
                              ? "HTTP 401 Auth Fehler"
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
                      {c.last_sync_at ? new Date(c.last_sync_at).toLocaleString("de-DE") : "Ausstehend"}
                    </td>
                    <td className="py-3.5 px-3 text-slate-600">
                      Alle {c.poll_interval_hours} Std. ({c.lookback_days} Tage Lookback)
                    </td>
                    <td className="py-3.5 px-3 text-right space-x-2">
                      <button
                        onClick={() => handleTriggerSync(c.source_type)}
                        disabled={syncingSource === c.source_type || c.sync_status === "queued"}
                        className="px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 font-semibold transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
                      >
                        <RefreshCw className={`w-3 h-3 ${syncingSource === c.source_type || c.sync_status === "queued" ? "animate-spin" : ""}`} />
                        <span>{c.sync_status === "queued" ? "Queued" : "Sync"}</span>
                      </button>
                      <button
                        onClick={() => onOpenConfigureModal(c)}
                        className={`px-3 py-1.5 rounded-xl font-semibold transition-colors shadow-xs inline-flex items-center gap-1 ${
                          c.sync_status === "error"
                            ? "bg-rose-600 hover:bg-rose-700 text-white"
                            : "bg-[#0d5c3a] hover:bg-[#08432a] text-white"
                        }`}
                      >
                        <Settings className="w-3 h-3" />
                        <span>{c.sync_status === "error" ? "Token Erneuern" : "Bearbeiten"}</span>
                      </button>
                      <button
                        onClick={() => handleDeleteConnector(c.source_type)}
                        disabled={deletingSource === c.source_type}
                        className="px-3 py-1.5 rounded-xl bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-600 font-semibold transition-colors disabled:opacity-50 inline-flex items-center gap-1"
                        title="1-Klick Connector Trennen & Löschen"
                      >
                        <Trash2 className="w-3 h-3" />
                        <span>Löschen</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center bg-slate-50 border border-slate-200 rounded-2xl">
            <p className="text-xs text-slate-500 mb-3">Noch keine aktiven Connectoren konfiguriert.</p>
            <button
              onClick={() => onOpenConfigureModal()}
              className="px-4 py-2 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all shadow-md shadow-[#0d5c3a]/20"
            >
              Ersten Connector Hinzufügen
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
