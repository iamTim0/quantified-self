"use client";

import React from "react";
import { LayoutDashboard, LineChart, Plug, User, LogOut, Share2, Activity, ArrowUpRight, ScanSearch, BrainCircuit, BookOpen } from "lucide-react";

export type TabType = "overview" | "explorer" | "quality" | "analysis" | "connectors" | "profile";

interface SidebarProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  onShare: () => void;
  onLogout: () => void;
}

export default function Sidebar({ activeTab, onTabChange, onShare, onLogout }: SidebarProps) {
  const menuItems = [
    { id: "overview" as TabType, label: "Dashboard", icon: LayoutDashboard },
    { id: "explorer" as TabType, label: "Data Explorer", icon: LineChart },
    { id: "quality" as TabType, label: "Data Quality", icon: ScanSearch },
    { id: "analysis" as TabType, label: "Analysen", icon: BrainCircuit },
    { id: "connectors" as TabType, label: "Connectors", icon: Plug },
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
            MENU
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
                  {isActive && (
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-300" />
                  )}
                </button>
              );
            })}

            <button
              onClick={onShare}
              className="w-full flex items-center gap-3 px-3.5 py-3 rounded-2xl text-sm font-semibold text-slate-500 hover:text-slate-900 hover:bg-slate-100/80 transition-all"
            >
              <Share2 className="w-4 h-4 text-slate-400" />
              <span>Teilen & Export</span>
            </button>
          </nav>
        </div>

        {/* GENERAL Section */}
        <div>
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-widest px-3 mb-3 block">
            GENERAL
          </span>
          <nav className="space-y-1">
            <a
              href="https://quantified-self.example.com/docs/"
              target="_blank"
              rel="noreferrer"
              className="w-full flex items-center justify-between px-3.5 py-3 rounded-2xl text-sm font-semibold text-slate-500 hover:text-slate-900 hover:bg-slate-100/80 transition-all"
              title="Zentrale Plattform-Dokumentation öffnen"
            >
              <div className="flex items-center gap-3">
                <BookOpen className="w-4 h-4 text-slate-400" />
                <span>Dokumentation</span>
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
                <User className={`w-4 h-4 ${activeTab === "profile" ? "text-white" : "text-slate-400"}`} />
                <span>Einstellungen</span>
              </div>
            </button>

            <button
              onClick={onLogout}
              className="w-full flex items-center gap-3 px-3.5 py-3 rounded-2xl text-sm font-semibold text-rose-500 hover:bg-rose-50 hover:text-rose-600 transition-all"
            >
              <LogOut className="w-4 h-4 text-rose-400" />
              <span>Abmelden</span>
            </button>
          </nav>
        </div>
      </div>

      {/* Bottom Promo CTA Card (like Reference Image) */}
      <div className="mt-8 relative overflow-hidden rounded-2xl bg-gradient-to-b from-[#0d5c3a] to-[#08432a] p-4 text-white shadow-xl shadow-[#0d5c3a]/20">
        <div className="flex items-center justify-between mb-2">
          <div className="w-7 h-7 rounded-full bg-emerald-500/20 border border-emerald-400/30 flex items-center justify-center">
            <Activity className="w-3.5 h-3.5 text-emerald-300" />
          </div>
          <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-emerald-400/20 text-emerald-200">
            PRO
          </span>
        </div>
        <h4 className="text-xs font-bold text-white mb-1">Live Quantified Self</h4>
        <p className="text-[11px] text-emerald-100/80 mb-3 leading-tight">
          Verbinde Yazio, Oura & Apple Health für Echtzeit-Analysen.
        </p>
        <button
          onClick={() => onTabChange("connectors")}
          className="w-full py-2 px-3 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs flex items-center justify-center gap-1.5 transition-colors shadow-md"
        >
          <span>Connectors verwalten</span>
          <ArrowUpRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </aside>
  );
}
