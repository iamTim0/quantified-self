import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Server-side route guard (Next 16 renamed `middleware.ts` to `proxy.ts`).
 *
 * Deep-linking to `/profile` while signed out used to render the shell, wait for
 * `/api/v1/auth/me` to answer, and only then swap in the login screen — leaving
 * the browser sitting on a protected URL showing a sign-in form. This turns that
 * into a redirect that happens before any React runs.
 *
 * **This is not an authorization boundary and must never be treated as one.**
 * Next's own guidance says as much: a proxy is for optimistic checks, not for
 * session management. Every byte of tenant data is fetched from the Gateway,
 * which verifies the JWT and its `tenant_id` on each request; forging the cookie
 * this file reads gets you the same empty shell and a 401. The guard exists to
 * fix a URL and a flash, nothing more.
 *
 * What it checks is deliberately *not* the access token. `qs_access` expires
 * after 12 hours while the session lives for 30 days, so a returning user has a
 * usable session and no access cookie — `apiFetch` exchanges the refresh token
 * on the first 401. Redirecting on a missing `qs_access` would sign that user out
 * of a working session. `qs_refresh` is scoped to `/api/v1/auth` and is not sent
 * on a page navigation, so it cannot be consulted here either.
 *
 * `qs_csrf` is the right signal: it is set on `/`, lives as long as the refresh
 * token, and is not a credential — it says "a session was established and may
 * still be refreshable", which is exactly the question being asked.
 */

// Kept in step with services/core/src/core/security/cookies.py. Not imported:
// the dashboard and Core share no code by design (AGENTS.md rule 6).
const SESSION_MARKER_COOKIE = "qs_csrf";
const ACCESS_COOKIE = "qs_access";

/**
 * Paths that must stay reachable without a session.
 *
 * `/` is on the list because it is where the sign-in screen lives — the app is
 * one shell that renders `AuthScreen` or the dashboard depending on the session.
 * Redirecting it would loop.
 */
const PUBLIC_PREFIXES = ["/auth", "/legal"];

function isPublic(pathname: string): boolean {
  if (pathname === "/") return true;
  return PUBLIC_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

export function proxy(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;

  if (isPublic(pathname)) return NextResponse.next();

  const hasSession =
    request.cookies.has(SESSION_MARKER_COOKIE) ||
    request.cookies.has(ACCESS_COOKIE);
  if (hasSession) return NextResponse.next();

  // Remember where they were going so signing in does not dump them on the
  // overview. `encodeURIComponent` so a query string in the target cannot escape
  // the parameter it is stored in.
  const target = `${pathname}${search}`;

  // Built from `nextUrl` rather than written as the relative reference `/?next=…`,
  // which is legal HTTP and what this did first: Next parses the Location header
  // with `new URL()` and answers 500 on anything that is not absolute.
  //
  // `nextUrl` is the right base because the Gateway forwards the browser's own
  // `Host` header untouched, so this resolves to the origin the user actually
  // typed and not to the Next server behind the proxy. Cloning also keeps the
  // origin fixed to that host, so `next` cannot steer the redirect anywhere else.
  const destination = request.nextUrl.clone();
  destination.pathname = "/";
  destination.search = `?next=${encodeURIComponent(target)}`;

  return NextResponse.redirect(destination, 307);
}

export const config = {
  /**
   * Everything except Next's own assets, `/api`, and files with an extension.
   *
   * A negative matcher rather than a list of protected routes: a route added
   * later is then guarded by default, and making it public is a deliberate edit
   * to PUBLIC_PREFIXES above. The exclusions are the ones Next's documentation
   * calls for — without them the guard would redirect stylesheets and images.
   *
   * `api` is excluded because a guard that answers 307 to an API call is worse
   * than useless: the caller wants a status code, not a login page. Behind the
   * Gateway those paths never reach Next at all, so this only matters when the
   * dashboard is addressed directly — which is exactly how it is developed, and
   * where the first version of this file turned every `/api/v1/auth/me` into a
   * redirect.
   */
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico|.*\\.[^/]+$).*)"],
};
