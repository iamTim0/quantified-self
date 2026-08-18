"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, KeyRound, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { apiFetch } from "../lib/api";
import { useT } from "../lib/i18n/provider";

/**
 * Administration for external login providers.
 *
 * Providers were configurable only by inserting a row into `oidc_providers` by
 * hand. That meant a working feature nobody without database access could turn
 * on, and no record of who changed what.
 *
 * Two deliberate choices about the secret:
 *
 * - It is never sent back by the API, so this form cannot display it. The list
 *   shows only whether one is stored.
 * - Leaving the field blank on an edit keeps the stored value. Clearing it on
 *   every save would mean re-entering the secret to tick a checkbox.
 */

interface Provider {
  id: string;
  slug: string;
  display_name: string;
  issuer: string;
  client_id: string;
  has_client_secret: boolean;
  scopes: string;
  redirect_uri: string;
  claims_mapping: Record<string, string>;
  enabled: boolean;
  allow_signup: boolean;
  require_verified_email: boolean;
  updated_at: string | null;
}

type Draft = Omit<Provider, "id" | "has_client_secret" | "updated_at"> & {
  client_secret: string;
};

const emptyDraft = (): Draft => ({
  slug: "",
  display_name: "",
  issuer: "",
  client_id: "",
  client_secret: "",
  scopes: "openid email profile",
  redirect_uri: typeof window !== "undefined" ? `${window.location.origin}/auth/callback` : "",
  claims_mapping: {},
  enabled: false,
  allow_signup: false,
  require_verified_email: true,
});

