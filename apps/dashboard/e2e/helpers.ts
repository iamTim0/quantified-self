import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** Shared fixtures for the browser suites. */

export const API_BASE = process.env.E2E_API_BASE ?? "http://127.0.0.1:8000";

export interface Account {
  email: string;
  password: string;
  name: string;
}

/** A fresh account per run, so tests never depend on pre-existing state (rule 10). */
export function newAccount(): Account {
  const id = Math.random().toString(36).slice(2, 10);
  return {
    email: `e2e-${id}@example.test`,
    password: "correct horse battery staple",
    name: `E2E ${id}`,
  };
}

/**
 * Create the account out of band.
 *
 * Takes the `request` fixture rather than `page.request` on purpose: page.request
 * shares the browser context's cookie jar, so signing up through it left the
 * browser already authenticated and the login form never rendered. Every test
 * then failed looking for an email field that was correctly absent — a test bug
 * that looks exactly like an application bug.
 */
export async function signUp(request: APIRequestContext, account: Account) {
  const response = await request.post(`${API_BASE}/api/v1/auth/signup`, {
    data: account,
  });
  expect(
    response.ok(),
    `signup failed: ${response.status()} ${await response.text()}`,
  ).toBeTruthy();
}

/** Fill in and submit the sign-in form on whatever page is currently open. */
export async function submitSignIn(page: Page, account: Account) {
  // By label, not by CSS type or placeholder: the labels are properly associated
  // with their inputs, so this asserts the accessible form as well as the flow.
  await page.getByLabel("E-Mail").fill(account.email);
  await page.getByLabel("Passwort").fill(account.password);
  await page.getByRole("button", { name: /^anmelden$/i }).click();
}

export async function signIn(page: Page, account: Account) {
  await page.goto("/");
  await submitSignIn(page, account);
  await expectSignedIn(page);
}

export async function expectSignedIn(page: Page) {
  // The sidebar only renders for an authenticated session.
  await expect(page.getByRole("button", { name: "Abmelden" })).toBeVisible();
}

export async function expectSignedOut(page: Page) {
  await expect(page.getByLabel("Passwort")).toBeVisible();
}
