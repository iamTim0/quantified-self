"use client";

import React, { useState } from "react";
import { CheckCircle2, FileUp, Info, X } from "lucide-react";

interface ConnectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
  tenantId: string;
  token: string;
}

export default function ConnectorModal({ isOpen, onClose, onSaved, tenantId, token }: ConnectorModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [metricType, setMetricType] = useState("sleep_score");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    setError(null);
    if (!file) {
      setError("Bitte wähle eine Oura-CSV-Datei aus.");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setError("Es können nur CSV-Dateien importiert werden.");
      return;
    }
    if (file.size > 5_000_000) {
      setError("Die CSV-Datei darf maximal 5 MB groß sein.");
      return;
    }

    setLoading(true);
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiBase}/api/v1/data/imports/oura/csv`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-ID": tenantId,
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          file_name: file.name,
          csv_content: await file.text(),
          default_metric_type: metricType,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setMessage(`${data.inserted} Messwerte importiert${data.duplicates ? `, ${data.duplicates} Duplikate übersprungen` : ""}.`);
        setFile(null);
        onSaved();
      } else {
        const data = await res.json().catch(() => null);
        setError(data?.detail || "Der CSV-Import ist fehlgeschlagen.");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError("Beim CSV-Import ist ein Fehler aufgetreten: " + msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md p-4">
      <div className="bg-[#111827] border border-white/10 rounded-2xl w-full max-w-lg p-6 shadow-2xl">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <FileUp className="w-5 h-5 text-blue-400" />
            <span>Oura CSV importieren</span>
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
              Oura-CSV-Datei
            </label>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-gray-300 file:mr-4 file:rounded-lg file:border-0 file:bg-blue-600 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-blue-500"
            />
            {file && <p className="mt-2 text-xs text-gray-400">Ausgewählt: {file.name}</p>}
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
              Metrik der Datei
            </label>
            <select
              value={metricType}
              onChange={(e) => setMetricType(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-blue-500 outline-none"
            >
              <option value="sleep_score" className="bg-gray-900 text-white">Schlaf-Score</option>
              <option value="readiness_score" className="bg-gray-900 text-white">Readiness-Score</option>
              <option value="activity_score" className="bg-gray-900 text-white">Aktivitäts-Score</option>
              <option value="steps" className="bg-gray-900 text-white">Schritte</option>
              <option value="heart_rate" className="bg-gray-900 text-white">Herzfrequenz</option>
            </select>
          </div>

          <div className="rounded-xl border border-blue-400/20 bg-blue-400/10 p-3 text-xs text-blue-100 flex gap-2">
            <Info className="w-4 h-4 shrink-0 mt-0.5 text-blue-300" />
            <p>Unterstützt werden Oura-Exporte mit <code>day</code>, <code>date</code> oder <code>timestamp</code> sowie <code>score</code> oder <code>value</code>. Eine vorhandene Spalte <code>metric_type</code> überschreibt die Auswahl oben.</p>
          </div>

          {error && <p role="alert" className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</p>}
          {message && <p className="rounded-xl bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300 flex items-center gap-2"><CheckCircle2 className="w-4 h-4" />{message}</p>}

          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-semibold rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 text-gray-300 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 text-sm font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50"
            >
              {loading ? "Importiere..." : "CSV importieren"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
