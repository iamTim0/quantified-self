"use client";

import React, { useState, useEffect } from "react";
import Header, { TabType } from "./components/Header";
import OverviewTab from "./components/OverviewTab";
import ExplorerTab from "./components/ExplorerTab";
import ConnectorsPage, { ConnectorInfo } from "./components/ConnectorsPage";
import ConnectorModal from "./components/ConnectorModal";
import AuthScreen, { UserAuthData } from "./components/AuthScreen";
import ShareModal from "./components/ShareModal";
import ProfileTab from "./components/ProfileTab";
import { SummaryMetrics } from "./components/MetricCards";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function DashboardPage() {
  const [mounted, setMounted] = useState(false);
  const [activeTab, setActiveTab] = useState<TabType>("overview");

  const [token, setToken] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [userName, setUserName] = useState("Timo");
  const [userEmail, setUserEmail] = useState("timo@example.com");
  const [userRole, setUserRole] = useState("owner");
  const [tenantName, setTenantName] = useState("Timo's Workspace");
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  const [summary, setSummary] = useState<SummaryMetrics>({});
  const [chartLabels, setChartLabels] = useState<string[]>([]);
  const [sleepValues, setSleepValues] = useState<number[]>([]);
  const [readinessValues, setReadinessValues] = useState<number[]>([]);
  const [calorieValues, setCalorieValues] = useState<number[]>([]);
  const [proteinValues, setProteinValues] = useState<number[]>([]);
  const [carbValues, setCarbValues] = useState<number[]>([]);
  const [fatValues, setFatValues] = useState<number[]>([]);

  const [selectedModalConnector, setSelectedModalConnector] = useState<ConnectorInfo | undefined>(undefined);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleOpenConfigureModal = (connector?: ConnectorInfo) => {
    setSelectedModalConnector(connector);
    setIsModalOpen(true);
  };

  useEffect(() => {
    setMounted(true);
    const storedToken = localStorage.getItem("qs_token") || "";
    const storedTenant = localStorage.getItem("qs_tenant_id") || "";
    if (storedToken && storedTenant) {
      setToken(storedToken);
      setTenantId(storedTenant);
      setUserName(localStorage.getItem("qs_user_name") || "Timo");
      setUserEmail(localStorage.getItem("qs_user_email") || "timo@example.com");
      setUserRole(localStorage.getItem("qs_user_role") || "owner");
      setTenantName(localStorage.getItem("qs_tenant_name") || "Timo's Workspace");
      setIsAuthenticated(true);
    }
  }, []);

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
    if (!mounted || !isAuthenticated) return;
    let isMounted = true;

    async function loadDashboardData() {
      try {
        const headers = {
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": tenantId,
        };

        const [summaryRes, metricsRes] = await Promise.all([
          fetch(`${API_BASE}/api/v1/data/metrics/summary`, { headers }),
          fetch(`${API_BASE}/api/v1/data/metrics?limit=300`, { headers }),
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
          const caloriePts = points.filter((p: { metric_type: string }) => p.metric_type === "yazio_calories" || p.metric_type === "consumed_item_calories");
          const proteinPts = points.filter((p: { metric_type: string }) => p.metric_type === "yazio_protein");
          const carbPts = points.filter((p: { metric_type: string }) => p.metric_type === "yazio_carbs");
          const fatPts = points.filter((p: { metric_type: string }) => p.metric_type === "yazio_fat");

          const formatDate = (isoString?: string) => {
            if (!isoString) return "";
            try {
              const d = new Date(isoString);
              if (isNaN(d.getTime())) return "";
              return d.toISOString().split("T")[0];
            } catch {
              return "";
            }
          };

          const timestamps = Array.from(
            new Set(
              points
                .map((p: { timestamp?: string }) => formatDate(p.timestamp))
                .filter(Boolean)
            )
          ).sort() as string[];

          setChartLabels(timestamps);
          setSleepValues(
            timestamps.map((ts) => {
              const pt = sleepPts.find((p: { timestamp: string }) => formatDate(p.timestamp) === ts);
              return pt ? pt.value : 0;
            })
          );
          setReadinessValues(
            timestamps.map((ts) => {
              const pt = readinessPts.find((p: { timestamp: string }) => formatDate(p.timestamp) === ts);
              return pt ? pt.value : 0;
            })
          );
          setCalorieValues(
            timestamps.map((ts) => {
              const pts = caloriePts.filter((p: { timestamp: string }) => formatDate(p.timestamp) === ts);
              return pts.length > 0 ? pts.reduce((acc: number, p: { value: number }) => acc + (p.value || 0), 0) : 0;
            })
          );
          setProteinValues(
            timestamps.map((ts) => {
              const pt = proteinPts.find((p: { timestamp: string }) => formatDate(p.timestamp) === ts);
              return pt ? pt.value : 0;
            })
          );
          setCarbValues(
            timestamps.map((ts) => {
              const pt = carbPts.find((p: { timestamp: string }) => formatDate(p.timestamp) === ts);
              return pt ? pt.value : 0;
            })
          );
          setFatValues(
            timestamps.map((ts) => {
              const pt = fatPts.find((p: { timestamp: string }) => formatDate(p.timestamp) === ts);
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
  }, [mounted, isAuthenticated, token, tenantId, refreshTrigger]);

  if (!mounted) {
    return <div className="min-h-screen bg-neutral-950" />;
  }

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
          activeTab={activeTab}
          onTabChange={setActiveTab}
          onOpenModal={() => handleOpenConfigureModal()}
          onShare={() => setIsShareModalOpen(true)}
          onLogout={handleLogout}
        />

        {activeTab === "overview" && (
          <OverviewTab
            summary={summary}
            chartLabels={chartLabels}
            sleepValues={sleepValues}
            readinessValues={readinessValues}
            calorieValues={calorieValues}
            proteinValues={proteinValues}
            carbValues={carbValues}
            fatValues={fatValues}
            onRefresh={triggerRefresh}
            onNavigateToConnectors={() => setActiveTab("connectors")}
          />
        )}

        {activeTab === "explorer" && (
          <ExplorerTab apiBase={API_BASE} token={token} tenantId={tenantId} />
        )}

        {activeTab === "connectors" && (
          <ConnectorsPage
            apiBase={API_BASE}
            token={token}
            tenantId={tenantId}
            onOpenConfigureModal={(c) => handleOpenConfigureModal(c)}
          />
        )}

        {activeTab === "profile" && (
          <ProfileTab
            apiBase={API_BASE}
            token={token}
            tenantId={tenantId}
            userName={userName}
            userEmail={userEmail}
            userRole={userRole}
            tenantName={tenantName}
            onUpdateProfile={(name, email) => {
              setUserName(name);
              setUserEmail(email);
              localStorage.setItem("qs_user_name", name);
              localStorage.setItem("qs_user_email", email);
            }}
            onLogout={handleLogout}
          />
        )}

        <ConnectorModal
          isOpen={isModalOpen}
          onClose={() => {
            setIsModalOpen(false);
            setSelectedModalConnector(undefined);
          }}
          initialSourceType={selectedModalConnector?.source_type}
          initialPollInterval={selectedModalConnector?.poll_interval_hours || 6}
          initialLookbackDays={selectedModalConnector?.lookback_days || 30}
          isEditing={Boolean(selectedModalConnector)}
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
