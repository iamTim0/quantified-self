"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, KeyRound, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { apiFetch } from "../lib/api";

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
        setError("Nur Inhaber und Administratoren können Anbieter verwalten.");
        return;
      }
      if (!res.ok) throw new Error("Anbieter konnten nicht geladen werden.");
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
        throw new Error(body?.detail ?? "Speichern fehlgeschlagen.");
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
        throw new Error(body?.detail ?? "Löschen fehlgeschlagen.");
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
      <span className="mb-1 block text-xs font-semibold text-slate-600">{label}</span>
      <input
        className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 outline-none focus:border-emerald-500"
        value={String(draft?.[key] ?? "")}
        onChange={(e) => setDraft((d) => (d ? { ...d, [key]: e.target.value } : d))}
        {...props}
      />
    </label>
  );

  const toggle = (label: string, key: "enabled" | "allow_signup" | "require_verified_email", hint: string) => (
    <label className="flex items-start gap-3 rounded-2xl border border-slate-200 bg-white p-3">
      <input
        type="checkbox"
        className="mt-1"
        checked={Boolean(draft?.[key])}
        onChange={(e) => setDraft((d) => (d ? { ...d, [key]: e.target.checked } : d))}
      />
      <span>
        <span className="block text-sm font-semibold text-slate-800">{label}</span>
        <span className="block text-xs text-slate-500">{hint}</span>
      </span>
    </label>
  );

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-900">Externe Anmeldeanbieter</h2>
          <p className="text-xs text-slate-500">
            OpenID Connect. Anbieter sind standardmäßig deaktiviert.
          </p>
        </div>
        {!draft && (
          <button
            onClick={() => {
              setEditingSlug(null);
              setDraft(emptyDraft());
            }}
            className="inline-flex items-center gap-2 rounded-2xl bg-[#0d5c3a] px-4 py-2 text-sm font-bold text-white"
          >
            <Plus className="h-4 w-4" /> Anbieter hinzufügen
          </button>
        )}
      </header>

      {error && (
        <p className="flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-slate-400">Anbieter werden geladen…</p>
      ) : providers.length === 0 && !draft ? (
        <p className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
          Noch kein Anbieter konfiguriert. Die Anmeldung per E-Mail und Passwort
          funktioniert unabhängig davon.
        </p>
      ) : (
        <ul className="space-y-2">
          {providers.map((p) => (
            <li
              key={p.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white p-4"
            >
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-sm font-bold text-slate-900">
                  {p.display_name}
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-xs font-normal text-slate-500">
                    {p.slug}
                  </span>
                  {p.enabled ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                      <ShieldCheck className="h-3 w-3" /> aktiv
                    </span>
                  ) : (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                      deaktiviert
                    </span>
                  )}
                </p>
                <p className="truncate text-xs text-slate-500">{p.issuer}</p>
                <p className="mt-1 flex items-center gap-1 text-xs text-slate-400">
                  <KeyRound className="h-3 w-3" />
                  {p.has_client_secret ? "Client Secret hinterlegt" : "Kein Client Secret (Public Client)"}
                  {p.allow_signup && " · Registrierung erlaubt"}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => beginEdit(p)}
                  disabled={busy}
                  className="rounded-2xl border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700"
                >
                  Bearbeiten
                </button>
                <button
                  onClick={() => remove(p.slug)}
                  disabled={busy}
                  className="inline-flex items-center gap-1 rounded-2xl border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-700"
                >
                  <Trash2 className="h-3 w-3" /> Löschen
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {draft && (
        <div className="space-y-3 rounded-3xl border border-slate-200 bg-slate-50 p-5">
          <h3 className="text-sm font-bold text-slate-900">
            {editingSlug ? `${editingSlug} bearbeiten` : "Neuer Anbieter"}
          </h3>

          <div className="grid gap-3 sm:grid-cols-2">
            {field("Slug (URL-Teil)", "slug", {
              disabled: Boolean(editingSlug),
              placeholder: "google",
            })}
            {field("Anzeigename", "display_name", { placeholder: "Google" })}
            {field("Issuer", "issuer", { placeholder: "https://accounts.google.com" })}
            {field("Client ID", "client_id")}
            {field("Client Secret", "client_secret", {
              type: "password",
              placeholder: editingSlug ? "•••••••• (unverändert lassen)" : "",
            })}
            {field("Redirect URI", "redirect_uri")}
            {field("Scopes", "scopes")}
          </div>

          <div className="grid gap-2 sm:grid-cols-3">
            {toggle("Aktiv", "enabled", "Erscheint auf der Anmeldeseite.")}
            {toggle(
              "Registrierung erlauben",
              "allow_signup",
              "Legt bei unbekannter Identität ein neues Konto an.",
            )}
            {toggle(
              "Verifizierte E-Mail verlangen",
              "require_verified_email",
              "Empfohlen. Ohne Verifizierung ist die Adresse keine Identität.",
            )}
          </div>

          <p className="text-xs text-slate-500">
            Der Issuer wird beim Speichern geprüft: das Discovery-Dokument muss
            erreichbar sein und denselben Issuer nennen.
          </p>

          <div className="flex gap-2">
            <button
              onClick={save}
              disabled={busy}
              className="rounded-2xl bg-[#0d5c3a] px-4 py-2 text-sm font-bold text-white disabled:opacity-50"
            >
              {busy ? "Speichern…" : "Speichern"}
            </button>
            <button
              onClick={() => {
                setDraft(null);
                setEditingSlug(null);
                setError("");
              }}
              disabled={busy}
              className="rounded-2xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700"
            >
              Abbrechen
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
