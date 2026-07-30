"use client";

import React, { useState } from "react";
import { CheckCircle2, Key, Plug, X } from "lucide-react";

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
  const [accessToken, setAccessToken] = useState("");
  const [yazioAuthMode, setYazioAuthMode] = useState<"token" | "login">("token");
  const [yazioEmail, setYazioEmail] = useState("");
  const [yazioPassword, setYazioPassword] = useState("");
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
      let finalToken = accessToken.trim();
      let payloadConfig: Record<string, any> | undefined = undefined;

      if (yazioAuthMode === "login") {
        if (!yazioEmail.trim() || !yazioPassword.trim()) {
          setError("Bitte gib E-Mail und Passwort für deinen Yazio-Account ein.");
          setLoading(false);
          return;
        }
        finalToken = "SERVER_OAUTH_LOGIN";
        payloadConfig = {
          yazio_email: yazioEmail.trim(),
          yazio_password: yazioPassword.trim(),
        };
      } else if (!finalToken) {
        setError("Bitte gib einen Yazio Bearer Token ein.");
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
          source_type: "yazio",
          access_token: finalToken,
          status: "active",
          config: payloadConfig,
        }),
      });

      if (res.ok) {
        setMessage("Yazio Connector erfolgreich konfiguriert!");
        setAccessToken("");
        setYazioEmail("");
        setYazioPassword("");
        onSaved();
        setTimeout(() => {
          onClose();
        }, 1200);
      } else {
        const data = await res.json().catch(() => null);
        setError(data?.detail || "Konfiguration konnte nicht gespeichert werden.");
      }
    } catch (err: any) {
      setError(`Netzwerkfehler: ${err?.message || "Server nicht erreichbar"}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="w-full max-w-md bg-neutral-950 border border-neutral-800 rounded-2xl p-6 shadow-2xl space-y-6">
        <div className="flex justify-between items-center pb-4 border-b border-neutral-800">
          <div className="flex items-center gap-2.5 text-white">
            <Plug className="w-5 h-5 text-blue-400" />
            <h2 className="text-lg font-bold">Yazio Connector konfigurieren</h2>
          </div>
          <button
            onClick={onClose}
            className="text-neutral-400 hover:text-white p-1 rounded-lg hover:bg-neutral-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex bg-neutral-900 border border-neutral-800 rounded-lg p-1 mb-3 text-xs">
            <button
              type="button"
              onClick={() => setYazioAuthMode("token")}
              className={`flex-1 py-1.5 rounded font-medium transition-colors ${
                yazioAuthMode === "token" ? "bg-purple-600 text-white" : "text-neutral-400 hover:text-white"
              }`}
            >
              Bearer Token direkt eingeben
            </button>
            <button
              type="button"
              onClick={() => setYazioAuthMode("login")}
              className={`flex-1 py-1.5 rounded font-medium transition-colors ${
                yazioAuthMode === "login" ? "bg-purple-600 text-white" : "text-neutral-400 hover:text-white"
              }`}
            >
              Yazio E-Mail & Passwort
            </button>
          </div>

          {yazioAuthMode === "login" ? (
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
                Dein Passwort wird nur verwendet, um den Yazio Bearer Token abzurufen.
              </p>
            </div>
          ) : (
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1.5 flex items-center gap-1.5">
                <Key className="w-3.5 h-3.5 text-purple-400" />
                <span>Yazio Bearer Access Token</span>
              </label>
              <input
                type="password"
                placeholder="Füge deinen Yazio Bearer Token hier ein (z.B. eyJhbGciOi...)"
                value={accessToken}
                onChange={(e) => setAccessToken(e.target.value)}
                className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-blue-500 outline-none font-mono"
              />
              <p className="mt-1.5 text-[11px] text-neutral-400">
                Der Token wird Serverseitig mit AES-256 Fernet verschlüsselt gespeichert.
              </p>
            </div>
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
              {loading ? "Speichere..." : "Token Speichern"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
