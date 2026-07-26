"use client";

import React from "react";
import { Activity, Settings, Share2, LogOut } from "lucide-react";

interface HeaderProps {
  tenantId: string;
  onOpenModal: () => void;
  onShare: () => void;
  onLogout: () => void;
}

export default function Header({ tenantId, onOpenModal, onShare, onLogout }: HeaderProps) {
  return (
    <header className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-8 pb-4 border-b border-white/10">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-cyan-500/20 font-bold text-white">
          <Activity className="w-6 h-6" />
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">Quantified Self Platform</h1>
          <p className="text-xs text-gray-400 font-mono">Tenant ID: {tenantId}</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={onShare}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 transition-colors text-white"
        >
          <Share2 className="w-4 h-4" />
          <span>Share</span>
        </button>

        <button
          onClick={onOpenModal}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition-colors text-gray-200"
        >
          <Settings className="w-4 h-4 text-blue-400" />
          <span>Connectors</span>
        </button>

        <button
          onClick={onLogout}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-lg bg-red-500/10 hover:bg-red-500/20 transition-colors text-red-400"
        >
          <LogOut className="w-4 h-4" />
          <span>Sign Out</span>
        </button>
      </div>
    </header>
  );
}
