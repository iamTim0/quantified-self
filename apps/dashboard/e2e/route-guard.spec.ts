import { expect, test } from "@playwright/test";

import {
  expectSignedIn,
  expectSignedOut,
  newAccount,
  signIn,
  signUp,
  submitSignIn,
} from "./helpers";

/**
 * The server-side route guard in `src/proxy.ts`.
 *
 * Asserted through a browser because the thing being fixed is a browser
 * behaviour: a signed-out deep link used to render the shell, wait for
 * `/api/v1/auth/me`, and then show a login form while the address bar still read
 * `/profile`. Nothing server-side could have caught that.
 *
 * These do not assert that the guard protects data — it does not, and is not
 * meant to. `auth.spec.ts` covers that: every API call is authorized by Core.
 */

test.describe("route guard", () => {
  test("a signed-out deep link is redirected before the page renders", async ({
    page,
  }) => {
    await page.goto("/profile");

    // Redirected to the sign-in screen, with the destination preserved. The
    // check is on the URL as well as the form: the old behaviour also ended at a
    // login form, but left the browser sitting on /profile.
    await expect(page).toHaveURL(/\/\?next=%2Fprofile$/);
    await expectSignedOut(page);
  });

  test("signing in from there continues to the requested page", async ({
    page,
    request,
  }) => {
    const account = newAccount();
    await signUp(request, account);

    await page.goto("/explorer");
    await expect(page).toHaveURL(/\/\?next=%2Fexplorer$/);

    await submitSignIn(page, account);
    await expectSignedIn(page);
    await expect(page).toHaveURL(/\/explorer$/);
  });

  test("a signed-in deep link is not redirected", async ({ page, request }) => {
    const account = newAccount();
    await signUp(request, account);
    await signIn(page, account);

    await page.goto("/quality");
    await expect(page).toHaveURL(/\/quality$/);
    await expectSignedIn(page);
  });

  test("public pages stay reachable while signed out", async ({ page }) => {
    // The guard defaults to protecting everything, so the exemptions are the
    // part that can silently break. Locking a user out of the privacy policy or
    // the OIDC callback would be a worse bug than the one being fixed.
    await page.goto("/legal/impressum");
    await expect(page).toHaveURL(/\/legal\/impressum$/);

    await page.goto("/auth/callback");
    await expect(page).toHaveURL(/\/auth\/callback$/);
    // Reached the page rather than merely failing to navigate away from it.
    await expect(
      page.getByText("Die Rückmeldung des Anbieters war unvollständig."),
    ).toBeVisible();
  });

  test("a protocol-relative `next` cannot redirect off this origin", async ({
    page,
    request,
    baseURL,
  }) => {
    const account = newAccount();
    await signUp(request, account);

    // Browsers read `//host` as protocol-relative, so a plain "starts with /"
    // check on the return path is the usual way an open redirect gets in. The
    // parameter is attacker-supplied by construction: it arrives in a link.
    const origin = new URL(baseURL!).origin;
    await page.goto("/?next=%2F%2Fexample.com%2Fphish");
    await submitSignIn(page, account);
    await expectSignedIn(page);

    expect(new URL(page.url()).origin).toBe(origin);
    expect(page.url()).not.toContain("example.com");
  });
});
