"use client";

/**
 * Client-side session handling.
 *
 * Two bugs shaped this file. The first: the dashboard used to fetch
 * `/api/v1/auth/dev-token` whenever localStorage happened to be empty, so
 * logging out and refreshing signed you straight back in as owner of a hardcoded
 * tenant. That endpoint is gone and nothing here invents a session.
 *
 * The second: the tokens themselves lived in `localStorage`, readable by any
 * script on the page. They are now httpOnly cookies set by Core, which
 * JavaScript cannot read at all — so this module holds no credential and has
 * nothing to clear. "Am I signed in?" is answered by asking the server, not by
 * inspecting local state, and signing out is a server-side revocation whose
 * response expires the cookies.
 *
 * What remains readable is `qs_csrf`, deliberately: it is not a credential, only
 * proof that the code composing a request could read this origin's cookies. See
 * services/core/src/core/security/cookies.py for the reasoning.
 */

export const CSRF_COOKIE = "qs_csrf";
export const CSRF_HEADER = "X-CSRF-Token";

export interface SessionUser {
  userId: string;
  tenantId: string;
  email: string;
  name: string;
  role: string;
}

/** Read a non-httpOnly cookie. Returns null when absent. */
export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  for (const part of document.cookie.split("; ")) {
    if (part.startsWith(prefix)) {
      return decodeURIComponent(part.slice(prefix.length));
    }
  }
  return null;
}

interface MeResponse {
  user_id: string;
  tenant_id: string;
  email: string;
  name: string;
  role: string;
}

function toSessionUser(data: MeResponse): SessionUser {
  return {
    userId: data.user_id,
    tenantId: data.tenant_id,
    email: data.email,
    name: data.name ?? "",
    role: data.role ?? "member",
  };
}

/**
 * Ask the server who we are.
 *
 * This is the only source of truth for "is there a session". `apiFetch` handles
 * the expired-access-token case by refreshing once, so a null here means signed
 * out rather than merely stale.
 */
export async function fetchSession(apiBase: string): Promise<SessionUser | null> {
  const { apiJson } = await import("./api");
  const data = await apiJson<MeResponse>(`${apiBase}/api/v1/auth/me`);
  return data ? toSessionUser(data) : null;
}

/**
 * End the session on the server.
 *
 * Core clears the cookies in its response and denylists the access token's `jti`,
 * so this is what actually signs the user out — there is no local credential
 * left over to forget. The call is best-effort: a user who clicks "log out" must
 * end up signed out of this browser even if the network is down, and the caller
 * resets its own UI state regardless.
 */
export async function endSession(apiBase: string): Promise<string | null> {
  const csrf = readCookie(CSRF_COOKIE);
  try {
    const res = await fetch(`${apiBase}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(csrf ? { [CSRF_HEADER]: csrf } : {}),
      },
      body: JSON.stringify({ all_sessions: false }),
      // Deliberately not keepalive: the response is now worth reading. A user
      // who signed in through an identity provider still has a live session
      // *there*, and Core returns the provider's RP-initiated logout URL so the
      // browser can finish the job.
    });

    // 204 means there is no provider session to end — the common case.
    if (res.status === 200) {
      const body = await res.json().catch(() => null);
      const url: unknown = body?.end_session_url;
      return typeof url === "string" && url ? url : null;
    }
  } catch {
    // Ignored on purpose — see docstring.
  }
  return null;
}
