"use client";

import React from "react";
import { Activity, Settings, Share2, LogOut, User as UserIcon, Building2 } from "lucide-react";

interface HeaderProps {
  tenantId: string;
  userName?: string;
  userEmail?: string;
  userRole?: string;
  tenantName?: string;
  onOpenModal: () => void;
  onShare: () => void;
  onLogout: () => void;
}

export default function Header({
  tenantId,
  userName = "Timo",
  userEmail = "timo@example.com",
  userRole = "owner",
  tenantName = "Timo's Workspace",
  onOpenModal,
  onShare,
  onLogout,
}: HeaderProps) {
  return (
    <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8 pb-4 border-b border-white/10">
      <div className="flex items-center gap-4">
        <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-purple-500/20 text-white">
          <Activity className="w-6 h-6" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold tracking-tight text-white">{tenantName}</h1>
            <span className="px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold rounded-full bg-purple-500/20 border border-purple-500/30 text-purple-300">
              {userRole}
            </span>
          </div>
          <div className="flex items-center gap-3 text-xs text-neutral-400 mt-0.5">
            <span className="flex items-center gap-1">
              <UserIcon className="w-3.5 h-3.5 text-neutral-500" />
              {userName} ({userEmail})
            </span>
            <span>•</span>
            <span className="flex items-center gap-1 font-mono text-neutral-500">
              <Building2 className="w-3.5 h-3.5" />
              Tenant: {tenantId.slice(0, 8)}...
            </span>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={onShare}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-xl bg-purple-600 hover:bg-purple-500 transition-all text-white shadow-lg shadow-purple-600/20"
        >
          <Share2 className="w-4 h-4" />
          <span>Share Data</span>
        </button>

        <button
          onClick={onOpenModal}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition-all text-neutral-200"
        >
          <Settings className="w-4 h-4 text-purple-400" />
          <span>Connectors</span>
        </button>

        <button
          onClick={onLogout}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-xl bg-red-500/10 hover:bg-red-500/20 transition-all text-red-400 border border-red-500/20"
        >
          <LogOut className="w-4 h-4" />
          <span>Sign Out</span>
        </button>
      </div>
    </header>
  );
}
