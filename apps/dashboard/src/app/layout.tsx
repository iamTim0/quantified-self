import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import { Outfit, JetBrains_Mono } from "next/font/google";
import "./globals.css";

import { LOCALE_COOKIE, resolveLocale, type Locale } from "./lib/i18n/locale";
import { LocaleProvider } from "./lib/i18n/provider";
import { translate } from "./lib/i18n/translate";

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
});

/**
 * The language for this request: an explicit choice if one was made, otherwise
 * whatever the browser asked for.
 *
 * Reading a cookie makes the route render per request rather than being prerendered
 * once. That is the price of a first paint that is already in the right language,
 * and it is a price this app was always going to pay: every page needs the session,
 * and `src/proxy.ts` already runs on each request.
 */
async function requestLocale(): Promise<Locale> {
  const [cookieStore, headerList] = await Promise.all([cookies(), headers()]);
  return resolveLocale(cookieStore.get(LOCALE_COOKIE)?.value, headerList.get("accept-language"));
}

export async function generateMetadata(): Promise<Metadata> {
  const locale = await requestLocale();
  return {
    title: "Quantified Self Platform",
    description: translate(locale, "auth.tagline"),
  };
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await requestLocale();

  return (
    <html
      lang={locale}
      className={`${outfit.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-neutral-950 text-white font-sans">
        <LocaleProvider initialLocale={locale}>{children}</LocaleProvider>
      </body>
    </html>
  );
}
