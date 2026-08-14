"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { useT, type MessageKey } from "../../lib/i18n/provider";

/**
 * OIDC redirect target.
 *
 * The provider sends the browser here with `code` and `state`. Neither is a
 * credential on its own: the server holds the matching single-use state row and
 * the PKCE verifier, so this page just hands both back and receives a session.
 *
 * The session arrives as httpOnly cookies on the callback response, so there is
 * nothing to save here — the redirect to `/` finds an authenticated browser.
 *
 * The provider slug travels in `state_provider` rather than being guessed from
 * the URL, so one redirect URI serves every configured provider.
 */
function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState("");
  const t = useT();
  // State holds a key, not a finished sentence: a rendered string would stay
  // in whatever language it was set in when the reader switches.
  const [status, setStatus] = useState<MessageKey>("auth.callbackWorking");

  const apiBase =
    process.env.NEXT_PUBLIC_API_URL ||
    (typeof window !== "undefined" ? window.location.origin : "");

  const complete = useCallback(async () => {
    const code = params.get("code");
    const state = params.get("state");
    const provider =
      params.get("provider") ||
      (typeof window !== "undefined" ? sessionStorage.getItem("qs_oidc_provider") : null);
    const providerError = params.get("error");

    if (providerError) {
      // The user declined, or the provider refused. Not our error to explain away.
      setError(params.get("error_description") || t("auth.callbackProviderCancelled"));
      return;
    }
    if (!code || !state || !provider) {
      setError(t("auth.callbackIncomplete"));
      return;
    }

    try {
      const res = await fetch(
        `${apiBase}/api/v1/auth/oidc/${encodeURIComponent(provider)}/callback`,
        {
          method: "POST",
          // Required for the browser to keep the session cookies this returns.
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, state }),
        },
      );
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error(data?.detail || t("auth.callbackFailed"));
      }

      sessionStorage.removeItem("qs_oidc_provider");
      setStatus("auth.callbackDone");
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [apiBase, params, router, t]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) await complete();
    })();
    return () => {
      cancelled = true;
    };
  }, [complete]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 p-6">
      <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white p-8 text-center">
        {error ? (
          <>
            <h1 className="mb-2 text-lg font-bold text-slate-900">{t("auth.callbackTitle")}</h1>
            <p className="mb-5 text-sm leading-relaxed text-slate-600">{error}</p>
            <Link
              href="/"
              className="inline-block rounded-2xl bg-[#0d5c3a] px-5 py-2.5 text-sm font-bold text-white"
            >
              {t("auth.callbackRetry")}
            </Link>
          </>
        ) : (
          <p className="text-sm text-slate-600">{t(status)}</p>
        )}
      </div>
    </main>
  );
}

export default function OidcCallbackPage() {
  const t = useT();

  // useSearchParams needs a Suspense boundary to keep the route static.
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-slate-100">
          <p className="text-sm text-slate-500">{t("auth.callbackWorking")}</p>
        </main>
      }
    >
      <CallbackInner />
    </Suspense>
  );
}
