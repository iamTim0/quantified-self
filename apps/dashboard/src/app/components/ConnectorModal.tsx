"use client";

import React, { useState } from "react";
import { CheckCircle2, FileUp, Info, Key, Plug, X } from "lucide-react";

type ConnectorType = "oura" | "yazio" | "oura_csv";

interface ConnectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
  tenantId: string;
  token: string;
  apiBase?: string;
}

export default function ConnectorModal({
  isOpen,
  onClose,
  onSaved,
  tenantId,
  token,
  apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000",
}: ConnectorModalProps) {
  const [connectorType, setConnectorType] = useState<ConnectorType>("yazio");
  const [accessToken, setAccessToken] = useState("");
  const [yazioAuthMode, setYazioAuthMode] = useState<"token" | "login">("token");
  const [yazioEmail, setYazioEmail] = useState("");
  const [yazioPassword, setYazioPassword] = useState("");
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

    setLoading(true);
    try {
      if (connectorType === "oura_csv") {
        if (!file) {
          setError("Bitte wähle eine Oura-CSV-Datei aus.");
          setLoading(false);
          return;
        }
        if (!file.name.toLowerCase().endsWith(".csv")) {
          setError("Es können nur CSV-Dateien importiert werden.");
          setLoading(false);
          return;
        }
        if (file.size > 5_000_000) {
          setError("Die CSV-Datei darf maximal 5 MB groß sein.");
          setLoading(false);
          return;
        }

        const res = await fetch(`${apiBase}/api/v1/data/imports/oura/csv`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Tenant-ID": tenantId,
            Authorization: `Bearer ${token}`,
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
      } else {
        let finalToken = accessToken.trim();

        if (connectorType === "yazio" && yazioAuthMode === "login") {
          if (!yazioEmail.trim() || !yazioPassword.trim()) {
            setError("Bitte gib E-Mail und Passwort für deinen Yazio-Account ein.");
            setLoading(false);
            return;
          }
          const authParams = new URLSearchParams();
          authParams.append("client_id", "1_4hiybetvfksgw40o0sog4s884kwc840wwso8go4k8c04goo4c");
          authParams.append("client_secret", "6rok2m65xuskgkgogw40wkkk8sw0osg84s8cggsc4woos4s8o");
          authParams.append("grant_type", "password");
          authParams.append("username", yazioEmail.trim());
          authParams.append("password", yazioPassword.trim());

          const oauthRes = await fetch("https://yzapi.yazio.com/v15/oauth/token", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: authParams,
          });

          if (!oauthRes.ok) {
            setError("Yazio Login fehlgeschlagen: Ungültige E-Mail oder Passwort.");
            setLoading(false);
            return;
          }

          const oauthData = await oauthRes.json();
          finalToken = oauthData.access_token;
        }

        if (!finalToken) {
          setError("Bitte gib einen gültigen Access / Bearer Token ein.");
          setLoading(false);
          return;
        }

        const res = await fetch(`${apiBase}/api/v1/data/sources/configure`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Tenant-ID": tenantId,
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            source_type: connectorType,
            access_token: finalToken,
            status: "active",
          }),
        });

        if (res.ok) {
          const data = await res.json();
          setMessage(`Connector ${connectorType.toUpperCase()} erfolgreich konfiguriert (${data.masked_token}).`);
          setAccessToken("");
          setYazioEmail("");
          setYazioPassword("");
          onSaved();
        } else {
          const data = await res.json().catch(() => null);
          setError(data?.detail || "Fehler beim Speichern der Connector-Konfiguration.");
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError("Ein Fehler ist aufgetreten: " + msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md p-4">
      <div className="bg-[#111827] border border-white/10 rounded-2xl w-full max-w-lg p-6 shadow-2xl">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Plug className="w-5 h-5 text-blue-400" />
            <span>Connector Konfigurieren</span>
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Type Selector */}
        <div className="flex bg-neutral-900 border border-neutral-800 rounded-xl p-1 mb-6">
          <button
            type="button"
            onClick={() => setConnectorType("yazio")}
            className={`flex-1 py-2 text-xs font-semibold rounded-lg transition-colors ${
              connectorType === "yazio"
                ? "bg-blue-600 text-white shadow-md"
                : "text-neutral-400 hover:text-white"
            }`}
          >
            Yazio API Token
          </button>
          <button
            type="button"
            onClick={() => setConnectorType("oura_csv")}
            className={`flex-1 py-2 text-xs font-semibold rounded-lg transition-colors ${
              connectorType === "oura_csv"
                ? "bg-blue-600 text-white shadow-md"
                : "text-neutral-400 hover:text-white"
            }`}
          >
            Oura CSV Export
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {connectorType === "yazio" && (
            <div className="flex bg-neutral-950 border border-neutral-800 rounded-lg p-1 mb-3 text-xs">
              <button
                type="button"
                onClick={() => setYazioAuthMode("token")}
                className={`flex-1 py-1 rounded font-medium transition-colors ${
                  yazioAuthMode === "token" ? "bg-purple-600 text-white" : "text-neutral-400 hover:text-white"
                }`}
              >
                Bearer Token direkt eingeben
              </button>
              <button
                type="button"
                onClick={() => setYazioAuthMode("login")}
                className={`flex-1 py-1 rounded font-medium transition-colors ${
                  yazioAuthMode === "login" ? "bg-purple-600 text-white" : "text-neutral-400 hover:text-white"
                }`}
              >
                Yazio E-Mail & Passwort
              </button>
            </div>
          )}

          {connectorType !== "oura_csv" ? (
            connectorType === "yazio" && yazioAuthMode === "login" ? (
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1">
                    Yazio E-Mail
                  </label>
                  <input
                    type="email"
                    placeholder="name@example.com"
                    value={yazioEmail}
                    onChange={(e) => setYazioEmail(e.target.value)}
                    className="w-full px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-blue-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1">
                    Yazio Passwort
                  </label>
                  <input
                    type="password"
                    placeholder="••••••••"
                    value={yazioPassword}
                    onChange={(e) => setYazioPassword(e.target.value)}
                    className="w-full px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-blue-500 outline-none"
                  />
                </div>
                <p className="text-[11px] text-neutral-400">
                  Dein Passwort wird nur verwendet, um den Yazio Bearer Token direkt abzurufen, und niemals gespeichert.
                </p>
              </div>
            ) : (
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1.5 flex items-center gap-1.5">
                  <Key className="w-3.5 h-3.5 text-purple-400" />
                  <span>{connectorType === "oura" ? "Oura Personal Access Token" : "Yazio Bearer Access Token"}</span>
                </label>
                <input
                  type="password"
                  placeholder={connectorType === "oura" ? "z.B. eyJhbGciOi..." : "Füge deinen Yazio Bearer Token hier ein (z.B. eyJhbGciOi...)"}
                  value={accessToken}
                  onChange={(e) => setAccessToken(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-blue-500 outline-none font-mono"
                />
                <p className="mt-1.5 text-[11px] text-neutral-400">
                  Der Token wird Serverseitig mit AES-256 Fernet verschlüsselt gespeichert und für API requests verwendet.
                </p>
              </div>
            )
          ) : (
            <>
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
                <p>Unterstützt werden Oura-Exporte mit <code>day</code>, <code>date</code> oder <code>timestamp</code> sowie <code>score</code> oder <code>value</code>.</p>
              </div>
            </>
          )}

          {error && <p role="alert" className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</p>}
          {message && <p className="rounded-xl bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300 flex items-center gap-2"><CheckCircle2 className="w-4 h-4" />{message}</p>}

          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-semibold rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 text-gray-300 transition-colors"
            >
              Abbrechen
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 text-sm font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50"
            >
              {loading ? "Speichere..." : connectorType === "oura_csv" ? "CSV importieren" : "Token Speichern"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
