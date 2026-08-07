"use client";

import React, { useState, useEffect, useCallback } from "react";
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
import DataQualityTab from "./components/DataQualityTab";
import AnalysisTab from "./components/AnalysisTab";
import LegalFooter from "./components/LegalFooter";
import { SummaryMetrics } from "./components/MetricCards";
import { SessionUser, endSession, fetchSession } from "./lib/session";
import { apiFetch } from "./lib/api";

const getApiBase = (): string => {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined" && window.location.origin) {
    return window.location.origin;
  }
  return "http://127.0.0.1:8000";
};

// There is deliberately no default tenant. A hardcoded seed tenant here is what
// gave the dev-token bootstrap something to silently sign into.

export default function DashboardPage() {
  const API_BASE = getApiBase();
  const [mounted, setMounted] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  const getTabFromPathname = (path: string): TabType => {
    if (path.startsWith("/explorer")) return "explorer";
    if (path.startsWith("/connectors")) return "connectors";
    if (path.startsWith("/quality")) return "quality";
    if (path.startsWith("/analysis")) return "analysis";
    if (path.startsWith("/profile") || path.startsWith("/settings")) return "profile";
    return "overview";
  };

  const activeTab = getTabFromPathname(pathname);

  const handleTabChange = (tab: TabType) => {
    if (tab === "explorer") router.push("/explorer");
    else if (tab === "connectors") router.push("/connectors");
    else if (tab === "quality") router.push("/quality");
    else if (tab === "analysis") router.push("/analysis");
    else if (tab === "profile") router.push("/profile");
    else router.push("/");
  };

  // No access token in component state: the credential is an httpOnly cookie the
  // browser attaches itself, and nothing here can (or should) read it.
  const [tenantId, setTenantId] = useState("");
  const [userName, setUserName] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [userRole, setUserRole] = useState("member");
  // Derived from the signed-in user; the workspace name has no separate endpoint yet.
  const tenantName = userName ? `${userName}'s Workspace` : "";
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

  const triggerRefresh = useCallback(() => setRefreshTrigger((prev) => prev + 1), []);

  useEffect(() => {
    if (!isAuthenticated) return;
    const interval = window.setInterval(triggerRefresh, 30_000);
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") triggerRefresh();
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [isAuthenticated, triggerRefresh]);

  const applySession = useCallback((user: SessionUser) => {
    setTenantId(user.tenantId);
    if (user.name) setUserName(user.name);
    if (user.email) setUserEmail(user.email);
    if (user.role) setUserRole(user.role);
    setIsAuthenticated(true);
  }, []);

  const resetToSignedOut = useCallback(() => {
    setTenantId("");
    setUserName("");
    setUserEmail("");
    setUserRole("member");
    setIsAuthenticated(false);
  }, []);

  // Bootstrap: ask the server whether the cookies we may or may not have amount
  // to a session. There is no local state to consult and nothing here mints a
  // token — `fetchSession` returning null means signed out, full stop.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const user = await fetchSession(API_BASE);
      if (cancelled) return;
      if (user) {
        applySession(user);
      } else {
        resetToSignedOut();
      }
      setMounted(true);
    })();

    return () => {
      cancelled = true;
    };
  }, [API_BASE, applySession, resetToSignedOut]);

  // Logging out in one tab must sign the others out too. The cookie is shared
  // across tabs but its removal fires no event, so a tab that regains focus
  // re-checks with the server rather than trusting what it last rendered.
  useEffect(() => {
    if (!isAuthenticated) return;
    const recheck = async () => {
      if (document.visibilityState !== "visible") return;
      const user = await fetchSession(API_BASE);
      if (!user) resetToSignedOut();
    };
    document.addEventListener("visibilitychange", recheck);
    return () => document.removeEventListener("visibilitychange", recheck);
  }, [API_BASE, isAuthenticated, resetToSignedOut]);

  const handleLogin = (data: UserAuthData) => {
    applySession(data.user);
    triggerRefresh();
  };

  const handleLogout = useCallback(async () => {
    // Sign out locally first so the UI cannot keep rendering protected content
    // while the network call is still in flight.
    const signOut = resetToSignedOut;
    try {
      await endSession(API_BASE);
    } finally {
      signOut();
      router.push("/");
    }
  }, [API_BASE, resetToSignedOut, router]);

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
    if (!mounted || !isAuthenticated) return;

    let isMounted = true;
    const activeTenant = tenantId;

    async function loadDashboardData() {
      try {
        const [summaryRes, metricsRes] = await Promise.all([
          apiFetch(`${API_BASE}/api/v1/data/metrics/summary`, {
            cache: "no-store",
            headers: { "X-Tenant-ID": activeTenant },
          }),
          // Fetch the newest points first so large histories do not hide current data
          // behind the endpoint's result limit. The chart is rendered chronologically below.
          apiFetch(`${API_BASE}/api/v1/data/metrics?limit=1000&sort=desc`, {
            cache: "no-store",
            headers: { "X-Tenant-ID": activeTenant },
          }),
        ]);

        // A rejected token means the session is over — do not keep polling with it.
        if ((summaryRes.status === 401 || metricsRes.status === 401) && isMounted) {
          resetToSignedOut();
          return;
        }

        if (summaryRes.ok && isMounted) {
          const sumData = await summaryRes.json();
          setSummary(sumData.metrics || {});
        }

        if (metricsRes.ok && isMounted) {
          const mData = await metricsRes.json();
          const points = [...(mData.data_points || [])].reverse();

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

          // Calorie Values: Prioritize daily summary 'calories' or 'yazio_calories'.
          // Fall back to sum of 'consumed_item_calories' ONLY if summary is missing to prevent double counting.
          setCalorieValues(
            timestamps.map((ts) => {
              const summaryPt = points.find((p: { metric_type: string; timestamp: string }) =>
                (p.metric_type === "calories" || p.metric_type === "yazio_calories") && formatDate(p.timestamp) === ts
              );
              if (summaryPt) return summaryPt.value || 0;

              const itemPts = points.filter((p: { metric_type: string; timestamp: string }) =>
                p.metric_type === "consumed_item_calories" && formatDate(p.timestamp) === ts
              );
              return itemPts.reduce((acc: number, p: { value: number }) => acc + (p.value || 0), 0);
            })
          );

          setProteinValues(
            timestamps.map((ts) => {
              const summaryPt = points.find((p: { metric_type: string; timestamp: string }) =>
                (p.metric_type === "protein" || p.metric_type === "yazio_protein") && formatDate(p.timestamp) === ts
              );
              if (summaryPt) return summaryPt.value || 0;

              const itemPts = points.filter((p: { metric_type: string; timestamp: string }) =>
                p.metric_type === "consumed_item_protein" && formatDate(p.timestamp) === ts
              );
              return itemPts.reduce((acc: number, p: { value: number }) => acc + (p.value || 0), 0);
            })
          );

          setCarbValues(
            timestamps.map((ts) => {
              const summaryPt = points.find((p: { metric_type: string; timestamp: string }) =>
                (p.metric_type === "carbohydrates" || p.metric_type === "yazio_carbs" || p.metric_type === "carbs") && formatDate(p.timestamp) === ts
              );
              if (summaryPt) return summaryPt.value || 0;

              const itemPts = points.filter((p: { metric_type: string; timestamp: string }) =>
                p.metric_type === "consumed_item_carbs" && formatDate(p.timestamp) === ts
              );
              return itemPts.reduce((acc: number, p: { value: number }) => acc + (p.value || 0), 0);
            })
          );

          setFatValues(
            timestamps.map((ts) => {
              const summaryPt = points.find((p: { metric_type: string; timestamp: string }) =>
                (p.metric_type === "fat" || p.metric_type === "yazio_fat") && formatDate(p.timestamp) === ts
              );
              if (summaryPt) return summaryPt.value || 0;

              const itemPts = points.filter((p: { metric_type: string; timestamp: string }) =>
                p.metric_type === "consumed_item_fat" && formatDate(p.timestamp) === ts
              );
              return itemPts.reduce((acc: number, p: { value: number }) => acc + (p.value || 0), 0);
            })
          );

          setSleepValues(
            timestamps.map((ts) => {
              const pt = points.find((p: { metric_type: string; timestamp: string }) => p.metric_type === "sleep_score" && formatDate(p.timestamp) === ts);
              return pt ? pt.value : 0;
            })
          );

          setReadinessValues(
            timestamps.map((ts) => {
              const pt = points.find((p: { metric_type: string; timestamp: string }) => p.metric_type === "readiness_score" && formatDate(p.timestamp) === ts);
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
  }, [mounted, isAuthenticated, tenantId, refreshTrigger, API_BASE, resetToSignedOut]);

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
            onRefresh={triggerRefresh}
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
              apiBase={API_BASE}
              tenantId={tenantId}
              refreshTrigger={refreshTrigger}
              onRefresh={triggerRefresh}
              onNavigateToConnectors={() => handleTabChange("connectors")}
            />
          )}

          {activeTab === "explorer" && (
            <ExplorerTab key={refreshTrigger} apiBase={API_BASE} tenantId={tenantId} />
          )}

          {activeTab === "connectors" && (
            <ConnectorsPage
              key={refreshTrigger}
              apiBase={API_BASE}
              tenantId={tenantId}
              onOpenConfigureModal={(c, st) => handleOpenConfigureModal(c, st)}
            />
          )}

          {activeTab === "quality" && (
            <DataQualityTab apiBase={API_BASE} tenantId={tenantId} />
          )}

          {activeTab === "analysis" && (
            <AnalysisTab
              apiBase={API_BASE}
              tenantId={tenantId}
              refreshTrigger={refreshTrigger}
            />
          )}

          {activeTab === "profile" && (
            <ProfileTab
              apiBase={API_BASE}
              tenantId={tenantId}
              userName={userName}
              userEmail={userEmail}
              userRole={userRole}
              tenantName={tenantName}
              onUpdateProfile={(name: string, email: string) => {
                // React state only. These used to be mirrored into localStorage
                // to survive a reload; the reload now asks /auth/me instead, so
                // the copy had nothing left reading it.
                setUserName(name);
                setUserEmail(email);
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
            tenantId={tenantId}
            onSaved={triggerRefresh}
          />

          <ShareModal
            isOpen={isShareModalOpen}
            onClose={() => setIsShareModalOpen(false)}
            apiBase={API_BASE}
          />

          <LegalFooter />
        </main>
      </div>
    </div>
  );
}
