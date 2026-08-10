"use client";

import React, { useState, useEffect } from "react";
import { X, Share2, Shield, Trash2, CheckCircle2 } from "lucide-react";
import { apiFetch } from "../lib/api";
import { useT } from "../lib/i18n/provider";

interface ShareItem {
  id: string;
  grantee_tenant_id?: string;
  grantor_tenant_id?: string;
  scope: string;
}

interface ShareModalProps {
  isOpen: boolean;
  onClose: () => void;
  apiBase: string;
}

export default function ShareModal({ isOpen, onClose, apiBase }: ShareModalProps) {
  const t = useT();
  const [email, setEmail] = useState("");
  const [shares, setShares] = useState<ShareItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const handleClose = () => {
    setError("");
    setSuccess("");
    setEmail("");
    onClose();
  };

  useEffect(() => {
    let isMounted = true;
    if (isOpen) {
      apiFetch(`${apiBase}/api/v1/data/shares`, {})
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (isMounted && data) {
            setShares(data.granted_by_me || []);
          }
        })
        .catch((err) => console.error("Failed to fetch shares", err));
    }
    return () => {
      isMounted = false;
    };
  }, [isOpen, apiBase]);

  const handleShare = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setSuccess("");

    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/shares`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ grantee_email: email, scope: "read_all" }),
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || t("share.failed"));
      }

      setSuccess(t("share.success", { email }));
      setEmail("");

      const refreshRes = await apiFetch(`${apiBase}/api/v1/data/shares`, {});
      if (refreshRes.ok) {
        const refreshData = await refreshRes.json();
        setShares(refreshData.granted_by_me || []);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleRevoke = async (shareId: string) => {
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/shares/${shareId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setShares((prev) => prev.filter((s) => s.id !== shareId));
      }
    } catch (err) {
      console.error("Failed to revoke share", err);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-md transition-all">
      <div className="bg-white border border-slate-200/90 rounded-3xl w-full max-w-md shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        <div className="p-6 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-emerald-50 rounded-2xl text-[#0d5c3a] border border-emerald-200">
              <Share2 className="w-5 h-5" />
            </div>
            <h2 className="text-lg font-extrabold text-slate-900">{t("share.title")}</h2>
          </div>
          <button
            onClick={handleClose}
            className="p-1.5 rounded-xl text-slate-400 hover:text-slate-900 hover:bg-slate-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          <form onSubmit={handleShare} className="space-y-4">
            <p className="text-xs text-slate-500 leading-relaxed">{t("share.intro")}</p>

            {error && (
              <p
                role="alert"
                className="text-xs font-semibold text-rose-700 bg-rose-50 p-3 rounded-2xl border border-rose-200"
              >
                {error}
              </p>
            )}
            {success && (
              <p className="text-xs font-semibold text-emerald-800 bg-emerald-50 p-3 rounded-2xl border border-emerald-200 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                {success}
              </p>
            )}

            <div>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t("share.emailPlaceholder")}
                required
                className="w-full bg-white border border-slate-200 rounded-2xl py-2.5 px-4 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-[#0d5c3a] hover:bg-[#08432a] text-white font-bold rounded-2xl py-3 text-xs transition-all disabled:opacity-50 shadow-md shadow-[#0d5c3a]/20"
            >
              {loading ? t("share.submitting") : t("share.submit")}
            </button>
          </form>

          {shares.length > 0 && (
            <div className="pt-4 border-t border-slate-100">
              <h3 className="text-xs font-bold text-slate-500 mb-3 uppercase tracking-wider">
                {t("share.activeTitle")}
              </h3>
              <div className="space-y-2">
                {shares.map((share) => (
                  <div
                    key={share.id}
                    className="flex items-center justify-between p-3 rounded-2xl border border-slate-200 bg-slate-50"
                  >
                    <div className="flex items-center gap-3">
                      <Shield className="w-4 h-4 text-[#0d5c3a]" />
                      <div>
                        <p className="text-xs text-slate-900 font-bold font-mono">
                          {share.grantee_tenant_id?.substring(0, 8)}...
                        </p>
                        <p className="text-[10px] text-slate-400">{share.scope}</p>
                      </div>
                    </div>
                    <button
                      onClick={() => handleRevoke(share.id)}
                      className="p-1.5 text-rose-600 hover:bg-rose-100 rounded-xl transition-colors"
                      title={t("share.revoke")}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
