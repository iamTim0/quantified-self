"use client";

import React from "react";
import { Plus, Share2, LogOut, LayoutDashboard, LineChart, Plug, User } from "lucide-react";

export type TabType = "overview" | "explorer" | "connectors" | "profile";

interface HeaderProps {
  tenantId: string;
  userName: string;
  userEmail: string;
  userRole: string;
  tenantName: string;
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  onOpenModal: () => void;
  onShare: () => void;
  onLogout: () => void;
}

export default function Header({
  userName,
  userEmail,
  userRole,
  tenantName,
  activeTab,
  onTabChange,
  onOpenModal,
  onShare,
  onLogout,
}: HeaderProps) {
  const getInitials = (name: string) => {
    if (!name) return "QS";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  };

  return (
    <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6 pb-6 border-b border-slate-200">
      <div className="flex items-center gap-4">
        <button
          onClick={() => onTabChange("profile")}
          className="w-11 h-11 rounded-2xl bg-[#0d5c3a] text-white flex items-center justify-center font-bold text-sm shadow-md shadow-[#0d5c3a]/20 hover:scale-105 transition-transform"
          title="Zum Profil"
        >
          {getInitials(userName)}
        </button>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-900">{tenantName}</h1>
            <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 font-bold">
              {userRole}
            </span>
          </div>
          <p className="text-xs text-slate-500">
            Willkommen zurück, {userName} <span className="text-slate-400">({userEmail})</span>
          </p>
        </div>
      </div>

      {/* Navigation Tabs */}
      <nav className="flex items-center p-1 rounded-2xl bg-slate-100 border border-slate-200">
        <button
          onClick={() => onTabChange("overview")}
          className={`flex items-center gap-2 px-3 py-1.5 text-xs font-bold rounded-xl transition-all ${
            activeTab === "overview"
              ? "bg-[#0d5c3a] text-white shadow-xs"
              : "text-slate-500 hover:text-slate-900"
          }`}
        >
          <LayoutDashboard className="w-3.5 h-3.5" />
          <span>Overview</span>
        </button>
        <button
          onClick={() => onTabChange("explorer")}
          className={`flex items-center gap-2 px-3 py-1.5 text-xs font-bold rounded-xl transition-all ${
            activeTab === "explorer"
              ? "bg-[#0d5c3a] text-white shadow-xs"
              : "text-slate-500 hover:text-slate-900"
          }`}
        >
          <LineChart className="w-3.5 h-3.5" />
          <span>Data Explorer</span>
        </button>
        <button
          onClick={() => onTabChange("connectors")}
          className={`flex items-center gap-2 px-3 py-1.5 text-xs font-bold rounded-xl transition-all ${
            activeTab === "connectors"
              ? "bg-[#0d5c3a] text-white shadow-xs"
              : "text-slate-500 hover:text-slate-900"
          }`}
        >
          <Plug className="w-3.5 h-3.5" />
          <span>Connectors</span>
        </button>
        <button
          onClick={() => onTabChange("profile")}
          className={`flex items-center gap-2 px-3 py-1.5 text-xs font-bold rounded-xl transition-all ${
            activeTab === "profile"
              ? "bg-[#0d5c3a] text-white shadow-xs"
              : "text-slate-500 hover:text-slate-900"
          }`}
        >
          <User className="w-3.5 h-3.5" />
          <span>Profil</span>
        </button>
      </nav>

      <div className="flex items-center gap-2 w-full md:w-auto justify-end">
        <button
          onClick={onShare}
          className="flex items-center gap-2 px-3.5 py-2 text-xs font-bold rounded-2xl bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 transition-all shadow-xs"
        >
          <Share2 className="w-3.5 h-3.5 text-slate-500" />
          <span>Teilen</span>
        </button>
        <button
          onClick={onOpenModal}
          className="flex items-center gap-2 px-3.5 py-2 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all shadow-md shadow-[#0d5c3a]/20"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Connector Hinzufügen</span>
        </button>
        <button
          onClick={onLogout}
          className="p-2 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-2xl transition-colors"
          title="Abmelden"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}