export default function OidcProviderAdmin({ apiBase }: { apiBase: string }) {
  const t = useT();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/oidc/providers`);
      if (res.status === 403) {
        // Not an error to shout about: a member simply cannot manage providers.
        setProviders([]);
        setError(t("oidc.forbidden"));
        return;
      }
      if (!res.ok) throw new Error(t("oidc.loadFailed"));
      setProviders((await res.json()).providers ?? []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

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

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    setError("");
    try {
      const editing = editingSlug !== null;
      const res = await apiFetch(
        editing
          ? `${apiBase}/api/v1/data/oidc/providers/${encodeURIComponent(editingSlug)}`
          : `${apiBase}/api/v1/data/oidc/providers`,
        {
          method: editing ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...draft,
            // Omit rather than send an empty string, so the server keeps the
            // stored secret instead of overwriting it with nothing.
            client_secret: draft.client_secret || undefined,
          }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? t("oidc.saveFailed"));
      }
      setDraft(null);
      setEditingSlug(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (slug: string) => {
    setBusy(true);
    setError("");
    try {
      const res = await apiFetch(
        `${apiBase}/api/v1/data/oidc/providers/${encodeURIComponent(slug)}`,
        { method: "DELETE" },
      );
      if (!res.ok && res.status !== 204) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? t("oidc.deleteFailed"));
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const beginEdit = (provider: Provider) => {
    setEditingSlug(provider.slug);
    setDraft({
      slug: provider.slug,
      display_name: provider.display_name,
      issuer: provider.issuer,
      client_id: provider.client_id,
      client_secret: "",
      scopes: provider.scopes,
      redirect_uri: provider.redirect_uri,
      claims_mapping: provider.claims_mapping ?? {},
      enabled: provider.enabled,
      allow_signup: provider.allow_signup,
      require_verified_email: provider.require_verified_email,
    });
  };

  const field = (
    label: string,
    key: keyof Draft,
    props: React.InputHTMLAttributes<HTMLInputElement> = {},
  ) => (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold text-ink-muted">{label}</span>
      <input
        className="w-full rounded-2xl border border-line bg-surface px-4 py-2.5 text-sm text-ink outline-none focus-visible:border-brand"
        value={String(draft?.[key] ?? "")}
        onChange={(e) => setDraft((d) => (d ? { ...d, [key]: e.target.value } : d))}
        {...props}
      />
    </label>
  );

  const toggle = (
    label: string,
    key: "enabled" | "allow_signup" | "require_verified_email",
    hint: string,
  ) => (
    <label className="flex items-start gap-3 rounded-2xl border border-line bg-surface p-3">
      <input
        type="checkbox"
        className="mt-1"
        checked={Boolean(draft?.[key])}
        onChange={(e) => setDraft((d) => (d ? { ...d, [key]: e.target.checked } : d))}
      />
      <span>
        <span className="block text-sm font-semibold text-ink-secondary">{label}</span>
        <span className="block text-xs text-ink-muted">{hint}</span>
      </span>
    </label>
  );

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-ink">{t("oidc.title")}</h2>
          <p className="text-xs text-ink-muted">{t("oidc.subtitle")}</p>
        </div>
        {!draft && (
          <button
            onClick={() => {
              setEditingSlug(null);
              setDraft(emptyDraft());
            }}
            className="inline-flex items-center gap-2 rounded-2xl bg-brand px-4 py-2 text-sm font-bold text-brand-ink"
          >
            <Plus className="h-4 w-4" /> {t("oidc.add")}
          </button>
        )}
      </header>

      {error && (
        <p className="flex items-start gap-2 rounded-2xl border border-warn-line bg-warn-soft p-3 text-sm text-warn-ink">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-ink-muted">{t("oidc.loading")}</p>
      ) : providers.length === 0 && !draft ? (
        <p className="rounded-2xl border border-line bg-page p-4 text-sm text-ink-muted">
          {t("oidc.emptyState")}
        </p>
      ) : (
        <ul className="space-y-2">
          {providers.map((p) => (
            <li
              key={p.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-surface p-4"
            >
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-sm font-bold text-ink">
                  {p.display_name}
                  <span className="rounded-full bg-surface-muted px-2 py-0.5 font-mono text-xs font-normal text-ink-muted">
                    {p.slug}
                  </span>
                  {p.enabled ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-ok-soft px-2 py-0.5 text-xs font-semibold text-ok-ink">
                      <ShieldCheck className="h-3 w-3" /> {t("oidc.enabled")}
                    </span>
                  ) : (
                    <span className="rounded-full bg-surface-muted px-2 py-0.5 text-xs text-ink-muted">
                      deaktiviert
                    </span>
                  )}
                </p>
                <p className="truncate text-xs text-ink-muted">{p.issuer}</p>
                <p className="mt-1 flex items-center gap-1 text-xs text-ink-muted">
                  <KeyRound className="h-3 w-3" />
                  {p.has_client_secret ? t("oidc.hasSecret") : t("oidc.noSecret")}
                  {p.allow_signup && " · Registrierung erlaubt"}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => beginEdit(p)}
                  disabled={busy}
                  className="rounded-2xl border border-line px-3 py-1.5 text-xs font-semibold text-ink-secondary"
                >
                  Bearbeiten
                </button>
                <button
                  onClick={() => remove(p.slug)}
                  disabled={busy}
                  className="inline-flex items-center gap-1 rounded-2xl border border-danger-line px-3 py-1.5 text-xs font-semibold text-danger-ink-on-soft"
                >
                  <Trash2 className="h-3 w-3" /> {t("common.delete")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {draft && (
        <div className="space-y-3 rounded-3xl border border-line bg-page p-5">
          <h3 className="text-sm font-bold text-ink">
            {editingSlug ? t("oidc.editing", { slug: editingSlug }) : t("oidc.newProvider")}
          </h3>

          <div className="grid gap-3 sm:grid-cols-2">
            {field(t("oidc.fieldSlug"), "slug", {
              disabled: Boolean(editingSlug),
              placeholder: "google",
            })}
            {field(t("oidc.fieldDisplayName"), "display_name", { placeholder: "Google" })}
            {field(t("oidc.fieldIssuer"), "issuer", { placeholder: "https://accounts.google.com" })}
            {field(t("oidc.fieldClientId"), "client_id")}
            {field(t("oidc.fieldClientSecret"), "client_secret", {
              type: "password",
              placeholder: editingSlug ? t("oidc.secretUnchanged") : "",
            })}
            {field(t("oidc.fieldRedirectUri"), "redirect_uri")}
            {field(t("oidc.fieldScopes"), "scopes")}
          </div>

          <div className="grid gap-2 sm:grid-cols-3">
            {toggle(t("oidc.toggleEnabled"), "enabled", t("oidc.toggleEnabledHint"))}
            {toggle(t("oidc.toggleSignup"), "allow_signup", t("oidc.toggleSignupHint"))}
            {toggle(
              t("oidc.toggleVerified"),
              "require_verified_email",
              t("oidc.toggleVerifiedHint"),
            )}
          </div>

          <p className="text-xs text-ink-muted">{t("oidc.issuerHint")}</p>

          <div className="flex gap-2">
            <button
              onClick={save}
              disabled={busy}
              className="rounded-2xl bg-brand px-4 py-2 text-sm font-bold text-brand-ink disabled:opacity-50"
            >
              {busy ? t("common.saving") : t("common.save")}
            </button>
            <button
              onClick={() => {
                setDraft(null);
                setEditingSlug(null);
                setError("");
              }}
              disabled={busy}
              className="rounded-2xl border border-line px-4 py-2 text-sm font-semibold text-ink-secondary"
            >
              Abbrechen
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
