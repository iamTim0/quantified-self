"use client";

import React, { useState, useEffect } from "react";
import {
  Plus,
  RefreshCw,
  Settings,
  ShieldCheck,
  Key,
  AlertTriangle,
  CheckCircle2,
  Flame,
  MapPin,
  ArrowUpRight,
  Radio,
  Layers,
  Activity,
  Server
} from "lucide-react";

export interface ConnectorItem {
  id: string;
  tenant_id: string;
  source_type: string;
  status: string;
  sync_status?: string;
  last_sync_message?: string;
  last_request_id?: string;
  nats_subject?: string;
  nats_queue_group?: string;
  masked_token: string;
  poll_interval_hours: number;
  lookback_days: number;
  last_sync_at?: string;
  created_at?: string;
  updated_at?: string;
}

interface ConnectorsPageProps {
  tenantId: string;
  token: string;
  apiBase?: string;
  onOpenConfigureModal: (connector?: ConnectorItem, sourceType?: string) => void;
}

const AVAILABLE_CATALOG = [
  {
    id: "whoop",
    name: "WHOOP",
    category: "Recovery, Schlaf & Training",
    description: "Importiert Cycles, Recovery, Schlaf, Workouts und Herz-Kreislauf-Metriken über WHOOP OAuth.",
    icon: Activity,
    iconColor: "text-cyan-700 bg-cyan-50 border-cyan-200",
    natsSubject: "qs.task.sync.whoop",
    queueGroup: "whoop_importer_task_group",
  },
  {
    id: "yazio",
    name: "Yazio Nutrition v15",
    category: "Ernährung & Tagebuch",
    description: "Importiert Mahlzeiten, Lebensmittelnamen, Kalorien, Protein, Kohlenhydrate und Fett aus deinem Yazio-Tagebuch.",
    icon: Flame,
    iconColor: "text-amber-500 bg-amber-50 border-amber-200",
    natsSubject: "qs.task.sync.yazio",
    queueGroup: "yazio_importer_task_group",
  },
  {
    id: "dawarich",
    name: "Dawarich Location History",
    category: "Location & GPS Tracking",
    description: "Self-hosted Alternative zu Google Location History. Importiert Standorte, GPS-Punkte und Bewegungsstrecken.",
    icon: MapPin,
    iconColor: "text-emerald-600 bg-emerald-50 border-emerald-200",
    natsSubject: "qs.task.sync.dawarich",
    queueGroup: "dawarich_importer_task_group",
  },
];

