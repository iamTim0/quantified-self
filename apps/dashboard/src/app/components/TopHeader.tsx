"use client";

import React from "react";
import { Plus, RefreshCw, Share2 } from "lucide-react";

interface TopHeaderProps {
  userName: string;
  userEmail: string;
  userRole: string;
  onOpenConfigureModal: () => void;
  onShare: () => void;
  onNavigateToProfile: () => void;
  onRefresh: () => void;
}

export default function TopHeader({
  userName,
  userEmail,
  userRole,
  onOpenConfigureModal,
  onShare,
  onNavigateToProfile,
  onRefresh,
}: TopHeaderProps) {
  const getInitials = (name: string) => {
    if (!name) return "QS";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  };

  return (
    <header className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 pb-6 mb-6 border-b border-slate-200/70">
      <div className="flex-1 text-xs text-slate-500">Automatische Aktualisierung alle 30 Sekunden</div>

      {/* Right Controls */}
      <div className="flex items-center justify-end gap-3">
        <button
          onClick={onRefresh}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-2xl bg-white border border-slate-200 text-xs font-semibold text-slate-600 hover:text-slate-900 hover:bg-slate-50 transition-all shadow-sm"
          title="Gesamte Seite aktualisieren"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Aktualisieren</span>
        </button>
        {/* Quick Share Action */}
        <button
          onClick={onShare}
          className="hidden md:flex items-center gap-1.5 px-3.5 py-2 rounded-2xl bg-white border border-slate-200 text-xs font-semibold text-slate-600 hover:text-slate-900 hover:bg-slate-50 transition-all shadow-sm"
        >
          <Share2 className="w-3.5 h-3.5 text-slate-500" />
          <span>Export & Teilen</span>
        </button>

        {/* Add Connector Button (Primary Dark Emerald) */}
        <button
          onClick={onOpenConfigureModal}
          className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white text-xs font-bold transition-all shadow-md shadow-[#0d5c3a]/20"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Connector hinzufügen</span>
        </button>

        <div className="h-6 w-px bg-slate-200 mx-1 hidden sm:block" />

        {/* User Profile Pill */}
        <button
          onClick={onNavigateToProfile}
          className="flex items-center gap-3 pl-2 pr-3 py-1.5 rounded-2xl bg-white border border-slate-200 hover:border-slate-300 transition-all shadow-sm group"
        >
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-emerald-600 to-teal-700 text-white font-bold text-xs flex items-center justify-center shadow-inner">
            {getInitials(userName)}
          </div>
          <div className="text-left hidden lg:block">
            <div className="text-xs font-bold text-slate-900 group-hover:text-[#0d5c3a] transition-colors leading-tight">
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
