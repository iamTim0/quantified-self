"use client";

/**
 * The single way this app talks to the API.
 *
 * Every call sends the session cookies, attaches the CSRF token that pairs with
 * them, and recovers from one expired access token without bouncing the user to
 * the login screen. Components no longer receive or handle a token at all —
 * there is nothing for them to hold, because the credential is an httpOnly
 * cookie the page cannot read.
 */

import { CSRF_COOKIE, CSRF_HEADER, readCookie } from "./session";

/** Methods that change nothing and therefore need no CSRF proof. */
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/**
 * De-duplicates concurrent refreshes.
 *
 * A dashboard fires several requests at once, so an expired access token
 * produces a burst of 401s. Without this, each one would start its own refresh;
 * because refresh-token rotation is single-use, the second would present a token
 * the first had already spent, and Core treats that as replay and revokes the
 * whole session. Sharing one in-flight promise is what stops a routine token
 * expiry from logging the user out.
 */
let inFlightRefresh: Promise<boolean> | null = null;

function originOf(url: string): string {
  try {
    return new URL(url, window.location.href).origin;
  } catch {
    return window.location.origin;
  }
}

async function refreshOnce(apiOrigin: string): Promise<boolean> {
  if (!inFlightRefresh) {
    inFlightRefresh = (async () => {
      try {
        const res = await fetch(`${apiOrigin}/api/v1/auth/refresh`, {
          method: "POST",
          credentials: "include",
          headers: csrfHeaders(),
        });
        return res.ok;
      } catch {
        // A network blip is not proof the session is dead.
        return false;
      } finally {
        // Release on the next tick so callers awaiting this promise all observe
        // the same result before a new attempt can begin.
        setTimeout(() => {
          inFlightRefresh = null;
        }, 0);
      }
    })();
  }
  return inFlightRefresh;
}

function csrfHeaders(): Record<string, string> {
  const token = readCookie(CSRF_COOKIE);
  return token ? { [CSRF_HEADER]: token } : {};
}

/**
 * `fetch` with session cookies, CSRF, and a single transparent token refresh.
 *
 * Returns the response as-is; a 401 that survives the refresh is the caller's to
 * handle (normally by signing out).
 */
export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();

  const build = (): RequestInit => ({
    ...init,
    method,
    credentials: "include",
    headers: {
      ...(init.headers as Record<string, string> | undefined),
      ...(SAFE_METHODS.has(method) ? {} : csrfHeaders()),
    },
  });

  const response = await fetch(url, build());
  if (response.status !== 401) return response;

  const refreshed = await refreshOnce(originOf(url));
  if (!refreshed) return response;

  // Rebuild rather than reuse: the refresh rotated the CSRF cookie, so the
  // retry must carry the new value.
  return fetch(url, build());
}

interface UploadRequestOptions {
  headers?: Record<string, string>;
  onProgress?: (percentage: number) => void;
}

/**
 * Upload a file while reporting bytes sent.
 *
 * `fetch` deliberately has no upload-progress event in browsers. XHR is used
 * only for this binary upload path; it keeps the same cookies, CSRF proof and
 * one-shot access-token refresh as `apiFetch`.
 */
export async function apiUpload(
  url: string,
  file: Blob,
  options: UploadRequestOptions = {},
): Promise<Response> {
  const request = (): Promise<Response> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", url, true);
      xhr.withCredentials = true;

      for (const [name, value] of Object.entries({
        ...(options.headers ?? {}),
        ...csrfHeaders(),
      })) {
        xhr.setRequestHeader(name, value);
      }

      xhr.upload.addEventListener("progress", (event) => {
        if (!event.lengthComputable || event.total <= 0) return;
        options.onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      });

      xhr.addEventListener("load", () => {
        const contentType = xhr.getResponseHeader("Content-Type");
        resolve(
          new Response(xhr.responseText, {
            status: xhr.status,
            statusText: xhr.statusText,
            headers: contentType ? { "Content-Type": contentType } : undefined,
          }),
        );
      });
      xhr.addEventListener("error", () => reject(new TypeError("Network request failed")));
      xhr.addEventListener("abort", () => reject(new DOMException("Upload aborted", "AbortError")));
      xhr.send(file);
    });

  let response = await request();
  if (response.status !== 401) return response;

  const refreshed = await refreshOnce(originOf(url));
  if (!refreshed) return response;

  // A retry starts a new request body, so make the reset visible to the user.
  options.onProgress?.(0);
  response = await request();
  return response;
}

/** `apiFetch` for JSON endpoints, returning null instead of throwing on failure. */
export async function apiJson<T>(url: string, init: RequestInit = {}): Promise<T | null> {
  const res = await apiFetch(url, init);
  if (!res.ok) return null;
  try {
    return (await res.json()) as T;
  } catch {
    return null;
  }
}
