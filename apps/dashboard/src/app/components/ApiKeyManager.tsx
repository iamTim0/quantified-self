"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Check,
  Copy,
  KeyRound,
  Loader2,
  Plug,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { apiFetch } from "../lib/api";
import { useI18n } from "../lib/i18n/provider";

/**
 * Management for tenant-bound inbound API keys.
 *
 * This replaces the old flow, where the "API key" was just the connector's stored
 * access token: compared in plaintext, with the tenant taken from a header the
 * caller supplied. Keys are now minted server-side, stored only as a hash, bound
 * to one tenant and one connector, and shown exactly once.
 */

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  source_type: string;
  /** The connector instance this key pushes to. */
  source_id: string | null;
  scopes: string[];
  status: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  rotated_from_id: string | null;
  created_at: string | null;
}

interface ApiKeyManagerProps {
  apiBase: string;
  sourceType: string;
  /**
   * Which connector instance keys belong to. A key now decides the `source_id` of
   * every point pushed under it, so with two Apple Health connectors the type
   * alone no longer says where the data lands. Empty while the connector is being
   * created and has no id yet.
   */
  sourceId?: string;
  ingestPath: string;
  providerLabel: string;
}

export default function ApiKeyManager({
  apiBase,
  sourceType,
  sourceId,
  ingestPath,
  providerLabel,
}: ApiKeyManagerProps) {
  const { t, formatDate } = useI18n();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [newKeyName, setNewKeyName] = useState("");
  const [expiresInDays, setExpiresInDays] = useState<number | "">("");
  // The plaintext key, held in memory only, shown once after creation/rotation.
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const headers = useCallback(() => ({ "Content-Type": "application/json" }), []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/api-keys`, { headers: headers() });
      if (res.ok) {
        const all: ApiKey[] = (await res.json()).api_keys || [];
        // Filtered to this instance when there is one, so a second Apple Health
        // connector does not display the first connector's keys as its own.
        setKeys(
          all.filter((k) => (sourceId ? k.source_id === sourceId : k.source_type === sourceType)),
        );
      }
    } catch {
      setError(t("apikeys.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [apiBase, headers, sourceType, sourceId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) await load();
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  const handleCreate = async () => {
    setBusy("create");
    setError("");
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/api-keys`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({
          name: newKeyName.trim() || `${providerLabel} Key`,
          source_type: sourceType,
          source_id: sourceId || undefined,
          expires_in_days: expiresInDays === "" ? undefined : Number(expiresInDays),
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || t("apikeys.createFailed"));
      setRevealedKey(data.api_key);
      setNewKeyName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const handleRotate = async (id: string) => {
    setBusy(id);
    setError("");
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/api-keys/${id}/rotate`, {
        method: "POST",
        headers: headers(),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || t("apikeys.rotationFailed"));
      setRevealedKey(data.api_key);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const handleRevoke = async (id: string, prefix: string) => {
    if (!confirm(t("apikeys.confirmRevoke", { prefix }))) return;
    setBusy(id);
    setError("");
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/api-keys/${id}/revoke`, {
        method: "POST",
        headers: headers(),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || t("apikeys.revokeFailed"));
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const copyKey = async () => {
    if (!revealedKey) return;
    try {
      await navigator.clipboard.writeText(revealedKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError(t("apikeys.copyFailed"));
    }
  };

  const activeKeys = keys.filter((k) => k.status === "active");

  return (
    <div className="space-y-3">
      <div className="space-y-2.5 rounded-2xl border border-emerald-200/80 bg-emerald-50/80 p-4">
        <div className="flex items-center gap-1.5 text-xs font-bold text-slate-900">
          <Plug className="h-4 w-4 text-[#0d5c3a]" />
          <span>{t("apikeys.webhookTitle", { provider: providerLabel })}</span>
        </div>
        <div className="space-y-1.5">
          <div className="text-[11px] font-bold text-slate-600">1. URL:</div>
          <div className="select-all break-all rounded-xl border border-slate-200 bg-white p-2 font-mono text-[11px] font-bold text-[#0d5c3a] shadow-sm">
            {apiBase}
            {ingestPath}
          </div>
        </div>
        <div className="space-y-1.5">
          <div className="text-[11px] font-bold text-slate-600">2. Header:</div>
          <div className="inline-block select-all rounded-xl border border-slate-200 bg-white p-2 font-mono text-[11px] font-extrabold text-slate-900 shadow-sm">
            {t("apikeys.headerExample")}
          </div>
          <p className="text-[11px] text-slate-500">{t("apikeys.headerHint")}</p>
        </div>
        <a
          href="/docs/features/api-keys/"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-[#0d5c3a] underline"
        >
          <BookOpen className="h-3.5 w-3.5" /> {t("apikeys.docs")}
        </a>
      </div>

      {revealedKey && (
        <div className="space-y-2 rounded-2xl border border-amber-300 bg-amber-50 p-4">
          <div className="flex items-center gap-1.5 text-xs font-bold text-amber-900">
            <AlertTriangle className="h-4 w-4" />
            {t("apikeys.shownOnce")}
          </div>
          <div className="flex items-center gap-2">
            <code className="flex-1 select-all break-all rounded-xl border border-amber-200 bg-white p-2.5 font-mono text-[11px] text-slate-900">
              {revealedKey}
            </code>
            <button
              type="button"
              onClick={copyKey}
              className="shrink-0 rounded-xl border border-amber-300 bg-white p-2.5 text-amber-800 hover:bg-amber-100"
              title={t("apikeys.copy")}
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
          <p className="text-[11px] text-amber-900">{t("apikeys.storeNow")}</p>
          <button
            type="button"
            onClick={() => setRevealedKey(null)}
            className="text-[11px] font-semibold text-amber-900 underline"
          >
            {t("apikeys.hideRevealed")}
          </button>
        </div>
      )}

      <div className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="mb-2.5 flex items-center gap-1.5">
          <KeyRound className="h-4 w-4 text-[#0d5c3a]" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-600">
            {t("apikeys.title", { count: activeKeys.length })}
          </h3>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />}
        </div>

        {keys.length === 0 && !loading && (
          <p className="mb-3 text-[11px] text-slate-500">
            {t("apikeys.none", { provider: providerLabel })}
          </p>
        )}

        <ul className="mb-3 space-y-2">
          {keys.map((k) => (
            <li
              key={k.id}
              className={`rounded-xl border p-2.5 ${
                k.status === "active"
                  ? "border-slate-200 bg-slate-50"
                  : "border-slate-200 bg-slate-100 opacity-60"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-[11px] font-bold text-slate-800">{k.name}</p>
                  <p className="font-mono text-[11px] text-slate-500">{k.key_prefix}…</p>
                  <p className="mt-0.5 text-[10px] text-slate-400">
                    {t("apikeys.created", { date: formatDate(k.created_at) })}
                    {k.expires_at &&
                      ` · ${t("apikeys.expires", { date: formatDate(k.expires_at) })}`}
                    {" · "}
                    {k.last_used_at
                      ? t("apikeys.lastUsed", { date: formatDate(k.last_used_at) })
                      : t("apikeys.neverUsed")}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                      k.status === "active"
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-slate-200 text-slate-600"
                    }`}
                  >
                    {k.status === "active" ? t("apikeys.statusActive") : t("apikeys.statusRevoked")}
                  </span>
                  {k.status === "active" && (
                    <>
                      <button
                        type="button"
                        onClick={() => handleRotate(k.id)}
                        disabled={busy === k.id}
                        title={t("apikeys.rotateTitle")}
                        className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-600 hover:bg-slate-100 disabled:opacity-50"
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleRevoke(k.id, k.key_prefix)}
                        disabled={busy === k.id}
                        title={t("apikeys.revokeTitle")}
                        className="rounded-lg border border-rose-200 bg-rose-50 p-1.5 text-rose-600 hover:bg-rose-100 disabled:opacity-50"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap items-end gap-2 border-t border-slate-100 pt-3">
          <label className="min-w-[140px] flex-1">
            <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Name
            </span>
            <input
              type="text"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              placeholder={t("apikeys.namePlaceholder")}
              className="w-full rounded-xl border border-slate-200 px-3 py-2 text-xs outline-none focus:border-[#0d5c3a]"
            />
          </label>
          <label>
            <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
              {t("apikeys.expiryLabel")}
            </span>
            <select
              value={expiresInDays}
              onChange={(e) =>
                setExpiresInDays(e.target.value === "" ? "" : Number(e.target.value))
              }
              className="rounded-xl border border-slate-200 px-3 py-2 text-xs outline-none"
            >
              <option value="">{t("apikeys.noExpiry")}</option>
              <option value={90}>{t("quality.windowDays", { count: 90 })}</option>
              <option value={365}>{t("common.years_one", { count: 1 })}</option>
              <option value={730}>{t("common.years_other", { count: 2 })}</option>
            </select>
          </label>
          <button
            type="button"
            onClick={handleCreate}
            disabled={busy === "create"}
            className="flex items-center gap-1.5 rounded-xl bg-[#0d5c3a] px-4 py-2 text-xs font-bold text-white hover:bg-[#08432a] disabled:opacity-50"
          >
            {busy === "create" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <KeyRound className="h-3.5 w-3.5" />
            )}
            {t("apikeys.create")}
          </button>
        </div>

        {activeKeys.length > 1 && (
          <p className="mt-2 text-[10px] text-slate-400">
            {t("apikeys.rotationHint")}
            App auf den neuen umgestellt ist.
          </p>
        )}
      </div>

      {error && (
        <p className="rounded-2xl border border-red-200 bg-red-50 px-3.5 py-2.5 text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
