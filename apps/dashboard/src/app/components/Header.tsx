"use client";

import React from "react";
import { Activity, Plus, Share2, LogOut, LayoutDashboard, LineChart, Plug } from "lucide-react";

export type TabType = "overview" | "explorer" | "connectors";

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
  tenantId,
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
  return (
    <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8 pb-6 border-b border-neutral-800/80">
      <div className="flex items-center gap-4">
        <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white shadow-lg shadow-purple-500/20">
          <Activity className="w-6 h-6" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-white">{tenantName}</h1>
            <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 font-semibold">
              {userRole}
            </span>
          </div>
          <p className="text-xs text-neutral-400">
            Welcome back, {userName} <span className="text-neutral-600">({userEmail})</span>
          </p>
        </div>
      </div>

      {/* Navigation Tabs */}
      <nav className="flex items-center p-1 rounded-xl bg-neutral-900/90 border border-neutral-800 backdrop-blur-md">
        <button
          onClick={() => onTabChange("overview")}
          className={`flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
            activeTab === "overview"
              ? "bg-purple-600 text-white shadow-md shadow-purple-600/20"
              : "text-neutral-400 hover:text-white"
          }`}
        >
          <LayoutDashboard className="w-3.5 h-3.5" />
          <span>Overview</span>
        </button>
        <button
          onClick={() => onTabChange("explorer")}
          className={`flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
            activeTab === "explorer"
              ? "bg-purple-600 text-white shadow-md shadow-purple-600/20"
              : "text-neutral-400 hover:text-white"
          }`}
        >
          <LineChart className="w-3.5 h-3.5" />
          <span>Data Explorer</span>
        </button>
        <button
          onClick={() => onTabChange("connectors")}
          className={`flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
            activeTab === "connectors"
              ? "bg-purple-600 text-white shadow-md shadow-purple-600/20"
              : "text-neutral-400 hover:text-white"
          }`}
        >
          <Plug className="w-3.5 h-3.5" />
          <span>Connectors</span>
        </button>
      </nav>

      <div className="flex items-center gap-2 w-full md:w-auto justify-end">
        <button
          onClick={onShare}
          className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-xl bg-neutral-900 border border-neutral-800 text-neutral-300 hover:text-white hover:border-neutral-700 transition-colors"
        >
          <Share2 className="w-3.5 h-3.5" />
          <span>Share</span>
        </button>
        <button
          onClick={onOpenModal}
          className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition-colors shadow-lg shadow-blue-600/20"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Add Connector</span>
        </button>
        <button
          onClick={onLogout}
          className="p-2 text-neutral-400 hover:text-red-400 hover:bg-red-500/10 rounded-xl transition-colors"
          title="Logout"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}
