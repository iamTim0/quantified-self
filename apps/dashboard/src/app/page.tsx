"use client";

import React, { useState, useEffect } from "react";
import Header from "./components/Header";
import MetricCards, { SummaryMetrics } from "./components/MetricCards";
import TrendChart from "./components/TrendChart";
import ConnectorModal from "./components/ConnectorModal";
import AuthScreen from "./components/AuthScreen";
import ShareModal from "./components/ShareModal";
import { Activity, RefreshCw } from "lucide-react";

// SECURITY C5: All API calls go through the Gateway (port 8000), never directly to Core.
// The Gateway validates JWT tokens and injects X-Tenant-ID headers.
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

interface ConnectorItem {
  id: string;
  source_type: string;
  status: string;
  masked_token: string;
}

export default function DashboardPage() {
  const [tenantId, setTenantId] = useState("");
  const [token, setToken] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  
  const [summary, setSummary] = useState<SummaryMetrics>({});
  const [chartLabels, setChartLabels] = useState<string[]>([]);
  const [sleepValues, setSleepValues] = useState<number[]>([]);
  const [readinessValues, setReadinessValues] = useState<number[]>([]);
  const [connectors, setConnectors] = useState<ConnectorItem[]>([]);
  
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // Restore session from localStorage on mount
  useEffect(() => {
    const savedToken = localStorage.getItem("qs_token");
    const savedTenantId = localStorage.getItem("qs_tenant_id");
    if (savedToken && savedTenantId) {
      setToken(savedToken);
      setTenantId(savedTenantId);
      setIsAuthenticated(true);
    }
  }, []);

  const handleLogin = (jwtToken: string, tId: string) => {
    localStorage.setItem("qs_token", jwtToken);
    localStorage.setItem("qs_tenant_id", tId);
    setToken(jwtToken);
    setTenantId(tId);
    setIsAuthenticated(true);
  };

  const handleLogout = () => {
    localStorage.removeItem("qs_token");
    localStorage.removeItem("qs_tenant_id");
    setToken("");
    setTenantId("");
    setIsAuthenticated(false);
  };

  const triggerRefresh = () => setRefreshTrigger((prev) => prev + 1);

  useEffect(() => {
    let isMounted = true;
    async function loadDashboardData() {
      if (!isAuthenticated) return;
      try {
        const headers = { 
          "X-Tenant-ID": tenantId,
          "Authorization": `Bearer ${token}` 
        };
        const [sumRes, sleepRes, readinessRes, connRes] = await Promise.all([
          fetch(`${API_BASE}/api/v1/data/metrics/summary`, { headers }),
          fetch(`${API_BASE}/api/v1/data/metrics?metric_type=sleep_score&limit=30`, { headers }),
          fetch(`${API_BASE}/api/v1/data/metrics?metric_type=readiness_score&limit=30`, { headers }),
          fetch(`${API_BASE}/api/v1/data/sources`, { headers }),
        ]);

        if (isMounted && sumRes.ok) {
          const sumData = await sumRes.json();
          setSummary(sumData.metrics || {});
        }

        if (isMounted && sleepRes.ok && readinessRes.ok) {
          const sleepData = await sleepRes.json();
          const readinessData = await readinessRes.json();
          const points = sleepData.data_points || [];
          const rPoints = readinessData.data_points || [];
          setChartLabels(points.map((p: { timestamp: string }) => p.timestamp.split("T")[0]));
          setSleepValues(points.map((p: { value: number }) => p.value));
          setReadinessValues(rPoints.map((p: { value: number }) => p.value));
        }

        if (isMounted && connRes.ok) {
          const connData = await connRes.json();
          setConnectors(connData.connectors || []);
    if (isAuthenticated) {
      loadDashboardData();
    }
    return () => {
      isMounted = false;
    };
  }, [tenantId, token, isAuthenticated, refreshTrigger]);

  if (!isAuthenticated) {
    return <AuthScreen onLogin={handleLogin} apiBase={API_BASE} />;
  }

  return (
    <main className="min-h-screen bg-black text-gray-100 p-4 sm:p-8 font-sans selection:bg-blue-500/30">
      <div className="max-w-6xl mx-auto">
        <Header 
          tenantId={tenantId} 
          onOpenModal={() => setIsModalOpen(true)} 
          onShare={() => setIsShareModalOpen(true)}
          onLogout={handleLogout}
        />

      <MetricCards metrics={summary} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <TrendChart
            labels={chartLabels}
            sleepValues={sleepValues}
            readinessValues={readinessValues}
            onRefresh={triggerRefresh}
          />
        </div>

        {/* Configured Connectors Control Widget */}
        <div className="glass-card p-6 flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-base font-semibold text-white flex items-center gap-2">
                <Activity className="w-4 h-4 text-blue-400" />
                <span>Configured Connectors</span>
              </h2>
              <button
                onClick={() => setIsModalOpen(true)}
                className="px-2.5 py-1 text-xs font-semibold rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 text-gray-300 transition-colors"
              >
                + Add
              </button>
            </div>

            <div className="space-y-3">
              {connectors.length === 0 ? (
                <div className="text-xs text-gray-400 py-4">No connectors configured yet. Click + Add to configure.</div>
              ) : (
                connectors.map((c) => (
                  <div key={c.id} className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/5">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-blue-500/20 text-blue-400 font-bold flex items-center justify-center text-xs">
                        {c.source_type.substring(0, 2).toUpperCase()}
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-white">{c.source_type.toUpperCase()}</div>
                        <div className="text-xs text-gray-400 font-mono">Token: {c.masked_token}</div>
                      </div>
                    </div>
                    <span className={`text-xs font-bold ${c.status === "active" ? "text-emerald-400" : "text-gray-400"}`}>
                      {c.status.toUpperCase()}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="pt-6 border-t border-white/10 mt-6">
            <button
              onClick={triggerRefresh}
              className="w-full flex items-center justify-center gap-2 py-2.5 text-xs font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Sync All Connectors</span>
            </button>
          </div>
        </div>
      </div>

      <ConnectorModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSaved={triggerRefresh}
        tenantId={tenantId}
        token={token}
      />

      <ShareModal
        isOpen={isShareModalOpen}
        onClose={() => setIsShareModalOpen(false)}
        apiBase={API_BASE}
        token={token}
      />
      </div>
    </main>
  );
}