export default function ConnectorsPage({
  tenantId,
  token,
  apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000",
  onOpenConfigureModal,
}: ConnectorsPageProps) {
  const [connectors, setConnectors] = useState<ConnectorItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncingSource, setSyncingSource] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

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
    fetchConnectors();
    // Auto-refresh connector status every 10s
    const interval = setInterval(fetchConnectors, 10000);
    return () => clearInterval(interval);
  }, [tenantId, token]);

  const handleTriggerSync = async (sourceType: string) => {
    setSyncingSource(sourceType);
    setSyncMessage(null);
    try {
      const res = await fetch(`${apiBase}/api/v1/data/sources/${sourceType}/sync`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": tenantId,
        },
        body: JSON.stringify({ source_type: sourceType }),
      });
      const data = await res.json();
      if (res.ok) {
        setSyncMessage({
          text: `NATS Event gequeut für ${sourceType.toUpperCase()} (Req-ID: ${data.request_id || "req_sync"})`,
          type: "success",
        });
        fetchConnectors();

        // Poll 3 times in quick succession to capture live queue execution
        setTimeout(fetchConnectors, 2000);
        setTimeout(fetchConnectors, 5000);
      } else {
        setSyncMessage({ text: `Sync fehlgeschlagen: ${data.detail || "Unbekannter Fehler"}`, type: "error" });
      }
    } catch (err: any) {
      setSyncMessage({ text: `Netzwerkfehler beim Sync Start: ${err.message}`, type: "error" });
    } finally {
      setSyncingSource(null);
      setTimeout(() => setSyncMessage(null), 6000);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Connectoren & Ingestion Pipeline</h1>
          <p className="text-xs text-slate-500 mt-1 flex items-center gap-2">
            <span>Verwalte verschlüsselte API-Tokens und NATS JetStream Event Importer.</span>
            <span className="inline-flex items-center gap-1 font-mono text-[10px] text-[#0d5c3a] font-bold bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
              <Radio className="w-3 h-3 text-emerald-600 animate-pulse" /> NATS JetStream Active
            </span>
          </p>
        </div>
        <button
          onClick={() => onOpenConfigureModal()}
          className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white text-xs font-bold transition-all shadow-md shadow-[#0d5c3a]/20"
        >
          <Plus className="w-4 h-4" />
          <span>Neuen Connector Verknüpfen</span>
        </button>
      </div>

      {syncMessage && (
        <div
          className={`p-4 rounded-2xl border text-xs flex items-center gap-2 ${
            syncMessage.type === "success"
              ? "bg-emerald-50 border-emerald-200 text-emerald-800"
              : "bg-rose-50 border-rose-200 text-rose-800"
          }`}
        >
          {syncMessage.type === "success" ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
          ) : (
            <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />
          )}
          <span>{syncMessage.text}</span>
        </div>
      )}

      {/* Available Connectors Cards Gallery */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {AVAILABLE_CATALOG.map((cat) => {
          const Icon = cat.icon;
          const configured = connectors.find((c) => c.source_type === cat.id);
          const isConfigured = !!configured;

          return (
            <div
              key={cat.id}
              className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl flex flex-col justify-between space-y-4 shadow-sm hover:shadow-md transition-all"
            >
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <div className={`w-10 h-10 rounded-2xl border flex items-center justify-center ${cat.iconColor}`}>
                    <Icon className="w-5 h-5" />
                  </div>
                  {isConfigured ? (
                    <span className="flex items-center gap-1.5 text-[10px] px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 font-bold">
                      <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                      <span>Aktiv & Bereit</span>
                    </span>
                  ) : (
                    <span className="text-[10px] px-2.5 py-1 rounded-full bg-slate-100 text-slate-500 border border-slate-200 font-bold">
                      Bereit zum Verknüpfen
                    </span>
                  )}
                </div>

                <div>
                  <h3 className="text-base font-extrabold text-slate-900">{cat.name}</h3>
                  <div className="text-[11px] font-semibold text-[#0d5c3a] mt-0.5">{cat.category}</div>
                </div>

                <p className="text-xs text-slate-500 leading-relaxed">{cat.description}</p>

                {/* Queue Transparency Panel */}
                <div className="p-3 bg-slate-50 border border-slate-200/60 rounded-2xl space-y-1.5">
                  <div className="flex items-center justify-between text-[11px] font-mono">
                    <span className="text-slate-400 flex items-center gap-1 font-sans">
                      <Layers className="w-3 h-3 text-[#0d5c3a]" /> NATS Subject:
                    </span>
                    <span className="font-bold text-slate-700 bg-white px-2 py-0.5 rounded border border-slate-200">
                      {cat.natsSubject}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-[11px] font-mono">
                    <span className="text-slate-400 flex items-center gap-1 font-sans">
                      <Server className="w-3 h-3 text-emerald-600" /> Queue Group:
                    </span>
                    <span className="font-semibold text-slate-600">
                      {cat.queueGroup}
                    </span>
                  </div>

                  {configured && (
                    <div className="flex items-center justify-between text-[11px] pt-1 border-t border-slate-200/60 text-slate-500">
                      <span className="flex items-center gap-1">
                        <Activity className="w-3 h-3 text-amber-500" /> Queue Status:
                      </span>
                      <span className={`font-bold uppercase text-[10px] px-2 py-0.5 rounded-full ${
                        configured.sync_status === "queued"
                          ? "bg-amber-100 text-amber-800 border border-amber-300 animate-pulse"
                          : "bg-emerald-100 text-emerald-800 border border-emerald-200"
                      }`}>
                        {configured.sync_status === "queued" ? "🟡 Event in Queue" : "🟢 Standby / Bereit"}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex gap-3 pt-2 border-t border-slate-100">
                {isConfigured ? (
                  <>
                    <button
                      onClick={() => handleTriggerSync(cat.id)}
                      disabled={syncingSource === cat.id}
                      className="flex-1 flex items-center justify-center gap-2 py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all disabled:opacity-50 shadow-md shadow-[#0d5c3a]/20"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${syncingSource === cat.id ? "animate-spin" : ""}`} />
                      <span>{syncingSource === cat.id ? "Queuing..." : "Jetzt Synchronisieren"}</span>
                    </button>
                    <button
                      onClick={() => onOpenConfigureModal(configured, cat.id)}
                      className="p-2.5 text-xs font-semibold rounded-2xl bg-slate-100 border border-slate-200 hover:bg-slate-200 text-slate-700 transition-colors"
                      title="Einstellungen bearbeiten"
                    >
                      <Settings className="w-4 h-4" />
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => onOpenConfigureModal(undefined, cat.id)}
                    className="w-full py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all shadow-md shadow-[#0d5c3a]/20 flex items-center justify-center gap-1.5"
                  >
                    <span>Jetzt Verknüpfen</span>
                    <ArrowUpRight className="w-3.5 h-3.5" />
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
                            : "bg-emerald-50 text-emerald-800 border-emerald-200"
                        }`}>
                          <Radio className={`w-3 h-3 ${c.sync_status === "queued" ? "text-amber-600 animate-spin" : "text-emerald-600"}`} />
                          <span>{c.sync_status === "queued" ? "Event gequeut (Processing)" : "Bereit / Active"}</span>
                        </span>
                        {c.last_sync_message && (
                          <div className="text-[10px] text-slate-500 font-mono leading-tight">
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
                        className="px-3 py-1.5 rounded-xl bg-[#0d5c3a] hover:bg-[#08432a] text-white font-semibold transition-colors shadow-xs inline-flex items-center gap-1"
                      >
                        <Settings className="w-3 h-3" />
                        <span>Bearbeiten</span>
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
