"use client";

import React from "react";
import { LogOut, Activity, ArrowUpRight, BookOpen } from "lucide-react";

import { useT } from "../lib/i18n/provider";
import { useIsStandalone } from "../lib/pwa";

// Both desktop and phone navigation render the same registry, so a destination
// cannot be added to one surface and silently omitted from the other. The two
// blocks below are derived from it too — this file used to filter `profile` out
// by hand and re-add it further down, which is how the registry came to describe
// the phone exhaustively and the desktop only approximately.
import { NAV, SIDEBAR_GENERAL, SIDEBAR_MENU, type TabType } from "./navigation";

export type { TabType };

interface SidebarProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  onLogout: () => void;
}

export default function Sidebar({ activeTab, onTabChange, onLogout }: SidebarProps) {
  const t = useT();
  const isStandalone = useIsStandalone();
  const menuItems = SIDEBAR_MENU.map((id) => {
    const entry = NAV[id];
    return { id, label: t(entry.labelKey), icon: entry.icon };
  });

  return (
    // `sticky` + `h-dvh` rather than `min-h-screen`. The old rule demanded a full
    // viewport height *inside* a card that itself sat in `lg:p-6` padding, so the
    // frame was always taller than the window by at least that padding — every
    // desktop carried a permanent strip of dead scroll, and the sidebar scrolled
    // away with it. Now it stays put and scrolls only if its own content exceeds
    // the viewport.
    <aside className="sticky top-0 flex h-dvh w-64 shrink-0 flex-col justify-between overflow-y-auto border-r border-line bg-surface p-6">
      <div>
        {/* Logo Header */}
        <div className="flex items-center gap-3 mb-10 pl-2">
          <div className="w-10 h-10 rounded-2xl bg-brand flex items-center justify-center text-brand-ink shadow-md shadow-brand/20">
            <Activity className="w-5 h-5" />
          </div>
          <div>
            <span className="text-xl font-bold text-ink tracking-tight block leading-none">
              Quantified
            </span>
            <span className="text-[10px] font-semibold tracking-wider text-ok-ink uppercase">
              Self Platform
            </span>
          </div>
        </div>

        {/* MENU Section */}
        <div className="mb-8">
          <span className="text-[11px] font-bold text-ink-muted uppercase tracking-widest px-3 mb-3 block">
            {t("sidebar.menu")}
          </span>
          <nav className="space-y-1">
            {menuItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onTabChange(item.id)}
                  className={`w-full flex items-center justify-between px-3.5 py-3 rounded-2xl text-sm font-semibold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
                    isActive
                      ? "bg-brand text-brand-ink shadow-lg shadow-brand/20"
                      : "text-ink-muted hover:text-ink hover:bg-surface-muted"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <Icon className={`w-4 h-4 ${isActive ? "text-white" : "text-ink-muted"}`} />
                    <span>{item.label}</span>
                  </div>
                  {isActive && <span className="w-1.5 h-1.5 rounded-full bg-emerald-300" />}
                </button>
              );
            })}
          </nav>
        </div>

        {/* GENERAL Section */}
        <div>
          <span className="text-[11px] font-bold text-ink-muted uppercase tracking-widest px-3 mb-3 block">
            {t("sidebar.general")}
          </span>
          <nav className="space-y-1">
            {/* Relative on purpose: Traefik serves the docs container under /docs
                on this same host, so an absolute URL only ever named one
                particular deployment -- and put its owner's domain in the source. */}
            {/* `target="_blank"` in a browser tab, in-scope in an installed app.
                There are no tabs in standalone mode: the same attribute that is
                polite in a browser launches the *browser* from inside the app and
                strands the reader outside it. The docs are served under this same
                origin by Traefik, so staying in scope is possible at all. */}
            <a
              href="/docs/"
              target={isStandalone ? undefined : "_blank"}
              rel={isStandalone ? undefined : "noreferrer"}
              className="w-full flex items-center justify-between px-3.5 py-3 rounded-2xl text-sm font-semibold text-ink-muted hover:text-ink hover:bg-surface-muted transition-colors"
              title={t("sidebar.docsTitle")}
            >
              <div className="flex items-center gap-3">
                <BookOpen className="w-4 h-4 text-ink-muted" />
                <span>{t("sidebar.docs")}</span>
              </div>
              {!isStandalone && <ArrowUpRight className="w-3.5 h-3.5 text-ink-muted" />}
            </a>

            {SIDEBAR_GENERAL.map((id) => {
              const entry = NAV[id];
              const Icon = entry.icon;
              const isActive = activeTab === id;
              return (
                <button
                  key={id}
                  onClick={() => onTabChange(id)}
                  className={`w-full flex items-center justify-between px-3.5 py-3 rounded-2xl text-sm font-semibold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
                    isActive
                      ? "bg-brand text-brand-ink shadow-lg shadow-brand/20"
                      : "text-ink-muted hover:text-ink hover:bg-surface-muted"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <Icon className={`w-4 h-4 ${isActive ? "text-white" : "text-ink-muted"}`} />
                    <span>{t(entry.labelKey)}</span>
                  </div>
                  {isActive && <span className="w-1.5 h-1.5 rounded-full bg-emerald-300" />}
                </button>
              );
            })}

            <button
              onClick={onLogout}
              className="w-full flex items-center gap-3 px-3.5 py-3 rounded-2xl text-sm font-semibold text-danger-ink-on-soft hover:bg-danger-soft hover:text-danger-ink-on-soft transition-colors"
            >
              <LogOut className="w-4 h-4 text-danger-ink-on-soft" />
              <span>{t("sidebar.logout")}</span>
            </button>
          </nav>
        </div>
      </div>
    </aside>
  );
}
