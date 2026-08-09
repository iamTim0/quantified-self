import { expect, test } from "@playwright/test";

import {
  API_BASE,
  expectSignedIn,
  expectSignedOut,
  newAccount,
  signIn,
  signUp,
} from "./helpers";

/**
 * The sequence the whole logout bug lived in: sign in, reload, sign out, reload.
 *
 * Every other test of this is server-side. They verify that Core revokes the
 * session and clears the cookies — which it does, and did not catch the original
 * defect, because the defect was that the *page* fetched a fresh token whenever
 * local storage was empty. The server was behaving correctly the entire time.
 *
 * So these drive a real browser against a real stack. What they assert is
 * deliberately behavioural — "after reloading I am still signed out" — rather
 * than structural, because the failure mode was a page that looked signed in.
 */

test.describe("session lifecycle in a browser", () => {
  test("sign in, reload, and the session survives", async ({ page, request }) => {
    const account = newAccount();
    await signUp(request, account);
    await signIn(page, account);

    await page.reload();
    await expectSignedIn(page);
  });

  test("sign out, then reload — and stay signed out", async ({ page, request }) => {
    const account = newAccount();
    await signUp(request, account);
    await signIn(page, account);

    await page.getByRole("button", { name: "Sign out" }).click();
    await expectSignedOut(page);

    // The reload is the entire point. The reported bug was that this step
    // silently signed the user back in.
    await page.reload();
    await expectSignedOut(page);
  });

  test("the session cookie is not readable from JavaScript", async ({ page, request }) => {
    const account = newAccount();
    await signUp(request, account);
    await signIn(page, account);

    const readable = await page.evaluate(() => document.cookie);
    expect(readable).not.toContain("qs_access");
    expect(readable).not.toContain("qs_refresh");
    // The CSRF cookie is deliberately readable — the page has to echo it back.
    expect(readable).toContain("qs_csrf");

    // And nothing put a credential in web storage on the way past.
    const stored = await page.evaluate(() =>
      JSON.stringify({
        local: Object.entries(localStorage),
        session: Object.entries(sessionStorage),
      }),
    );
    expect(stored).not.toContain("eyJ"); // a JWT always starts with this
    expect(stored).not.toContain("qs_token");
  });

  test("logging out in one tab signs the other out when it regains focus", async ({
    browser,
    request,
  }) => {
    const account = newAccount();
    const context = await browser.newContext();
    const first = await context.newPage();
    await signUp(request, account);
    await signIn(first, account);

    // Second tab in the same context, so it shares the cookie jar.
    const second = await context.newPage();
    await second.goto("/");
    await expectSignedIn(second);

    await first.getByRole("button", { name: "Sign out" }).click();
    await expectSignedOut(first);

    // The other tab re-checks with the server when it becomes visible rather
    // than trusting what it last rendered — cookie removal fires no event.
    await second.bringToFront();
    await second.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await expectSignedOut(second);

    await context.close();
  });

  test("a protected API call after logout is refused", async ({ page, request }) => {
    const account = newAccount();
    await signUp(request, account);
    await signIn(page, account);
    await page.getByRole("button", { name: "Sign out" }).click();
    await expectSignedOut(page);

    // Issued from inside the page, not via page.request. Playwright's API
    // request context will not send a Secure cookie over http, so a
    // page.request call is unauthenticated no matter what — it returns 401
    // whether or not logout actually worked, and the assertion proves nothing.
    // An in-page fetch carries the real cookie jar.
    const status = await page.evaluate(async (api) => {
      const r = await fetch(`${api}/api/v1/data/metrics/types`, {
        credentials: "include",
      });
      return r.status;
    }, API_BASE);
    expect(status).toBe(401);
  });

  test("while signed in, that same call succeeds", async ({ page, request }) => {
    // The counterpart to the test above. Without it, a 401 there could mean
    // "revoked" or "never authenticated in the first place", and only the second
    // reading would be a green test hiding a broken feature.
    const account = newAccount();
    await signUp(request, account);
    await signIn(page, account);

    const status = await page.evaluate(async (api) => {
      const r = await fetch(`${api}/api/v1/data/metrics/types`, {
        credentials: "include",
      });
      return r.status;
    }, API_BASE);
    expect(status).toBe(200);
  });

  test("a state-changing request without the CSRF header is refused", async ({
    page,
    request,
  }) => {
    const account = newAccount();
    await signUp(request, account);
    await signIn(page, account);

    // From inside the page so the cookies actually ride along, which is the
    // whole point: the browser attaches them, the attacker's script cannot read
    // qs_csrf to build the matching header, and the request must be refused.
    const status = await page.evaluate(async (api) => {
      const r = await fetch(`${api}/api/v1/data/sources/sync`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_type: "oura" }),
      });
      return r.status;
    }, API_BASE);
    expect(status).toBe(403);
  });
});
