import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests for the authentication flow.
 *
 * These run against a **real stack** — Postgres, Core and the Gateway — not
 * against mocks. The bug that started all of this ("log out, refresh, and you
 * are logged back in") lived precisely in the interaction between the browser,
 * the cookies the server sets, and what the page does on load. A test with a
 * mocked API would have passed throughout.
 *
 * The Gateway is the origin under test, not the Next server: it proxies the
 * dashboard *and* the API, so the browser sees one origin, which is what makes
 * the session cookies behave the way they do in production.
 *
 * Start the backing services before running:
 *   docker compose -f infra/docker-compose.yml up -d postgres nats
 *   uv run --directory services/core uvicorn core.main:app --port 8001
 *   uv run --directory services/api-gateway uvicorn gateway.main:app --port 8000
 *   npm --prefix apps/dashboard run dev
 *   npx playwright test
 */

// The Gateway, not the Next server. It proxies both the UI and the API, so the
// browser sees a single origin — which is what makes the session cookies behave
// as they do in production. Pointing at :3000 would exercise a cross-origin
// arrangement that no deployment uses.
const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./e2e",
  // Serial: these tests sign the same browser in and out, and a parallel worker
  // sharing that state would produce failures that look like auth bugs.
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // The interface is bilingual and picks its language from `Accept-Language`
    // when no `qs-locale` cookie has been set, so this line decides which
    // catalogue the locators below have to match. Pinned rather than inherited:
    // a suite whose language depends on the machine it runs on fails as a text
    // assertion when the real cause is the locale.
    locale: "en-GB",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  // No webServer block. Playwright can start one process; this needs four
  // (Postgres, Core, the Gateway and Next), and the Gateway has to come up after
  // Next or its first proxy attempt fails. The CI job and the docstring above
  // start them, which keeps one description of how to run this rather than two
  // that drift.
});
