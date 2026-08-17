"use client";

import React from "react";
import {
  User,
  LogOut,
  Activity,
  ArrowUpRight,
  BookOpen,
} from "lucide-react";

import { useT } from "../lib/i18n/provider";

// Both desktop and phone navigation render the same registry, so a destination
// cannot be added to one surface and silently omitted from the other.
import { NAV, NAV_ORDER, type TabType } from "./navigation";

export type { TabType };

interface SidebarProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  onLogout: () => void;
}

export default function Sidebar({ activeTab, onTabChange, onLogout }: SidebarProps) {
  const t = useT();
  const menuItems = NAV_ORDER.filter((id) => id !== "profile").map((id) => {
    const entry = NAV[id];
    return { id, label: t(entry.labelKey), icon: entry.icon };
  });

  return (
    <aside className="w-64 flex-shrink-0 bg-[#fcfdfe] border-r border-slate-200/80 p-6 flex flex-col justify-between min-h-screen rounded-l-3xl">
      <div>
        {/* Logo Header */}
        <div className="flex items-center gap-3 mb-10 pl-2">
          <div className="w-10 h-10 rounded-2xl bg-brand flex items-center justify-center text-brand-ink shadow-md shadow-brand/20">
            <Activity className="w-5 h-5" />
          </div>
          <div>
            <span className="text-xl font-bold text-slate-900 tracking-tight block leading-none">
              Quantified
            </span>
            <span className="text-[10px] font-semibold tracking-wider text-emerald-700 uppercase">
              Self Platform
            </span>
          </div>
        </div>

        {/* MENU Section */}
        <div className="mb-8">
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-widest px-3 mb-3 block">
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
                      : "text-slate-500 hover:text-slate-900 hover:bg-slate-100/80"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <Icon className={`w-4 h-4 ${isActive ? "text-white" : "text-slate-400"}`} />
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
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-widest px-3 mb-3 block">
            {t("sidebar.general")}
          </span>
          <nav className="space-y-1">
            {/* Relative on purpose: Traefik serves the docs container under /docs
                on this same host, so an absolute URL only ever named one
                particular deployment -- and put its owner's domain in the source. */}
            <a
              href="/docs/"
              target="_blank"
              rel="noreferrer"
              className="w-full flex items-center justify-between px-3.5 py-3 rounded-2xl text-sm font-semibold text-slate-500 hover:text-slate-900 hover:bg-slate-100/80 transition-colors"
              title={t("sidebar.docsTitle")}
            >
              <div className="flex items-center gap-3">
                <BookOpen className="w-4 h-4 text-slate-400" />
                <span>{t("sidebar.docs")}</span>
              </div>
              <ArrowUpRight className="w-3.5 h-3.5 text-slate-400" />
            </a>

            <button
              onClick={() => onTabChange("profile")}
              className={`w-full flex items-center justify-between px-3.5 py-3 rounded-2xl text-sm font-semibold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] ${
                activeTab === "profile"
                  ? "bg-brand text-brand-ink shadow-lg shadow-brand/20"
                  : "text-slate-500 hover:text-slate-900 hover:bg-slate-100/80"
              }`}
            >
              <div className="flex items-center gap-3">
                <User
                  className={`w-4 h-4 ${activeTab === "profile" ? "text-white" : "text-slate-400"}`}
                />
                <span>{t("sidebar.settings")}</span>
              </div>
            </button>

            <button
              onClick={onLogout}
              className="w-full flex items-center gap-3 px-3.5 py-3 rounded-2xl text-sm font-semibold text-rose-500 hover:bg-rose-50 hover:text-rose-600 transition-colors"
            >
              <LogOut className="w-4 h-4 text-rose-400" />
              <span>{t("sidebar.logout")}</span>
            </button>
          </nav>
        </div>
      </div>
    </aside>
  );
}
