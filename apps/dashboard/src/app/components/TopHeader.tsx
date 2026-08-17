"use client";

import React from "react";
import { BookOpen, Plus, RefreshCw } from "lucide-react";

import { useT } from "../lib/i18n/provider";
import LanguageSwitcher from "./LanguageSwitcher";
import NotificationBell from "./NotificationBell";
import ThemeSwitcher from "./ThemeSwitcher";

interface TopHeaderProps {
  apiBase: string;
  userName: string;
  userEmail: string;
  onOpenConfigureModal: () => void;
  onNavigateToProfile: () => void;
  onRefresh: () => void;
}

export default function TopHeader({
  apiBase,
  userName,
  userEmail,
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
    <header className="mb-6 flex flex-col items-stretch gap-4 border-b border-slate-200/70 pb-6 sm:flex-row sm:items-center sm:justify-end">
      {/* Every control shares the same 44px track. This keeps the row stable when
          a translated label or the profile name takes a different width. */}
      <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 sm:gap-3">
        <a
          href="/docs/"
          target="_blank"
          rel="noreferrer"
          className="hidden h-11 items-center gap-1.5 rounded-2xl border border-slate-200 bg-white px-3.5 text-xs font-semibold text-slate-600 shadow-sm [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] hover:bg-slate-50 hover:text-slate-900 sm:flex"
          title={t("sidebar.docsTitle")}
        >
          <BookOpen className="w-3.5 h-3.5 text-brand" />
          <span>{t("header.docs")}</span>
        </a>
        <NotificationBell apiBase={apiBase} />
        <button
          onClick={onRefresh}
          aria-label={t("header.refresh")}
          className="flex h-11 items-center gap-1.5 rounded-2xl border border-slate-200 bg-white px-3.5 text-xs font-semibold text-slate-600 shadow-sm [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] hover:bg-slate-50 hover:text-slate-900"
          title={t("header.refreshTitle")}
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">{t("header.refresh")}</span>
        </button>
        {/* Add Connector Button (Primary Dark Emerald) */}
        <button
          onClick={onOpenConfigureModal}
          aria-label={t("header.addConnector")}
          className="flex h-11 items-center gap-2 rounded-2xl bg-brand px-4 text-xs font-bold text-brand-ink shadow-md shadow-brand/20 [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] hover:bg-brand-hover"
        >
          <Plus className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">{t("header.addConnector")}</span>
        </button>

        <LanguageSwitcher />

        <ThemeSwitcher />

        <div className="h-6 w-px bg-slate-200 mx-1 hidden sm:block" />

        {/* User Profile Pill */}
        <button
          onClick={onNavigateToProfile}
          className="flex h-11 items-center gap-3 rounded-2xl border border-slate-200 bg-white pl-2 pr-3 shadow-sm [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] hover:border-slate-300 group"
        >
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-emerald-600 to-teal-700 text-white font-bold text-xs flex items-center justify-center shadow-inner">
            {getInitials(userName)}
          </div>
          <div className="text-left hidden lg:block">
            <div className="text-xs font-bold text-slate-900 group-hover:text-brand transition-colors leading-tight">
              {userName}
            </div>
            <div className="text-[10px] text-slate-400 font-mono truncate max-w-[140px]">
              {userEmail}
            </div>
          </div>
        </button>
      </div>
    </header>
  );
}
