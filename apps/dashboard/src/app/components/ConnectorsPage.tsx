"use client";

import React, { useState, useEffect } from "react";
import { Plus, RefreshCw, Settings, ShieldCheck, Key, AlertTriangle, CheckCircle2 } from "lucide-react";

export interface ConnectorItem {
  id: string;
  tenant_id: string;
  source_type: string;
  status: string;
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
  onOpenConfigureModal: (connector?: ConnectorItem) => void;
}

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
        setSyncMessage({ text: `Sync gestartet für ${sourceType.toUpperCase()}: ${data.message || "Erfolgreich gequeut"}`, type: "success" });
        fetchConnectors();
      } else {
        setSyncMessage({ text: `Sync fehlgeschlagen: ${data.detail || "Unbekannter Fehler"}`, type: "error" });
      }
    } catch (err: any) {
      setSyncMessage({ text: `Netzwerkfehler beim Sync Start: ${err.message}`, type: "error" });
    } finally {
      setSyncingSource(null);
      setTimeout(() => setSyncMessage(null), 5000);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Connectoren & Ingestion</h1>
          <p className="text-xs text-slate-500 mt-1">
            Übersicht aller aktiv konfigurierten Datenquellen für deinen Workspace.
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

      {/* Main Connected Sources Table */}
      <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-4">
        <div className="flex justify-between items-center">
          <h3 className="text-sm font-bold text-slate-900">Konfigurierte Connections & Status</h3>
          <span className="text-xs font-semibold text-slate-400">
            {connectors.length} Connector{connectors.length === 1 ? "" : "en"} aktiv
          </span>
        </div>

        {loading ? (
          <div className="p-8 text-center text-xs text-slate-400">Lade Connector Konfigurationen...</div>
        ) : connectors.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-400 uppercase tracking-wider font-bold text-[11px]">
                  <th className="pb-3 px-3">Connection / Quelle</th>
                  <th className="pb-3 px-3">Status</th>
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
                      <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase bg-emerald-50 text-emerald-800 border border-emerald-200 flex items-center gap-1 w-fit">
                        <ShieldCheck className="w-3 h-3 text-emerald-600" />
                        <span>{c.status}</span>
                      </span>
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
                        disabled={syncingSource === c.source_type}
                        className="px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 font-semibold transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
                      >
                        <RefreshCw className={`w-3 h-3 ${syncingSource === c.source_type ? "animate-spin" : ""}`} />
                        <span>Sync</span>
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
