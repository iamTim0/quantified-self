"use client";

import React, { useState } from "react";
import { X, Lock, ShieldCheck } from "lucide-react";

interface ConnectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
  tenantId: string;
  token: string;
}

export default function ConnectorModal({ isOpen, onClose, onSaved, tenantId, token }: ConnectorModalProps) {
  const [sourceType, setSourceType] = useState("oura");
  const [accessToken, setAccessToken] = useState("");
  const [status, setStatus] = useState("active");
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!accessToken.trim()) {
      alert("Please enter a valid access token.");
      return;
    }

    setLoading(true);
    try {
      // SECURITY C5: Route through Gateway, not directly to Core
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiBase}/api/v1/data/sources/configure`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-ID": tenantId,
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          source_type: sourceType,
          access_token: accessToken,
          status: status,
        }),
      });

      if (res.ok) {
        alert(`Connector '${sourceType}' configured & encrypted successfully!`);
        setAccessToken("");
        onSaved();
        onClose();
      } else {
        alert("Failed to save connector configuration.");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      alert("Error submitting connector config: " + msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-md p-4">
      <div className="bg-[#111827] border border-white/10 rounded-2xl w-full max-w-lg p-6 shadow-2xl">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-blue-400" />
            <span>Configure Health Connector</span>
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
              Connector Provider
            </label>
            <select
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-blue-500 outline-none"
            >
              <option value="oura" className="bg-gray-900 text-white">Oura Ring v2 API</option>
              <option value="whoop" className="bg-gray-900 text-white">Whoop 4.0 API</option>
              <option value="apple_health" className="bg-gray-900 text-white">Apple Health (gRPC Bridge)</option>
              <option value="fitbit" className="bg-gray-900 text-white">Fitbit Web API</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
              Personal Access Token / API Secret
            </label>
            <input
              type="password"
              value={accessToken}
              onChange={(e) => setAccessToken(e.target.value)}
              placeholder="Paste your API access token..."
              className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-blue-500 outline-none"
            />
            <div className="flex items-center gap-1.5 mt-2 text-xs text-emerald-400">
              <Lock className="w-3.5 h-3.5" />
              <span>Secrets are encrypted using Fernet AES-256 at rest before database storage.</span>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
              Sync Status
            </label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-blue-500 outline-none"
            >
              <option value="active" className="bg-gray-900 text-white">Active (Periodic Sync)</option>
              <option value="inactive" className="bg-gray-900 text-white">Inactive (Paused)</option>
            </select>
          </div>

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
              {loading ? "Saving..." : "Save Connector Encrypted"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
