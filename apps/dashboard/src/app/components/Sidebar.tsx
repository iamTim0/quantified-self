"use client";

import React from "react";
import {
  LayoutDashboard,
  LineChart,
  Plug,
  User,
  LogOut,
  Share2,
  Activity,
  ArrowUpRight,
  ScanSearch,
  BrainCircuit,
  BookOpen,
} from "lucide-react";

import { useT } from "../lib/i18n/provider";

export type TabType = "overview" | "explorer" | "quality" | "analysis" | "connectors" | "profile";

interface SidebarProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  onShare: () => void;
  onLogout: () => void;
}

export default function Sidebar({ activeTab, onTabChange, onShare, onLogout }: SidebarProps) {
  const t = useT();
  const menuItems = [
    { id: "overview" as TabType, label: t("sidebar.overview"), icon: LayoutDashboard },
    { id: "explorer" as TabType, label: t("sidebar.explorer"), icon: LineChart },
    { id: "quality" as TabType, label: t("sidebar.quality"), icon: ScanSearch },
    { id: "analysis" as TabType, label: t("sidebar.analysis"), icon: BrainCircuit },
    { id: "connectors" as TabType, label: t("sidebar.connectors"), icon: Plug },
  ];

  return (
    <aside className="w-64 flex-shrink-0 bg-[#fcfdfe] border-r border-slate-200/80 p-6 flex flex-col justify-between min-h-screen rounded-l-3xl">
      <div>
        {/* Logo Header */}
        <div className="flex items-center gap-3 mb-10 pl-2">
          <div className="w-10 h-10 rounded-2xl bg-[#0d5c3a] flex items-center justify-center text-white shadow-md shadow-[#0d5c3a]/20">
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
                  className={`w-full flex items-center justify-between px-3.5 py-3 rounded-2xl text-sm font-semibold transition-all ${
                    isActive
                      ? "bg-[#0d5c3a] text-white shadow-lg shadow-[#0d5c3a]/20"
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

            <button
              onClick={onShare}
              className="w-full flex items-center gap-3 px-3.5 py-3 rounded-2xl text-sm font-semibold text-slate-500 hover:text-slate-900 hover:bg-slate-100/80 transition-all"
            >
              <Share2 className="w-4 h-4 text-slate-400" />
              <span>{t("sidebar.share")}</span>
            </button>
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
              className="w-full flex items-center justify-between px-3.5 py-3 rounded-2xl text-sm font-semibold text-slate-500 hover:text-slate-900 hover:bg-slate-100/80 transition-all"
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
              className={`w-full flex items-center justify-between px-3.5 py-3 rounded-2xl text-sm font-semibold transition-all ${
                activeTab === "profile"
                  ? "bg-[#0d5c3a] text-white shadow-lg shadow-[#0d5c3a]/20"
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
              className="w-full flex items-center gap-3 px-3.5 py-3 rounded-2xl text-sm font-semibold text-rose-500 hover:bg-rose-50 hover:text-rose-600 transition-all"
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
