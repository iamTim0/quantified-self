import type { Metadata, Viewport } from "next";
import { Outfit, JetBrains_Mono } from "next/font/google";
import "./globals.css";

import { LocaleProvider } from "./lib/i18n/provider";
import { requestLocale } from "./lib/i18n/request";
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
 * The colour a phone paints its own chrome, and the palette native widgets use.
 *
 * Neither was declared. `theme-color` matters more since the workspace became
 * usable on a phone: without it the status bar keeps the browser's default and
 * the app ends below a strip of unrelated colour. `#f8fafc` is the shell's own
 * surface — the colour actually at the top of the viewport once the outer
 * padding collapses at `p-0` on small screens.
 *
 * `colorScheme` is the second half, and it is what stops Windows dark mode
 * rendering the 16 native `<select>` dropdowns dark-on-dark: their list,
 * scrollbar and focus ring come from the OS, not from our CSS. The interface is
 * a light one — three `dark:` utilities in the entire codebase — so it says so
 * once here rather than leaving each control to guess. Also set in
 * `globals.css`, because a `<meta>` tag arrives after first paint.
 */
export const viewport: Viewport = {
  themeColor: "#f8fafc",
  colorScheme: "light",
};

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
