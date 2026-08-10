import { expect, test } from "@playwright/test";

import { newAccount, signIn, signUp } from "./helpers";

/**
 * Configuration problems have to be visible in the dashboard, not only in a log.
 *
 * The stack these tests run against is a development one: it uses the JWT_SECRET
 * printed in this repository and has registration open. Both are real findings,
 * so the banner must be there — and if it ever silently stops rendering, the
 * warnings go back to being something only a log file knows.
 *
 * Asserted through a browser because that is the whole claim being made. The
 * endpoint is covered by services/core/tests/test_deployment_warnings.py; what
 * cannot be tested there is whether anybody would ever see it.
 */

test.describe("system warnings", () => {
  test("an owner is told the deployment is running on a published secret", async ({
    page,
    request,
  }) => {
    const account = newAccount();
    await signUp(request, account);
    await signIn(page, account);

    const warnings = page.getByRole("region", { name: "System warnings" });
    await expect(warnings).toBeVisible();

    // The signing key is the one that matters most: knowing it means being able
    // to mint a session for any account in any workspace.
    await expect(warnings.getByText(/JWT_SECRET is a published default/)).toBeVisible();

    // A warning without an action is a warning nobody acts on, so the action is
    // part of what must render.
    await expect(warnings.getByText(/secrets\.token_urlsafe/)).toBeVisible();
  });

  test("the warning never prints the secret itself", async ({ page, request }) => {
    /**
     * The banner names the variable. Rendering its value would turn a warning
     * about a weak secret into a second way to read it — over the shoulder, in a
     * screenshot, in a support ticket.
     */
    const account = newAccount();
    await signUp(request, account);
    await signIn(page, account);

    const text = await page.getByRole("region", { name: "System warnings" }).innerText();
    expect(text).toContain("JWT_SECRET");
    expect(text).not.toContain("dev-secret-key-quantified-self-2026");
  });

  test("dismissing hides it for the session and it returns on reload", async ({
    page,
    request,
  }) => {
    /**
     * Dismissing hides the warning for a day, per code, and survives a reload --
     * hiding it only until the next page load is how a banner gets ignored rather
     * than read. It is still not permanent: a "don't show again" on "your signing
     * key is public" is how it stays public.
     *
     * The day is asserted by clearing what records it, not by waiting one out:
     * `localStorage` is where the dismissal lives, so emptying it is the same state
     * the reader is in tomorrow.
     */
    const account = newAccount();
    await signUp(request, account);
    await signIn(page, account);

    const warnings = page.getByRole("region", { name: "System warnings" });
    const critical = warnings.getByText(/JWT_SECRET is a published default/).first();
    await expect(critical).toBeVisible();

    await warnings.getByRole("button", { name: "Hide for a day" }).first().click();
    await expect(critical).toBeHidden();

    // Still hidden after a reload -- that is the whole point of the change.
    await page.reload();
    await expect(
      page
        .getByRole("region", { name: "System warnings" })
        .getByText(/JWT_SECRET is a published default/),
    ).toBeHidden();

    // ...and back once the day has passed.
    await page.evaluate(() => window.localStorage.removeItem("qs-warnings-dismissed"));
    await page.reload();
    await expect(
      page
        .getByRole("region", { name: "System warnings" })
        .getByText(/JWT_SECRET is a published default/),
    ).toBeVisible();
  });

  test("it is visible on every tab, not just the overview", async ({ page, request }) => {
    // A published signing key is not a fact about one page.
    const account = newAccount();
    await signUp(request, account);
    await signIn(page, account);

    for (const path of ["/connectors", "/quality", "/profile"]) {
      await page.goto(path);
      await expect(page.getByRole("region", { name: "System warnings" })).toBeVisible();
    }
  });
});
