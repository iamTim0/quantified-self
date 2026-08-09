import { cookies, headers } from "next/headers";

import { LOCALE_COOKIE, resolveLocale, type Locale } from "./locale";

/**
 * The language for this request: an explicit choice if one was made, otherwise
 * whatever the browser asked for.
 *
 * Reading a cookie makes the route render per request rather than being prerendered
 * once. That is the price of a first paint that is already in the right language,
 * and it is a price this app was always going to pay: every page needs the session,
 * and `src/proxy.ts` already runs on each request.
 *
 * Server-only — it reads `next/headers`. The client gets the same answer from
 * `useI18n()`, which is seeded with this value by the root layout.
 */
export async function requestLocale(): Promise<Locale> {
  const [cookieStore, headerList] = await Promise.all([cookies(), headers()]);
  return resolveLocale(cookieStore.get(LOCALE_COOKIE)?.value, headerList.get("accept-language"));
}
