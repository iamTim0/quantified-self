"use client";

import React from "react";
import { Activity, Settings } from "lucide-react";

interface HeaderProps {
  tenantId: string;
  onOpenModal: () => void;
}

export default function Header({ tenantId, onOpenModal }: HeaderProps) {
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

      <div className="flex items-center gap-3">
        <button
          onClick={onOpenModal}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition-colors text-gray-200"
        >
          <Settings className="w-4 h-4 text-blue-400" />
          <span>Configure Connectors</span>
        </button>

        <div className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-full bg-white/5 border border-white/10 text-emerald-400">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shadow-sm shadow-emerald-500" />
          <span>Core Service Connected</span>
        </div>
      </div>
    </header>
  );
}
