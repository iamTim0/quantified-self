import type { Metadata, Viewport } from "next";
import { Outfit, JetBrains_Mono } from "next/font/google";
import "./globals.css";

import { LocaleProvider } from "./lib/i18n/provider";
import { requestLocale } from "./lib/i18n/request";
import { translate } from "./lib/i18n/translate";
import { ThemeProvider } from "./lib/theme/provider";
import { THEME_INIT_SCRIPT } from "./lib/theme/theme";

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
 * `colorScheme` is the second half, and it is what stops native `<select>`
 * dropdowns rendering dark-on-dark. The actual value follows the persisted
 * dashboard preference in `globals.css`; this metadata is the safe server-side
 * default before the browser's theme bootstrap runs.
 */
export const viewport: Viewport = {
  themeColor: "#f8fafc",
  colorScheme: "light dark",
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
      data-theme="light"
      data-theme-preference="system"
      suppressHydrationWarning
    >
      <head>
        <script id="theme-init" dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col font-sans">
        <LocaleProvider initialLocale={locale}>
          <ThemeProvider>{children}</ThemeProvider>
        </LocaleProvider>
      </body>
    </html>
  );
}
