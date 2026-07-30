"use client";

import React, { useState, useEffect } from "react";
import { Plug, RefreshCw, CheckCircle2, AlertCircle, ShieldCheck, Key, Trash2, Clock, Calendar, Settings } from "lucide-react";

export interface ConnectorInfo {
  id: string;
  source_type: string;
  status: string;
  masked_token: string;
  poll_interval_hours?: number;
  lookback_days?: number;
  last_sync_at?: string;
  created_at?: string;
  updated_at?: string;
}

interface ConnectorsPageProps {
  apiBase: string;
  token: string;
  tenantId: string;
  onOpenConfigureModal: (connector?: ConnectorInfo) => void;
}

export default function ConnectorsPage({
  apiBase,
  token,
  tenantId,
  onOpenConfigureModal,
}: ConnectorsPageProps) {
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncingSource, setSyncingSource] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<{ type: "success" | "error"; message: string } | null>(null);

  async function fetchConnectors() {
    setLoading(true);
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
      console.error("Failed to fetch connectors:", err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (token && tenantId) {
      fetchConnectors();
    }
  }, [apiBase, token, tenantId]);

  const handleDeleteConnector = async (sourceType: string) => {
    if (!confirm(`Möchtest Du die Zugangsdaten für ${sourceType.toUpperCase()} wirklich löschen?`)) {
      return;
    }
    setSyncStatus(null);
    try {
      const res = await fetch(`${apiBase}/api/v1/data/sources/${sourceType}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": tenantId,
        },
      });
      if (res.ok) {
        setSyncStatus({
          type: "success",
          message: `Zugangsdaten für ${sourceType.toUpperCase()} wurden gelöscht.`,
        });
        fetchConnectors();
      } else {
        const data = await res.json().catch(() => ({}));
        setSyncStatus({
          type: "error",
          message: data.detail || `Fehler beim Löschen des Connectors ${sourceType.toUpperCase()}`,
        });
      }
    } catch (err) {
      setSyncStatus({
        type: "error",
        message: `Fehler beim Löschen des Connectors ${sourceType.toUpperCase()}`,
      });
    }
  };

  const handleTriggerSync = async (sourceType: string) => {
    setSyncingSource(sourceType);
    setSyncStatus(null);
    try {
      const res = await fetch(`${apiBase}/api/v1/data/sources/${sourceType}/sync`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": tenantId,
        },
      });
      if (res.ok) {
        setSyncStatus({
          type: "success",
          message: `Sync gestartet für ${sourceType.toUpperCase()}! Import läuft im Hintergrund.`,
        });
        fetchConnectors();
      } else {
        const errData = await res.json().catch(() => ({}));
        const detail = errData.detail || `Fehler beim Sync für ${sourceType.toUpperCase()}`;
        setSyncStatus({
          type: "error",
          message: detail === "Connector not configured" ? `${sourceType.toUpperCase()} Connector ist noch nicht konfiguriert.` : detail,
        });
      }
    } catch (err) {
      setSyncStatus({
        type: "error",
        message: `Fehler beim Auslösen des Syncs für ${sourceType.toUpperCase()}.`,
      });
    } finally {
      setSyncingSource(null);
    }
  };

  const formatLastSync = (isoString?: string) => {
    if (!isoString) return "Noch nie synchronisiert";
    try {
      const d = new Date(isoString);
      const now = new Date();
      const diffMs = now.getTime() - d.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      if (diffMins < 1) return "Gerade eben";
      if (diffMins < 60) return `Vor ${diffMins} Min (${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})`;
      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `Vor ${diffHours} Std (${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})`;
      return d.toLocaleDateString([], { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-xl font-bold text-white">Integrations & Connection Manager</h2>
          <p className="text-xs text-neutral-400">
            Übersicht und Konfiguration aller verknüpften Datenquellen, Sync-Zeiten und Abfrage-Frequenzen.
          </p>
        </div>
        <button
          onClick={() => onOpenConfigureModal()}
          className="flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition-colors shadow-lg shadow-blue-600/20"
        >
          <Plug className="w-3.5 h-3.5" />
          <span>Neue Verbindung hinzufügen</span>
        </button>
      </div>

      {syncStatus && (
        <div
          className={`rounded-xl border p-3 text-xs flex items-center gap-2 ${
            syncStatus.type === "success"
              ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
              : "border-red-500/20 bg-red-500/10 text-red-300"
          }`}
        >
          {syncStatus.type === "success" ? (
            <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
          ) : (
            <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
          )}
          <span>{syncStatus.message}</span>
        </div>
      )}

      {/* Overview Card for Yazio */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 flex flex-col justify-between space-y-4 backdrop-blur-md">
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-xs font-bold uppercase tracking-wider text-amber-400">Nutrition Connector</span>
              <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold">
                <ShieldCheck className="w-3 h-3" /> Aktiv
              </span>
            </div>
            <h3 className="text-lg font-bold text-white">Yazio Nutrition v15</h3>
            <p className="text-xs text-neutral-400 leading-relaxed">
              Automatischer Import von Mahlzeiten, Lebensmittelnamen, Kalorien und Makronährstoffen.
            </p>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => handleTriggerSync("yazio")}
              disabled={syncingSource === "yazio"}
              className="flex-1 flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${syncingSource === "yazio" ? "animate-spin" : ""}`} />
              <span>{syncingSource === "yazio" ? "Import läuft..." : "Jetzt Synchronisieren"}</span>
            </button>
            <button
              onClick={() => onOpenConfigureModal(connectors.find(c => c.source_type === "yazio"))}
              className="p-2 text-xs font-semibold rounded-xl bg-neutral-800 hover:bg-neutral-700 text-neutral-300 transition-colors"
              title="Einstellungen & Frequenz anpassen"
            >
              <Settings className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Main Connected Sources Table */}
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md space-y-4">
        <h3 className="text-sm font-semibold text-neutral-200">Verknüpfte Connections & Sync-Status</h3>
        {connectors.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-neutral-800 text-neutral-400 uppercase tracking-wider font-semibold text-[11px]">
                  <th className="pb-3 px-3">Connection / Quelle</th>
                  <th className="pb-3 px-3">Status</th>
                  <th className="pb-3 px-3">Letzter Sync</th>
                  <th className="pb-3 px-3">Abfrage-Frequenz</th>
                  <th className="pb-3 px-3 text-right">Aktionen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/60">
                {connectors.map((c) => (
                  <tr key={c.id} className="hover:bg-neutral-800/40 transition-colors">
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-2.5">
                        <Key className="w-4 h-4 text-purple-400" />
                        <div>
                          <span className="font-bold text-white uppercase">{c.source_type}</span>
                          <span className="ml-2 font-mono text-neutral-500">({c.masked_token})</span>
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-3">
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        {c.status}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-neutral-300 font-medium">
                      <div className="flex items-center gap-1.5">
                        <Clock className="w-3.5 h-3.5 text-blue-400" />
                        <span>{formatLastSync(c.last_sync_at)}</span>
                      </div>
                    </td>
                    <td className="py-3 px-3 text-neutral-300">
                      <div className="flex items-center gap-1.5">
                        <Calendar className="w-3.5 h-3.5 text-emerald-400" />
                        <span>Alle {c.poll_interval_hours || 6} Std ({c.lookback_days || 30} Tage Lookback)</span>
                      </div>
                    </td>
                    <td className="py-3 px-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleTriggerSync(c.source_type)}
                          disabled={syncingSource === c.source_type}
                          className="p-1.5 text-neutral-400 hover:text-white transition-colors"
                          title="Jetzt Synchronisieren"
                        >
                          <RefreshCw className={`w-4 h-4 ${syncingSource === c.source_type ? "animate-spin" : ""}`} />
                        </button>
                        <button
                          onClick={() => onOpenConfigureModal(c)}
                          className="p-1.5 text-neutral-400 hover:text-blue-400 transition-colors"
                          title="Frequenz & Intervall anpassen"
                        >
                          <Settings className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDeleteConnector(c.source_type)}
                          className="p-1.5 text-neutral-400 hover:text-red-400 transition-colors"
                          title="Verbindung trennen"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-neutral-500">Noch keine aktiven Verbindungen eingerichtet.</p>
        )}
      </div>
    </div>
  );
}
