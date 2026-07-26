"use client";

import React, { useState, useEffect } from "react";
import { Plug, RefreshCw, CheckCircle2, AlertCircle, ShieldCheck, UploadCloud, Key, Trash2 } from "lucide-react";

interface ConnectorInfo {
  id: string;
  source_type: string;
  status: string;
  masked_token: string;
  created_at?: string;
  updated_at?: string;
}

interface ConnectorsPageProps {
  apiBase: string;
  token: string;
  tenantId: string;
  onOpenConfigureModal: () => void;
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
          message: `Sync task queued successfully for ${sourceType.toUpperCase()}!`,
        });
      } else {
        const errData = await res.json().catch(() => ({}));
        const detail = errData.detail || `Failed to trigger sync for ${sourceType.toUpperCase()}`;
        setSyncStatus({
          type: "error",
          message: detail === "Connector not configured" ? `${sourceType.toUpperCase()} connector is not configured yet. Click 'Configure Connector' above to set it up.` : detail,
        });
      }
    } catch (err) {
      setSyncStatus({
        type: "error",
        message: `Error triggering sync task for ${sourceType.toUpperCase()}.`,
      });
    } finally {
      setSyncingSource(null);
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-xl font-bold text-white">Integrations & Data Connectors</h2>
          <p className="text-xs text-neutral-400">
            Manage your hardware sensors, fitness APIs, and CSV data importers.
          </p>
        </div>
        <button
          onClick={onOpenConfigureModal}
          className="flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition-colors shadow-lg shadow-blue-600/20"
        >
          <Plug className="w-3.5 h-3.5" />
          <span>Configure Connector</span>
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

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

        {/* Yazio API */}
        <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 flex flex-col justify-between space-y-4 backdrop-blur-md">
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-xs font-bold uppercase tracking-wider text-amber-400">Nutrition API</span>
              <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold">
                <ShieldCheck className="w-3 h-3" /> Active
              </span>
            </div>
            <h3 className="text-lg font-bold text-white">Yazio Nutrition v15</h3>
            <p className="text-xs text-neutral-400 leading-relaxed">
              Import consumed food items, daily calories, and macro breakdown from your Yazio diary.
            </p>
          </div>
          <button
            onClick={() => handleTriggerSync("yazio")}
            disabled={syncingSource === "yazio"}
            className="w-full flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-xl bg-neutral-800 hover:bg-neutral-700 text-white transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${syncingSource === "yazio" ? "animate-spin" : ""}`} />
            <span>{syncingSource === "yazio" ? "Triggering..." : "Sync Now"}</span>
          </button>
        </div>

        {/* Oura CSV Upload */}
        <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 flex flex-col justify-between space-y-4 backdrop-blur-md">
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-xs font-bold uppercase tracking-wider text-cyan-400">File Importer</span>
              <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-semibold">
                <UploadCloud className="w-3 h-3" /> CSV Export
              </span>
            </div>
            <h3 className="text-lg font-bold text-white">Oura CSV Upload</h3>
            <p className="text-xs text-neutral-400 leading-relaxed">
              Import historical Oura CSV export files directly into your workspace.
            </p>
          </div>
          <button
            onClick={onOpenConfigureModal}
            className="w-full flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-xl bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 transition-colors"
          >
            <UploadCloud className="w-3.5 h-3.5" />
            <span>Upload CSV File</span>
          </button>
        </div>
      </div>

      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md">
        <h3 className="text-sm font-semibold text-neutral-200 mb-4">Registered Connector Credentials</h3>
        {connectors.length > 0 ? (
          <div className="divide-y divide-neutral-800">
            {connectors.map((c) => (
              <div key={c.id} className="py-3 flex justify-between items-center text-xs">
                <div className="flex items-center gap-3">
                  <Key className="w-4 h-4 text-purple-400" />
                  <div>
                    <span className="font-bold text-white uppercase">{c.source_type}</span>
                    <span className="ml-2 font-mono text-neutral-500">({c.masked_token})</span>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    {c.status}
                  </span>
                  <button
                    onClick={() => handleTriggerSync(c.source_type)}
                    className="p-1.5 text-neutral-400 hover:text-white transition-colors"
                    title="Sync Now"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => handleDeleteConnector(c.source_type)}
                    className="p-1.5 text-neutral-400 hover:text-red-400 transition-colors"
                    title="Delete Credentials"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-neutral-500">No encrypted connectors saved yet.</p>
        )}
      </div>
    </div>
  );
}
