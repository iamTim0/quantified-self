"use client";

import React, { useState, useEffect } from "react";
import { X, Share2, Shield, Trash2 } from "lucide-react";

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
  token: string;
}

export default function ShareModal({ isOpen, onClose, apiBase, token }: ShareModalProps) {
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
      fetch(`${apiBase}/api/v1/data/shares`, {
        headers: { Authorization: `Bearer ${token}` }
      })
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
  }, [isOpen, apiBase, token]);

  const handleShare = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setSuccess("");

    try {
      const res = await fetch(`${apiBase}/api/v1/data/shares`, {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ grantee_email: email, scope: "read_all" })
      });
      const data = await res.json();
      
      if (!res.ok) {
        throw new Error(data.detail || "Failed to share data");
      }
      
      setSuccess(`Data successfully shared with ${email}`);
      setEmail("");
      
      const refreshRes = await fetch(`${apiBase}/api/v1/data/shares`, {
        headers: { Authorization: `Bearer ${token}` }
      });
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
      const res = await fetch(`${apiBase}/api/v1/data/shares/${shareId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` }
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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm transition-all">
      <div className="bg-neutral-900 border border-neutral-800 rounded-2xl w-full max-w-md shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        <div className="p-6 border-b border-neutral-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-500/10 rounded-lg text-blue-400">
              <Share2 className="w-5 h-5" />
            </div>
            <h2 className="text-xl font-semibold text-white">Share Data</h2>
          </div>
          <button 
            onClick={handleClose}
            className="p-2 rounded-lg text-neutral-400 hover:text-white hover:bg-neutral-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-6">
          <form onSubmit={handleShare} className="space-y-4">
            <p className="text-sm text-neutral-400">
              Grant a friend, coach, or doctor secure read-only access to your health metrics.
            </p>
            
            {error && <p className="text-sm text-red-400">{error}</p>}
            {success && <p className="text-sm text-green-400">{success}</p>}

            <div>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="grantee@example.com"
                required
                className="w-full bg-neutral-950 border border-neutral-800 rounded-xl py-2.5 px-4 text-white placeholder-neutral-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
              />
            </div>
            
            <button 
              type="submit" 
              disabled={loading}
              className="w-full bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-xl py-2.5 transition-colors disabled:opacity-50"
            >
              {loading ? "Sharing..." : "Send Invite"}
            </button>
          </form>

          {shares.length > 0 && (
            <div className="pt-6 border-t border-neutral-800">
              <h3 className="text-sm font-medium text-neutral-400 mb-3 uppercase tracking-wider">Active Grants</h3>
              <div className="space-y-3">
                {shares.map(share => (
                  <div key={share.id} className="flex items-center justify-between p-3 rounded-xl border border-neutral-800 bg-neutral-950/50">
                    <div className="flex items-center gap-3">
                      <Shield className="w-4 h-4 text-neutral-500" />
                      <div>
                        <p className="text-sm text-white font-mono">{share.grantee_tenant_id?.substring(0, 8)}...</p>
                        <p className="text-xs text-neutral-500">{share.scope}</p>
                      </div>
                    </div>
                    <button 
                      onClick={() => handleRevoke(share.id)}
                      className="p-2 text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                      title="Revoke Access"
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
