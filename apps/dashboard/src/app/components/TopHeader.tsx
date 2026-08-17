"use client";

import React from "react";
import { Plus, RefreshCw } from "lucide-react";

import { useT } from "../lib/i18n/provider";
import NotificationBell from "./NotificationBell";
import { NAV, type TabType } from "./navigation";

interface TopHeaderProps {
  apiBase: string;
  userName: string;
  userEmail: string;
  activeTab: TabType;
  onOpenConfigureModal: () => void;
  onNavigateToProfile: () => void;
  onRefresh: () => void;
}

/**
 * The persistent header: where you are, what needs attention, and one action.
 *
 * This used to hold seven controls in a wrapping row — docs, notifications,
 * refresh, add connector, language, theme, profile — and no page title at all.
 * On a phone five of them survived the breakpoints and wrapped onto two lines
 * *before* the content of every page. It was all controls and no orientation.
 *
 * The cut is by how often each is actually needed, which the navigation registry
 * already states for destinations and which applies just as well here:
 *
 * - **Notifications stay.** It is the only surface where a failed nightly report
 *   becomes visible at all, so it is the one control that has to be reachable at
 *   any moment — which it was not, because this header used to render *inside*
 *   `<main>` and scrolled away with the page.
 * - **Add connector stays on desktop.** It is rare after setup, but it is the
 *   one "get data in" affordance; on a phone it goes, and `/connectors` carries
 *   its own primary button.
 * - **Refresh is gone.** Returning to the tab already re-fetches everything
 *   (`visibilitychange` in the dashboard layout), each report has its own
 *   recompute in `ReportStatus`, and the browser has a reload button. On a phone
 *   it survives in the "More" sheet, where there is no such button in view.
 * - **Docs is gone from here.** The sidebar has the same link; two of them is a
 *   duplicate, not a convenience.
 * - **Language and theme move to Settings.** Both are set once and then never
 *   again, which is the definition of something that should not occupy the row
 *   above every screen.
 * - **The profile pill loses its email line.** It was `text-[10px]` in
 *   `text-ink-muted` — 2.56:1 at ten pixels — and Settings shows the address
 *   properly one tap away.
 */
export default function TopHeader({
  apiBase,
  userName,
  activeTab,
  onOpenConfigureModal,
  onNavigateToProfile,
  onRefresh,
}: TopHeaderProps) {
  const t = useT();

  const getInitials = (name: string) => {
    if (!name) return "QS";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  };

  return (
    // Sticky, and the top safe-area inset lives here now: this is what sits
    // against the status bar and the notch, so it is what has to clear them.
    <header className="sticky top-0 z-30 border-b border-line bg-surface/90 pt-[env(safe-area-inset-top)] backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-[1400px] items-center gap-3 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] sm:px-6 lg:px-8">
        {/* The orientation this header never had. `h1` because it names the
            page; the pages themselves carry `h2` downwards. */}
        <h1 className="min-w-0 flex-1 truncate text-title font-bold text-ink">
          {t(NAV[activeTab].labelKey)}
        </h1>

        {/* Only in an installed app, where the browser's reload button is gone.
            In a tab this would be a permanent control for something the browser
            already does and that `visibilitychange` handles on returning to the
            page — which is why it left this header in the first place. */}
        <button
          onClick={onRefresh}
          aria-label={t("header.refresh")}
          title={t("header.refreshTitle")}
          className="hidden min-h-11 min-w-11 items-center justify-center rounded-2xl border border-line bg-surface text-ink-muted shadow-sm hover:bg-page hover:text-ink standalone:flex"
        >
          <RefreshCw className="h-4 w-4" />
        </button>

        <NotificationBell apiBase={apiBase} />

        <button
          onClick={onOpenConfigureModal}
          aria-label={t("header.addConnector")}
          className="hidden h-11 items-center gap-2 rounded-2xl bg-brand px-4 text-meta font-bold text-brand-ink shadow-md shadow-brand/20 [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] hover:bg-brand-hover md:flex"
        >
          <Plus className="h-3.5 w-3.5" />
          <span>{t("header.addConnector")}</span>
        </button>

        <button
          onClick={onNavigateToProfile}
          aria-label={t("sidebar.settings")}
          className="group flex h-11 min-w-11 items-center gap-3 rounded-2xl border border-line bg-surface px-2 shadow-sm [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] hover:border-line"
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-linear-to-br from-emerald-600 to-teal-700 text-meta font-bold text-white shadow-inner">
            {getInitials(userName)}
          </span>
          <span className="hidden max-w-40 truncate pr-1 text-meta font-bold text-ink group-hover:text-brand lg:block">
            {userName}
          </span>
        </button>
      </div>
    </header>
  );
}
