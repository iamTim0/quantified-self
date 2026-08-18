"use client";

import { useCallback, useState } from "react";
import { BookOpen, LogOut, MoreHorizontal, RefreshCw, X } from "lucide-react";
import { useT } from "../lib/i18n/provider";
import { useDialog } from "../lib/useDialog";
import { NAV, PRIMARY_TABS, SECONDARY_TABS, type TabType } from "./navigation";

/**
 * Phone navigation: the four destinations a day actually uses, and a sheet.
 *
 * The sidebar has seven targets. A tab bar with seven targets gives each one a
 * touch area narrower than a fingertip, so the four that are opened daily get
 * the bar — the day, the data, the analysis, the chat — and the three that are
 * opened when something needs configuring live behind "More". That is a claim
 * about frequency, not importance: a connector is set up once and read from
 * every day.
 *
 * The sidebar is untouched and simply hidden below `md`. Two navigations for one
 * app is a maintenance cost, but a sidebar squeezed onto a phone is a column of
 * icons the thumb cannot reach, and the alternative — a hamburger — puts two
 * taps in front of every single navigation.
 */

export default function MobileTabBar({
  activeTab,
  onTabChange,
  onLogout,
  onRefresh,
}: {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  onLogout: () => void;
  /**
   * Re-fetch every page's data.
   *
   * It left the header, where it was a permanent control for something that
   * already happens on `visibilitychange`. It survives *here* because a phone in
   * standalone mode has no browser reload button in view, and this sheet is
   * where the rarely-needed things belong.
   */
  onRefresh: () => void;
}) {
  const t = useT();
  const [sheetOpen, setSheetOpen] = useState(false);
  const inSheet = SECONDARY_TABS.some((tab) => tab === activeTab);

  const closeSheet = useCallback(() => setSheetOpen(false), []);

  // Escape, the focus trap, and focus handed back to the "More" button on close
  // — the last of which this component was doing by hand, because closing via
  // the X unmounts the focused element and focus falls to <body>, restarting the
  // next Tab at the top of the document. `useDialog` remembers the opener
  // itself, so the ref this component kept for that purpose is gone.
  const sheetRef = useDialog<HTMLDivElement>(sheetOpen, closeSheet);

  const go = (tab: TabType) => {
    setSheetOpen(false);
    onTabChange(tab);
  };

  return (
    <>
      {sheetOpen && (
        <div
          className="fixed inset-0 z-40 bg-scrim md:hidden"
          // A backdrop that dismisses is what a phone user expects; without it
          // the only way out is the close button, which is the far corner.
          onClick={closeSheet}
          aria-hidden="true"
        />
      )}

      {sheetOpen && (
        <div
          ref={sheetRef}
          role="dialog"
          // `aria-modal` now says something true. It tells assistive technology
          // to prune everything outside this subtree, which was a lie while Tab
          // walked straight out of the back of the sheet into content a screen
          // reader had just been told did not exist. `useDialog` traps focus, so
          // the claim and the behaviour finally agree.
          aria-modal="true"
          aria-label={t("nav.more")}
          tabIndex={-1}
          // The bottom inset keeps the last row clear of the home indicator; the
          // side insets keep it clear of the cutout in landscape, where `inset-x-0`
          // otherwise runs the sheet under the camera housing on one edge.
          className="fixed inset-x-0 bottom-0 z-50 rounded-t-3xl border-t border-line bg-surface p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] shadow-2xl md:hidden"
        >
          <div className="mb-3 flex items-center justify-between">
            <span className="text-sm font-bold text-ink">{t("nav.more")}</span>
            <button
              type="button"
              onClick={closeSheet}
              aria-label={t("common.close")}
              className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-ink-muted hover:bg-surface-muted"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
          <ul className="space-y-1">
            {SECONDARY_TABS.map((tab) => {
              const entry = NAV[tab];
              const Icon = entry.icon;
              return (
                <li key={tab}>
                  <button
                    type="button"
                    onClick={() => go(tab)}
                    aria-current={activeTab === tab ? "page" : undefined}
                    className={`flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-medium ${
                      activeTab === tab
                        ? "bg-ok-soft text-ok-ink"
                        : "text-ink-secondary hover:bg-page"
                    }`}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    {t(entry.labelKey)}
                  </button>
                </li>
              );
            })}
            {/* The two controls that left the header. Neither is a destination,
                so neither belongs in the registry — but both are exactly the
                "needed occasionally" tier this sheet exists for. */}
            <li>
              <button
                type="button"
                onClick={() => {
                  setSheetOpen(false);
                  onRefresh();
                }}
                className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-medium text-ink-secondary hover:bg-page"
              >
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                {t("header.refresh")}
              </button>
            </li>
            <li>
              <a
                href="/docs/"
                target="_blank"
                rel="noreferrer"
                onClick={closeSheet}
                className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-medium text-ink-secondary hover:bg-page"
              >
                <BookOpen className="h-4 w-4" aria-hidden="true" />
                {t("header.docs")}
              </a>
            </li>
            <li>
              <button
                type="button"
                onClick={() => {
                  setSheetOpen(false);
                  onLogout();
                }}
                className="text-danger hover:bg-danger/10 flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-medium"
              >
                <LogOut className="h-4 w-4" aria-hidden="true" />
                {t("sidebar.logout")}
              </button>
            </li>
          </ul>
        </div>
      )}

      <nav
        aria-label={t("nav.primary")}
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] backdrop-blur md:hidden"
      >
        {PRIMARY_TABS.map((tab) => {
          const entry = NAV[tab];
          const Icon = entry.icon;
          const isActive = activeTab === tab;
          return (
            <button
              key={tab}
              type="button"
              onClick={() => go(tab)}
              aria-current={isActive ? "page" : undefined}
              // `min-h-14`: a touch target below about 44px is one a thumb misses.
              // `min-w-0` is what makes `truncate` real — without it the span's
              // cross size is fit-content, so the ellipsis can never fire and a
              // longer label silently widens the bar instead.
              className={`relative flex min-h-14 min-w-0 flex-1 touch-manipulation flex-col items-center justify-center gap-0.5 px-1 py-2 text-nav font-medium ${
                isActive ? "font-bold text-ok-ink" : "text-ink-muted"
              }`}
            >
              {/* Not colour alone (WCAG 1.4.1). The active tab differed from the
                  others only in hue — same icon, same size, same weight — which
                  is no difference at all to a reader with a red-green deficiency.
                  `aria-current` above was already correct; this is the same fact
                  made visible. The sidebar has carried a dot for this all along. */}
              {isActive && (
                <span
                  aria-hidden="true"
                  className="absolute inset-x-3 top-0 h-0.5 rounded-full bg-brand"
                />
              )}
              <Icon className="h-5 w-5" aria-hidden="true" />
              <span className="max-w-full truncate">{t(entry.labelKey)}</span>
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => setSheetOpen((open) => !open)}
          aria-expanded={sheetOpen}
          aria-label={t("nav.more")}
          className={`relative flex min-h-14 min-w-0 flex-1 touch-manipulation flex-col items-center justify-center gap-0.5 px-1 py-2 text-nav font-medium ${
            inSheet || sheetOpen ? "font-bold text-ok-ink" : "text-ink-muted"
          }`}
        >
          {(inSheet || sheetOpen) && (
            <span
              aria-hidden="true"
              className="absolute inset-x-3 top-0 h-0.5 rounded-full bg-brand"
            />
          )}
          <MoreHorizontal className="h-5 w-5" aria-hidden="true" />
          <span className="max-w-full truncate">{t("nav.more")}</span>
        </button>
      </nav>
    </>
  );
}
