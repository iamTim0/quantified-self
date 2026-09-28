"use client";

import React, { useState } from "react";
import { Activity, Lock, Mail, User, ArrowRight, AlertCircle } from "lucide-react";
import { SessionUser } from "../lib/session";
import { useT } from "../lib/i18n/provider";
import LanguageSwitcher from "./LanguageSwitcher";

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
  const t = useT();
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
        throw new Error(data?.detail || t("auth.providerUnavailable"));
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
    return t("auth.failed");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    const endpoint = isLogin ? "/api/v1/auth/login" : "/api/v1/auth/signup";
    const body = isLogin ? { email, password } : { email, password, name };

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
      const fallbackWorkspace = t("profile.defaultWorkspace", { name: data.name || fallbackName });
      onLogin({
        user: {
          userId: data.user_id,
          tenantId: data.tenant_id,
          email: data.email || email,
          name: data.name || fallbackName,
          role: data.role || "owner",
          workspaceName: data.workspace_name || fallbackWorkspace,
        },
        tenantName: data.workspace_name || fallbackWorkspace,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const lowered = error.toLowerCase();
  const isAlreadyRegistered =
    lowered.includes("already registered") || lowered.includes("already exists");

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-page p-4 pb-[max(1rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-[max(1rem,env(safe-area-inset-top))]">
      <div className="w-full max-w-md">
        <div className="mb-4 flex justify-end">
          <LanguageSwitcher />
        </div>

        <div className="mb-8 text-center">
          <div className="mb-4 inline-flex items-center justify-center rounded-2xl bg-brand p-3.5 text-brand-ink">
            <Activity className="w-8 h-8" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-ink">Quantified Self</h1>
          <p className="mt-2 text-body text-ink-secondary">{t("auth.tagline")}</p>
        </div>

        <div className="rounded-3xl border border-line bg-surface p-6 sm:p-8">
          <h2 className="mb-6 text-xl font-semibold text-ink">
            {isLogin ? t("auth.welcomeBack") : t("auth.createAccount")}
          </h2>

          {error && (
            <div
              role="alert"
              className="mb-4 p-3 rounded-2xl bg-danger-soft border border-danger-line text-danger-ink-on-soft text-xs font-medium space-y-1"
            >
              <div className="flex items-center gap-1.5 font-bold">
                <AlertCircle className="w-4 h-4 text-danger-ink-on-soft shrink-0" />
                <span>{error}</span>
              </div>
              {isAlreadyRegistered && (
                <button
                  type="button"
                  onClick={() => {
                    setIsLogin(true);
                    setError("");
                  }}
                  className="mt-1 text-xs font-bold text-brand hover:underline block"
                >
                  {t("auth.useExistingAccount")}
                </button>
              )}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {!isLogin && (
              <div>
                <label
                  htmlFor="auth-name"
                  className="mb-1.5 block text-body font-medium text-ink-secondary"
                >
                  {t("auth.name")}
                </label>
                <div className="relative">
                  <User className="absolute left-3.5 top-3 w-4 h-4 text-ink-muted" />
                  <input
                    id="auth-name"
                    name="name"
                    type="text"
                    autoComplete="name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    className="w-full rounded-xl border border-line bg-surface py-2.5 pl-10 pr-4 text-body text-ink outline-none transition-colors focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20"
                  />
                </div>
              </div>
            )}

            <div>
              <label
                htmlFor="auth-email"
                className="mb-1.5 block text-body font-medium text-ink-secondary"
              >
                {t("auth.email")}
              </label>
              <div className="relative">
                <Mail className="absolute left-3.5 top-3 w-4 h-4 text-ink-muted" />
                <input
                  id="auth-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  // An address is not a word; the red squiggle under it is noise.
                  spellCheck={false}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="w-full rounded-xl border border-line bg-surface py-2.5 pl-10 pr-4 text-body text-ink outline-none transition-colors focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20"
                />
              </div>
            </div>

            <div>
              <label
                htmlFor="auth-password"
                className="mb-1.5 block text-body font-medium text-ink-secondary"
              >
                {t("auth.password")}
              </label>
              <div className="relative">
                <Lock className="absolute left-3.5 top-3 w-4 h-4 text-ink-muted" />
                <input
                  id="auth-password"
                  name="password"
                  type="password"
                  // The distinction a manager acts on: offer the stored
                  // password, or offer to generate one.
                  autoComplete={isLogin ? "current-password" : "new-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="w-full rounded-xl border border-line bg-surface py-2.5 pl-10 pr-4 text-body text-ink outline-none transition-colors focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="group mt-2 flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 py-3 font-semibold text-brand-ink transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              {loading ? t("common.pleaseWait") : isLogin ? t("auth.signIn") : t("auth.signUp")}
              {!loading && (
                <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
              )}
            </button>
          </form>

          <div className="mt-6 text-center text-xs font-medium space-y-2">
            {allowRegistration ? (
              <div>
                <span className="text-ink-muted">
                  {isLogin ? t("auth.noAccount") : t("auth.haveAccount")}
                </span>
                <button
                  onClick={() => {
                    setIsLogin(!isLogin);
                    setError("");
                  }}
                  className="ml-2 text-brand hover:underline font-bold transition-colors"
                >
                  {isLogin ? t("auth.toSignUp") : t("auth.toSignIn")}
                </button>
              </div>
            ) : (
              <div className="text-ink-muted text-xs italic">{t("auth.registrationClosed")}</div>
            )}
            {providers.length > 0 && (
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <span className="h-px flex-1 bg-surface-muted" />
                  <span className="text-meta font-semibold uppercase tracking-wider text-ink-muted">
                    {t("auth.or")}
                  </span>
                  <span className="h-px flex-1 bg-surface-muted" />
                </div>
                {providers.map((provider) => (
                  <button
                    key={provider.slug}
                    type="button"
                    onClick={() => handleOidcLogin(provider.slug)}
                    disabled={startingProvider !== null}
                    className="w-full rounded-2xl border border-line bg-surface px-4 py-2.5 text-sm font-semibold text-ink-secondary transition-colors hover:bg-page disabled:opacity-50"
                  >
                    {startingProvider === provider.slug
                      ? t("auth.redirecting")
                      : t("auth.signInWith", { provider: provider.display_name })}
                  </button>
                ))}
              </div>
            )}

            <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs">
              <a
                href="/legal/datenschutz"
                className="text-ink-muted underline transition-colors hover:text-ink-muted"
              >
                {t("footer.privacy")}
              </a>
              <a
                href="/legal/impressum"
                className="text-ink-muted underline transition-colors hover:text-ink-muted"
              >
                {t("footer.imprint")}
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
