"use client";

import React, { useState, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar, { TabType } from "./components/Sidebar";
import TopHeader from "./components/TopHeader";
import OverviewTab from "./components/OverviewTab";
import ExplorerTab from "./components/ExplorerTab";
import ConnectorsPage, { ConnectorItem } from "./components/ConnectorsPage";
import ConnectorModal from "./components/ConnectorModal";
import AuthScreen, { UserAuthData } from "./components/AuthScreen";
import ShareModal from "./components/ShareModal";
import ProfileTab from "./components/ProfileTab";
import { SummaryMetrics } from "./components/MetricCards";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function DashboardPage() {
  const [mounted, setMounted] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  const getTabFromPathname = (path: string): TabType => {
    if (path.startsWith("/explorer")) return "explorer";
    if (path.startsWith("/connectors")) return "connectors";
    if (path.startsWith("/profile") || path.startsWith("/settings")) return "profile";
    return "overview";
  };

  const activeTab = getTabFromPathname(pathname);

  const handleTabChange = (tab: TabType) => {
    if (tab === "explorer") router.push("/explorer");
    else if (tab === "connectors") router.push("/connectors");
    else if (tab === "profile") router.push("/profile");
    else router.push("/");
  };

  const [token, setToken] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [userName, setUserName] = useState("Timo");
  const [userEmail, setUserEmail] = useState("owner@example.com");
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

  const [selectedModalConnector, setSelectedModalConnector] = useState<ConnectorItem | undefined>(undefined);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const triggerRefresh = () => setRefreshTrigger((prev) => prev + 1);

  useEffect(() => {
    setMounted(true);
    const savedToken = localStorage.getItem("qs_token");
    const savedTenantId = localStorage.getItem("qs_tenant_id");
    const savedUserName = localStorage.getItem("qs_user_name");
    const savedUserEmail = localStorage.getItem("qs_user_email");
    const savedUserRole = localStorage.getItem("qs_user_role");

    if (savedToken && savedTenantId) {
      setToken(savedToken);
      setTenantId(savedTenantId);
      if (savedUserName) setUserName(savedUserName);
      if (savedUserEmail) setUserEmail(savedUserEmail);
      if (savedUserRole) setUserRole(savedUserRole);
      setIsAuthenticated(true);
    }
  }, []);

  const handleLogin = (data: UserAuthData) => {
    setToken(data.token);
    setTenantId(data.tenantId);
    setUserName(data.name);
    setUserEmail(data.email);
    setUserRole(data.role);

    localStorage.setItem("qs_token", data.token);
    localStorage.setItem("qs_tenant_id", data.tenantId);
    localStorage.setItem("qs_user_name", data.name);
    localStorage.setItem("qs_user_email", data.email);
    localStorage.setItem("qs_user_role", data.role);

    setIsAuthenticated(true);
  };

  const handleLogout = () => {
    localStorage.removeItem("qs_token");
    localStorage.removeItem("qs_tenant_id");
    localStorage.removeItem("qs_user_name");
    localStorage.removeItem("qs_user_email");
    localStorage.removeItem("qs_user_role");
    setToken("");
    setTenantId("");
    setIsAuthenticated(false);
  };

  const handleOpenConfigureModal = (connector?: ConnectorItem, sourceType?: string) => {
    if (connector) {
      setSelectedModalConnector(connector);
    } else if (sourceType) {
      setSelectedModalConnector({
        id: "",
        tenant_id: tenantId,
        source_type: sourceType,
        status: "active",
        masked_token: "••••••••",
        poll_interval_hours: 6,
        lookback_days: 30,
      });
    } else {
      setSelectedModalConnector(undefined);
    }
    setIsModalOpen(true);
  };

  useEffect(() => {
    if (!mounted || !isAuthenticated || !token || !tenantId) return;

    let isMounted = true;

    async function loadDashboardData() {
      try {
        const [summaryRes, metricsRes] = await Promise.all([
          fetch(`${API_BASE}/api/v1/data/metrics/summary`, {
            headers: { Authorization: `Bearer ${token}`, "X-Tenant-ID": tenantId },
          }),
          fetch(`${API_BASE}/api/v1/data/metrics?limit=300`, {
            headers: { Authorization: `Bearer ${token}`, "X-Tenant-ID": tenantId },
          }),
        ]);

        if (summaryRes.ok && isMounted) {
          const sumData = await summaryRes.json();
          setSummary(sumData.metrics || {});
        }

        if (metricsRes.ok && isMounted) {
          const mData = await metricsRes.json();
          const points = mData.data_points || [];

          const sleepPts = points.filter((p: { metric_type: string }) => p.metric_type === "sleep_score");
          const readinessPts = points.filter((p: { metric_type: string }) => p.metric_type === "readiness_score");
          const caloriePts = points.filter((p: { metric_type: string }) => p.metric_type === "calories" || p.metric_type === "yazio_calories" || p.metric_type === "consumed_item_calories");
          const proteinPts = points.filter((p: { metric_type: string }) => p.metric_type === "protein" || p.metric_type === "yazio_protein");
          const carbPts = points.filter((p: { metric_type: string }) => p.metric_type === "carbohydrates" || p.metric_type === "yazio_carbs" || p.metric_type === "carbs");
          const fatPts = points.filter((p: { metric_type: string }) => p.metric_type === "fat" || p.metric_type === "yazio_fat");

          const formatDate = (isoString?: string) => {
            if (!isoString) return "";
            try {
              const d = new Date(isoString);
              if (isNaN(d.getTime())) return "";
              const year = d.getFullYear();
              const month = String(d.getMonth() + 1).padStart(2, "0");
              const day = String(d.getDate()).padStart(2, "0");
              return `${year}-${month}-${day}`;
            } catch {
              return "";
            }
          };

          const today = new Date();
          const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

          let earliestDateStr = todayStr;
          points.forEach((p: { timestamp?: string }) => {
            const dStr = formatDate(p.timestamp);
            if (dStr && dStr < earliestDateStr) {
              earliestDateStr = dStr;
            }
          });

          const earliestDate = new Date(earliestDateStr);
          const minDaysAgo = new Date();
          minDaysAgo.setDate(today.getDate() - 30);
          const startDate = earliestDate < minDaysAgo ? earliestDate : minDaysAgo;

          const timestamps: string[] = [];
          const curr = new Date(startDate);
          while (curr <= today) {
            const y = curr.getFullYear();
            const m = String(curr.getMonth() + 1).padStart(2, "0");
            const d = String(curr.getDate()).padStart(2, "0");
            timestamps.push(`${y}-${m}-${d}`);
            curr.setDate(curr.getDate() + 1);
          }

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
              const pts = proteinPts.filter((p: { timestamp: string }) => formatDate(p.timestamp) === ts);
              return pts.length > 0 ? pts.reduce((acc: number, p: { value: number }) => acc + (p.value || 0), 0) : 0;
            })
          );
          setCarbValues(
            timestamps.map((ts) => {
              const pts = carbPts.filter((p: { timestamp: string }) => formatDate(p.timestamp) === ts);
              return pts.length > 0 ? pts.reduce((acc: number, p: { value: number }) => acc + (p.value || 0), 0) : 0;
            })
          );
          setFatValues(
            timestamps.map((ts) => {
              const pts = fatPts.filter((p: { timestamp: string }) => formatDate(p.timestamp) === ts);
              return pts.length > 0 ? pts.reduce((acc: number, p: { value: number }) => acc + (p.value || 0), 0) : 0;
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
    return <div className="min-h-screen bg-slate-200/60" />;
  }

  if (!isAuthenticated) {
    return <AuthScreen onLogin={handleLogin} apiBase={API_BASE} />;
  }

  return (
    <div className="min-h-screen bg-slate-200/60 p-2 sm:p-4 lg:p-6 flex items-center justify-center">
      {/* Main Outer App Window Shell */}
      <div className="w-full max-w-[1600px] min-h-[900px] bg-[#f8fafc] rounded-3xl shadow-2xl border border-slate-200/80 flex flex-col md:flex-row overflow-hidden">
        {/* Sidebar Navigation with URL Sync */}
        <Sidebar
          activeTab={activeTab}
          onTabChange={handleTabChange}
          onShare={() => setIsShareModalOpen(true)}
          onLogout={handleLogout}
        />

        {/* Main Content Area */}
        <main className="flex-1 p-6 lg:p-8 overflow-y-auto">
          <TopHeader
            userName={userName}
            userEmail={userEmail}
            userRole={userRole}
            onOpenConfigureModal={() => handleOpenConfigureModal()}
            onShare={() => setIsShareModalOpen(true)}
            onNavigateToProfile={() => handleTabChange("profile")}
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
              onNavigateToConnectors={() => handleTabChange("connectors")}
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
              onOpenConfigureModal={(c, st) => handleOpenConfigureModal(c, st)}
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
            isEditing={Boolean(selectedModalConnector?.id)}
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
        </main>
      </div>
    </div>
  );
}
