import type { Metadata, Viewport } from "next";
import { Outfit, JetBrains_Mono } from "next/font/google";
import "./globals.css";

import ServiceWorkerRegistration from "./components/ServiceWorkerRegistration";
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
 * The colour a phone paints its own chrome, the palette native widgets use, and
 * whether the page is allowed to reach the edges of the screen at all.
 *
 * `viewportFit: "cover"` is the one that was missing, and its absence was silent.
 * `env(safe-area-inset-*)` resolves to **zero** unless the viewport opts into the
 * display cutout, so every safe-area allowance already written here — the tab
 * bar's, the scroll container's, the upload banner's — evaluated to `calc(1rem +
 * 0px)` and did nothing. The code read as if the insets were handled, which is why
 * it survived: nothing about a rule that computes to zero looks broken.
 *
 * `theme-color` is per scheme rather than a single light value. One hardcoded
 * `#f8fafc` put a near-white status bar above a dark shell, which is the seam a
 * reader sees before anything else on a phone. The two colours are the light and
 * dark `--background` from `globals.css`; they are literals because a `<meta>` tag
 * cannot read a CSS variable, and they are the one place in the app that has to be
 * kept in step with it by hand.
 *
 * `colorScheme` is what stops native `<select>` dropdowns rendering dark-on-dark.
 * The resolved value follows the persisted dashboard preference; this metadata is
 * the safe server-side default before the browser's theme bootstrap runs.
 */
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
    { media: "(prefers-color-scheme: dark)", color: "#0b1220" },
  ],
  colorScheme: "light dark",
  viewportFit: "cover",
};

export async function generateMetadata(): Promise<Metadata> {
  const locale = await requestLocale();
  return {
    title: "Quantified Self Platform",
    description: translate(locale, "auth.tagline"),
    // Apple ignores the web app manifest and reads these instead, which is why
    // the icon is declared twice rather than once.
    appleWebApp: {
      capable: true,
      title: "Quantified",
      statusBarStyle: "default",
    },
    icons: {
      icon: [
        { url: "/icons/icon.svg", type: "image/svg+xml" },
        { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      ],
      apple: "/icons/apple-touch-icon.png",
    },
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
        <ServiceWorkerRegistration />
      </body>
    </html>
  );
}
