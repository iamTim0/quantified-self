"use client";

/**
 * Client-side session handling.
 *
 * The previous implementation stored a token in localStorage, cleared it on
 * logout, and then — on the very next page load — fetched a fresh one from
 * `/api/v1/auth/dev-token` whenever local storage happened to be empty. Logging
 * out and refreshing therefore logged you straight back in as owner of a
 * hardcoded tenant. That endpoint no longer exists and nothing here invents a
 * session: if there is no valid stored token, the user is signed out, full stop.
 *
 * Tokens still live in localStorage rather than httpOnly cookies. That is a
 * deliberate, documented limitation of this pass — moving to cookies means
 * server-rendered route guards (a `proxy.ts`, since Next 16 renamed
 * `middleware`) and is tracked as follow-up work in AGENT_PROGRESS.md.
 */

export const STORAGE_KEYS = {
  token: "qs_token",
  refreshToken: "qs_refresh_token",
  tenantId: "qs_tenant_id",
  userName: "qs_user_name",
  userEmail: "qs_user_email",
  userRole: "qs_user_role",
} as const;

export interface StoredSession {
  token: string;
  refreshToken: string | null;
  tenantId: string;
  userName: string;
  userEmail: string;
  userRole: string;
}

interface JwtPayload {
  exp?: number;
  tenant_id?: string;
  user_id?: string;
  email?: string;
  role?: string;
}

/** Decode a JWT payload without verifying it. Only ever used for local hints. */
export function decodeJwtPayload(token: string): JwtPayload | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const base64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    return JSON.parse(atob(padded)) as JwtPayload;
  } catch {
    return null;
  }
}

/**
 * Whether a token is expired, treating anything unparseable as expired.
 *
 * `skewSeconds` makes the client give up slightly before the server would, so a
 * request is not fired with a token that dies in flight.
 */
export function isTokenExpired(token: string, skewSeconds = 30): boolean {
  const payload = decodeJwtPayload(token);
  if (!payload?.exp) return true;
  return payload.exp * 1000 <= Date.now() + skewSeconds * 1000;
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  Object.values(STORAGE_KEYS).forEach((key) => localStorage.removeItem(key));
}

export function saveSession(session: StoredSession): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEYS.token, session.token);
  if (session.refreshToken) {
    localStorage.setItem(STORAGE_KEYS.refreshToken, session.refreshToken);
  }
  localStorage.setItem(STORAGE_KEYS.tenantId, session.tenantId);
  localStorage.setItem(STORAGE_KEYS.userName, session.userName);
  localStorage.setItem(STORAGE_KEYS.userEmail, session.userEmail);
  localStorage.setItem(STORAGE_KEYS.userRole, session.userRole);
}

/**
 * Read a usable session from storage.
 *
 * Returns null — never a fabricated session — when nothing valid is stored. An
 * expired access token is reported through `expired` so the caller can decide
 * whether to attempt a refresh.
 */
export function readStoredSession(): { session: StoredSession | null; expired: boolean } {
  if (typeof window === "undefined") return { session: null, expired: false };

  const token = localStorage.getItem(STORAGE_KEYS.token);
  const refreshToken = localStorage.getItem(STORAGE_KEYS.refreshToken);

  if (!token) {
    return { session: null, expired: Boolean(refreshToken) };
  }

  if (isTokenExpired(token)) {
    return { session: null, expired: true };
  }

  const payload = decodeJwtPayload(token);
  const tenantId = payload?.tenant_id ?? localStorage.getItem(STORAGE_KEYS.tenantId);
  if (!tenantId) {
    // A token with no tenant is unusable; treat the stored state as corrupt.
    clearSession();
    return { session: null, expired: false };
  }

  return {
    session: {
      token,
      refreshToken,
      tenantId,
      userName: localStorage.getItem(STORAGE_KEYS.userName) ?? "",
      userEmail: payload?.email ?? localStorage.getItem(STORAGE_KEYS.userEmail) ?? "",
      userRole: payload?.role ?? localStorage.getItem(STORAGE_KEYS.userRole) ?? "member",
    },
    expired: false,
  };
}

/** Exchange the stored refresh token for a new session, or return null. */
export async function refreshSession(apiBase: string): Promise<StoredSession | null> {
  if (typeof window === "undefined") return null;
  const refreshToken = localStorage.getItem(STORAGE_KEYS.refreshToken);
  if (!refreshToken) return null;

  try {
    const res = await fetch(`${apiBase}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) {
      clearSession();
      return null;
    }
    const data = await res.json();
    const session: StoredSession = {
      token: data.access_token,
      refreshToken: data.refresh_token ?? null,
      tenantId: data.tenant_id,
      userName: data.name ?? "",
      userEmail: data.email ?? "",
      userRole: data.role ?? "member",
    };
    saveSession(session);
    return session;
  } catch {
    // A network failure is not proof the session is dead; keep it and let the
    // next protected call decide.
    return null;
  }
}

/**
 * End the session on the server and locally.
 *
 * Local state is cleared even if the network call fails — a user who clicks
 * "log out" must end up logged out of this browser regardless.
 */
export async function endSession(apiBase: string): Promise<void> {
  const token = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEYS.token) : null;
  const refreshToken =
    typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEYS.refreshToken) : null;

  try {
    await fetch(`${apiBase}/api/v1/auth/logout`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ refresh_token: refreshToken, all_sessions: false }),
      keepalive: true,
    });
  } catch {
    // Ignored on purpose — see docstring.
  } finally {
    clearSession();
  }
}
