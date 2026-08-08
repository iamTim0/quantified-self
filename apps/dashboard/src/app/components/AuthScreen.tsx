"use client";

import React, { useState } from "react";
import { Activity, Lock, Mail, User, ArrowRight, AlertCircle } from "lucide-react";
import { SessionUser } from "../lib/session";

/**
 * What a completed sign-in hands back to the page.
 *
 * Deliberately carries no credential. The access and refresh tokens are set by
 * Core as httpOnly cookies on the login response, so there is nothing for this
 * component to receive, pass on, or store — only who the user turned out to be.
 */
export interface UserAuthData {
  user: SessionUser;
  tenantName: string;
}

interface AuthScreenProps {
  apiBase: string;
  onLogin: (data: UserAuthData) => void;
}

interface OidcProvider {
  slug: string;
  display_name: string;
}

export default function AuthScreen({ apiBase, onLogin }: AuthScreenProps) {
  const [isLogin, setIsLogin] = useState(true);
  const [allowRegistration, setAllowRegistration] = useState(true);
  const [providers, setProviders] = useState<OidcProvider[]>([]);
  const [startingProvider, setStartingProvider] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  React.useEffect(() => {
    fetch(`${apiBase}/api/v1/auth/config`)
      .then((res) => res.json())
      .then((data) => {
        if (typeof data.allow_registration === "boolean") {
          setAllowRegistration(data.allow_registration);
          if (!data.allow_registration) {
            setIsLogin(true);
          }
        }
      })
      .catch(() => {});
  }, [apiBase]);

  React.useEffect(() => {
    fetch(`${apiBase}/api/v1/auth/oidc/providers`)
      .then((res) => (res.ok ? res.json() : { providers: [] }))
      .then((data) => setProviders(data.providers ?? []))
      .catch(() => {
        // No providers configured is the normal case; a failure here must not
        // block email/password login.
      });
  }, [apiBase]);

  /**
   * Ask the server for an authorization URL and follow it.
   *
   * The state and PKCE verifier stay server-side; the browser only ever carries
   * the opaque state back on the redirect.
   */
  const handleOidcLogin = async (slug: string) => {
    setStartingProvider(slug);
    setError("");
    try {
      const res = await fetch(`${apiBase}/api/v1/auth/oidc/${slug}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.authorization_url) {
        throw new Error(data?.detail || "Anmeldung über diesen Anbieter ist nicht möglich.");
      }
      // Remembered so the callback knows which provider answered; one redirect
      // URI can then serve every configured provider.
      sessionStorage.setItem("qs_oidc_provider", slug);
      // A full navigation, not a client-side route: the next hop is the identity
      // provider's own origin.
      window.location.assign(data.authorization_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStartingProvider(null);
    }
  };

  const formatErrorMessage = (detail: unknown): string => {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return JSON.stringify(item);
        })
        .join("; ");
    }
    if (detail && typeof detail === "object") {
      if ("msg" in detail) return String((detail as { msg: unknown }).msg);
      return JSON.stringify(detail);
    }
    return "Authentifizierung fehlgeschlagen";
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    const endpoint = isLogin ? "/api/v1/auth/login" : "/api/v1/auth/signup";
    const body = isLogin
      ? { email, password }
      : { email, password, name };

    try {
      // credentials: "include" is what lets the browser keep the Set-Cookie the
      // server sends back. Without it the login would appear to succeed and every
      // subsequent request would be unauthenticated.
      const res = await fetch(`${apiBase}${endpoint}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(formatErrorMessage(data.detail));
      }

      // Signup already establishes a session, so there is no second login round
      // trip: the cookies are set by the signup response itself.
      const fallbackName = isLogin ? email.split("@")[0] : name;
      onLogin({
        user: {
          userId: data.user_id,
          tenantId: data.tenant_id,
          email: data.email || email,
          name: data.name || fallbackName,
          role: data.role || "owner",
        },
        tenantName: `${data.name || fallbackName}'s Workspace`,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const isAlreadyRegistered = error.toLowerCase().includes("already registered") || error.toLowerCase().includes("bereits registriert");

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col justify-center items-center p-4 relative overflow-hidden">
      {/* Background Orbs */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-emerald-500/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-teal-500/10 rounded-full blur-[120px] pointer-events-none" />

      <div className="z-10 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center p-3.5 rounded-3xl bg-[#0d5c3a] text-white mb-4 shadow-xl shadow-[#0d5c3a]/20">
            <Activity className="w-8 h-8" />
          </div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Quantified Self</h1>
          <p className="text-slate-500 text-xs mt-1.5 font-medium">Deine persönliche Gesundheits- & Analytics-Plattform.</p>
        </div>

        <div className="glass-card bg-white border border-slate-200/80 rounded-3xl p-8 shadow-xl">
          <h2 className="text-xl font-extrabold text-slate-900 mb-6">
            {isLogin ? "Willkommen zurück" : "Konto erstellen"}
          </h2>
          
          {error && (
            <div role="alert" className="mb-4 p-3 rounded-2xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium space-y-1">
              <div className="flex items-center gap-1.5 font-bold">
                <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
                <span>{error}</span>
              </div>
              {isAlreadyRegistered && (
                <button
                  type="button"
                  onClick={() => {
                    setIsLogin(true);
                    setError("");
                  }}
                  className="mt-1 text-xs font-bold text-[#0d5c3a] hover:underline block"
                >
                  ➜ Hier klicken, um dich direkt mit dieser E-Mail anzumelden.
                </button>
              )}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {!isLogin && (
              <div>
                <label htmlFor="auth-name" className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">Name</label>
                <div className="relative">
                  <User className="absolute left-3.5 top-3 w-4 h-4 text-slate-400" />
                  <input 
                    id="auth-name"
                    type="text" 
                    value={name}
                    onChange={e => setName(e.target.value)}
                    required 
                    className="w-full bg-white border border-slate-200 rounded-2xl py-2.5 pl-10 pr-4 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                    placeholder="Jane Doe"
                  />
                </div>
              </div>
            )}
            
            <div>
              <label htmlFor="auth-email" className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">E-Mail</label>
              <div className="relative">
                <Mail className="absolute left-3.5 top-3 w-4 h-4 text-slate-400" />
                <input 
                  id="auth-email"
                  type="email" 
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required 
                  className="w-full bg-white border border-slate-200 rounded-2xl py-2.5 pl-10 pr-4 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                  placeholder="you@example.com"
                />
              </div>
            </div>

            <div>
              <label htmlFor="auth-password" className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">Passwort</label>
              <div className="relative">
                <Lock className="absolute left-3.5 top-3 w-4 h-4 text-slate-400" />
                <input 
                  id="auth-password"
                  type="password" 
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required 
                  className="w-full bg-white border border-slate-200 rounded-2xl py-2.5 pl-10 pr-4 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                  placeholder="••••••••"
                />
              </div>
            </div>

            <button 
              type="submit" 
              disabled={loading}
              className="w-full bg-[#0d5c3a] hover:bg-[#08432a] text-white font-bold rounded-2xl py-3 px-4 mt-2 transition-all flex items-center justify-center gap-2 group disabled:opacity-50 shadow-md shadow-[#0d5c3a]/20"
            >
              {loading ? "Bitte warten..." : isLogin ? "Anmelden" : "Konto Registrieren"}
              {!loading && <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />}
            </button>
          </form>

          <div className="mt-6 text-center text-xs font-medium space-y-2">
            {allowRegistration ? (
              <div>
                <span className="text-slate-500">
                  {isLogin ? "Noch kein Konto?" : "Bereits registriert?"}
                </span>
                <button 
                  onClick={() => { setIsLogin(!isLogin); setError(""); }}
                  className="ml-2 text-[#0d5c3a] hover:underline font-bold transition-colors"
                >
                  {isLogin ? "Jetzt Registrieren" : "Hier Anmelden"}
                </button>
              </div>
            ) : (
              <div className="text-slate-400 text-xs italic">
                Neuregistrierung vom Administrator deaktiviert.
              </div>
            )}
            {providers.length > 0 && (
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <span className="h-px flex-1 bg-slate-200" />
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                    oder
                  </span>
                  <span className="h-px flex-1 bg-slate-200" />
                </div>
                {providers.map((provider) => (
                  <button
                    key={provider.slug}
                    type="button"
                    onClick={() => handleOidcLogin(provider.slug)}
                    disabled={startingProvider !== null}
                    className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50"
                  >
                    {startingProvider === provider.slug
                      ? "Weiterleitung…"
                      : `Mit ${provider.display_name} anmelden`}
                  </button>
                ))}
              </div>
            )}

            <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs">
              <a
                href="/legal/datenschutz"
                className="text-slate-400 underline transition-colors hover:text-slate-600"
              >
                Datenschutzerklärung
              </a>
              <a
                href="/legal/impressum"
                className="text-slate-400 underline transition-colors hover:text-slate-600"
              >
                Impressum
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
