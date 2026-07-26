"use client";

import React, { useState, useEffect } from "react";
import Header from "./components/Header";
import MetricCards, { SummaryMetrics } from "./components/MetricCards";
import TrendChart from "./components/TrendChart";
import ConnectorModal from "./components/ConnectorModal";
import AuthScreen, { UserAuthData } from "./components/AuthScreen";
import ShareModal from "./components/ShareModal";
import { RefreshCw } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function DashboardPage() {
  const [token, setToken] = useState(() => (typeof window !== "undefined" ? localStorage.getItem("qs_token") || "" : ""));
  const [tenantId, setTenantId] = useState(() => (typeof window !== "undefined" ? localStorage.getItem("qs_tenant_id") || "" : ""));
  const [userName, setUserName] = useState(() => (typeof window !== "undefined" ? localStorage.getItem("qs_user_name") || "Timo" : "Timo"));
  const [userEmail, setUserEmail] = useState(() => (typeof window !== "undefined" ? localStorage.getItem("qs_user_email") || "timo@example.com" : "timo@example.com"));
  const [userRole, setUserRole] = useState(() => (typeof window !== "undefined" ? localStorage.getItem("qs_user_role") || "owner" : "owner"));
  const [tenantName, setTenantName] = useState(() => (typeof window !== "undefined" ? localStorage.getItem("qs_tenant_name") || "Timo's Workspace" : "Timo's Workspace"));

  const [isAuthenticated, setIsAuthenticated] = useState(() => typeof window !== "undefined" && Boolean(localStorage.getItem("qs_token") && localStorage.getItem("qs_tenant_id")));

  const [summary, setSummary] = useState<SummaryMetrics>({});
  const [chartLabels, setChartLabels] = useState<string[]>([]);
  const [sleepValues, setSleepValues] = useState<number[]>([]);
  const [readinessValues, setReadinessValues] = useState<number[]>([]);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleLogin = (auth: UserAuthData) => {
    localStorage.setItem("qs_token", auth.token);
    localStorage.setItem("qs_tenant_id", auth.tenantId);
    localStorage.setItem("qs_user_name", auth.userName);
    localStorage.setItem("qs_user_email", auth.userEmail);
    localStorage.setItem("qs_user_role", auth.userRole);
    localStorage.setItem("qs_tenant_name", auth.tenantName);

    setToken(auth.token);
    setTenantId(auth.tenantId);
    setUserName(auth.userName);
    setUserEmail(auth.userEmail);
    setUserRole(auth.userRole);
    setTenantName(auth.tenantName);
    setIsAuthenticated(true);
  };

  const handleLogout = () => {
    localStorage.clear();
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
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": tenantId,
        };

        const [summaryRes, metricsRes] = await Promise.all([
          fetch(`${API_BASE}/api/v1/data/metrics/summary`, { headers }),
          fetch(`${API_BASE}/api/v1/data/metrics?limit=30`, { headers }),
        ]);

        if (summaryRes.ok && isMounted) {
          const sData = await summaryRes.json();
          setSummary(sData.metrics || {});
        }

        if (metricsRes.ok && isMounted) {
          const mData = await metricsRes.json();
          const points = mData.data_points || [];

          const sleepPts = points.filter((p: { metric_type: string }) => p.metric_type === "sleep_score");
          const readinessPts = points.filter((p: { metric_type: string }) => p.metric_type === "readiness_score");

          const timestamps = Array.from(
            new Set(points.map((p: { timestamp: string }) => new Date(p.timestamp).toLocaleDateString()))
          ).sort() as string[];

          setChartLabels(timestamps);
          setSleepValues(
            timestamps.map((ts) => {
              const pt = sleepPts.find((p: { timestamp: string }) => new Date(p.timestamp).toLocaleDateString() === ts);
              return pt ? pt.value : 0;
            })
          );
          setReadinessValues(
            timestamps.map((ts) => {
              const pt = readinessPts.find((p: { timestamp: string }) => new Date(p.timestamp).toLocaleDateString() === ts);
              return pt ? pt.value : 0;
            })
          );
        }
      } catch (err) {
        console.error("Failed to load dashboard data:", err);
      }
    }

    loadDashboardData();
    return () => {
      isMounted = false;
    };
  }, [isAuthenticated, token, tenantId, refreshTrigger]);

  if (!isAuthenticated) {
    return <AuthScreen onLogin={handleLogin} apiBase={API_BASE} />;
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-white p-4 sm:p-6 lg:p-8">
      <div className="max-w-7xl mx-auto">
        <Header
          tenantId={tenantId}
          userName={userName}
          userEmail={userEmail}
          userRole={userRole}
          tenantName={tenantName}
          onOpenModal={() => setIsModalOpen(true)}
          onShare={() => setIsShareModalOpen(true)}
          onLogout={handleLogout}
        />

        <div className="flex justify-between items-center mb-6">
          <h2 className="text-lg font-semibold text-neutral-200">Health & Fitness Overview</h2>
          <button
            onClick={triggerRefresh}
            className="flex items-center gap-2 text-xs text-neutral-400 hover:text-white transition-colors bg-neutral-900 border border-neutral-800 px-3 py-1.5 rounded-lg"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>
        </div>

        <MetricCards metrics={summary} />

        <div className="mt-8">
          <TrendChart
            labels={chartLabels}
            sleepValues={sleepValues}
            readinessValues={readinessValues}
            onRefresh={triggerRefresh}
          />
        </div>

        <ConnectorModal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          token={token}
          tenantId={tenantId}
          onSaved={triggerRefresh}
        />

        <ShareModal
          isOpen={isShareModalOpen}
          onClose={() => setIsShareModalOpen(false)}
          apiBase={API_BASE}
          token={token}
        />
      </div>
    </div>
  );
}
