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
import ProfileTab from "./components/ProfileTab";
import DataQualityTab from "./components/DataQualityTab";
import AnalysisTab from "./components/AnalysisTab";
import ChatTab from "./components/ChatTab";
import LegalFooter from "./components/LegalFooter";
import SystemWarnings from "./components/SystemWarnings";
import UploadBanner from "./components/UploadBanner";
import { UploadProvider } from "./lib/uploads/provider";
import { SummaryMetrics } from "./components/MetricCards";
import { METRIC_CATALOG } from "./lib/metrics/catalog";
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

/**
 * Read and clear the `next` parameter the route guard leaves behind.
 *
 * `src/proxy.ts` redirects a signed-out deep link to `/?next=<path>`; this sends
 * the user on once they are signed in, instead of dropping them on the overview.
 *
 * Only a path on this origin is accepted. `//evil.example` and `/\evil.example`
 * are both read as protocol-relative URLs by browsers, so a plain "starts with a
 * slash" test is the standard way an open redirect gets in.
 *
 * Reads `window.location.search` rather than `useSearchParams` on purpose: this
 * page is the shell for every route, and a `useSearchParams` call in it would
 * force a Suspense boundary around all of them.
 */
function consumeNextParam(): string | null {
  if (typeof window === "undefined") return null;

  const raw = new URLSearchParams(window.location.search).get("next");
  if (!raw) return null;

  // Clear it either way: a rejected value must not survive a reload.
  const url = new URL(window.location.href);
  url.searchParams.delete("next");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);

  if (!raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) {
    return null;
  }
  return raw;
}

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
    if (path.startsWith("/chat")) return "chat";
    if (path.startsWith("/profile") || path.startsWith("/settings")) return "profile";
    return "overview";
  };

  const activeTab = getTabFromPathname(pathname);

  const handleTabChange = (tab: TabType) => {
    if (tab === "explorer") router.push("/explorer");
    else if (tab === "connectors") router.push("/connectors");
    else if (tab === "quality") router.push("/quality");
    else if (tab === "analysis") router.push("/analysis");
    else if (tab === "chat") router.push("/chat");
    else if (tab === "profile") router.push("/profile");
    else router.push("/");
  };

  // No access token in component state: the credential is an httpOnly cookie the
  // browser attaches itself, and nothing here can (or should) read it.
  const [tenantId, setTenantId] = useState("");
  const [userName, setUserName] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [userRole, setUserRole] = useState("member");
  const [tenantName, setTenantName] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  const [summary, setSummary] = useState<SummaryMetrics>({});
  const [chartLabels, setChartLabels] = useState<string[]>([]);
  const [sleepValues, setSleepValues] = useState<number[]>([]);
  const [readinessValues, setReadinessValues] = useState<number[]>([]);
  const [calorieValues, setCalorieValues] = useState<number[]>([]);
  const [proteinValues, setProteinValues] = useState<number[]>([]);
  const [carbValues, setCarbValues] = useState<number[]>([]);
  const [fatValues, setFatValues] = useState<number[]>([]);

  const [selectedModalConnector, setSelectedModalConnector] = useState<ConnectorItem | undefined>(
    undefined,
  );
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const triggerRefresh = useCallback(() => setRefreshTrigger((prev) => prev + 1), []);

  // Refreshed when the tab comes back into the foreground, and not on a timer.
  //
  // There was a 30s interval here. Nothing on this page changes every 30 seconds:
  // the scheduler checks for due connectors every five minutes, and an import that
  // lands writes history, not a live figure. So the interval mostly re-fetched the
  // same numbers, moved the page under whoever was reading it, and kept a signed-in
  // tab talking to the API all day for nothing.
  //
  // Coming back to the tab is the moment the data might actually be stale, which is
  // why that half stays. A sync you trigger yourself already calls triggerRefresh.
  useEffect(() => {
    if (!isAuthenticated) return;
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") triggerRefresh();
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [isAuthenticated, triggerRefresh]);

  const applySession = useCallback((user: SessionUser) => {
    setTenantId(user.tenantId);
    if (user.name) setUserName(user.name);
    if (user.email) setUserEmail(user.email);
    if (user.role) setUserRole(user.role);
    setTenantName(user.workspaceName);
    setIsAuthenticated(true);
  }, []);

  const resetToSignedOut = useCallback(() => {
    setTenantId("");
    setUserName("");
    setUserEmail("");
    setUserRole("member");
    setTenantName("");
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
        // The guard sent us here from a protected URL but the session turned out
        // to be live after all (the marker cookie can be cleared on its own).
        const returnTo = consumeNextParam();
        if (returnTo) router.replace(returnTo);
      } else {
        resetToSignedOut();
      }
      setMounted(true);
    })();

    return () => {
      cancelled = true;
    };
  }, [API_BASE, applySession, resetToSignedOut, router]);

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
    // Send them where they were originally headed, if the guard recorded it.
    const returnTo = consumeNextParam();
    if (returnTo) router.replace(returnTo);
  };

  const handleLogout = useCallback(async () => {
    // Sign out locally first so the UI cannot keep rendering protected content
    // while the network call is still in flight.
    const signOut = resetToSignedOut;
    let endSessionUrl: string | null = null;
    try {
      endSessionUrl = await endSession(API_BASE);
    } finally {
      signOut();
      if (endSessionUrl) {
        // The user signed in through an identity provider, whose session is
        // still live. A full navigation, not a client route: the next hop is
        // the provider's origin, and it redirects back here afterwards.
        window.location.assign(endSessionUrl);
      } else {
        router.push("/");
      }
    }
  }, [API_BASE, resetToSignedOut, router]);

  const handleOpenConfigureModal = (connector?: ConnectorItem, sourceType?: string) => {
    if (connector) {
      setSelectedModalConnector(connector);
    } else if (sourceType) {
      // A blank stand-in that only carries the chosen type. `id: ""` is what makes
      // `isEditing` false downstream, so this opens as "create a new instance"
      // rather than as an edit of something that does not exist yet.
      setSelectedModalConnector({
        id: "",
        tenant_id: tenantId,
        source_type: sourceType,
        display_name: "",
        status: "active",
        masked_token: "••••••••",
        poll_interval_hours: 6,
        lookback_days: 7,
        lookback_hours: 168,
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

          type Point = { metric_type: string; timestamp: string; value: number };

          /** Daily value for a metric: the day's own total if there is one, else the
           * sum of its per-item readings.
           *
           * Both are canonical names now, so the chain that used to read
           * `"carbohydrates" || "yazio_carbs" || "carbs"` is gone — that fan-out was
           * the dashboard guessing at what the importers might have called things,
           * and two of those three names were never emitted by anything. Legacy rows
           * are still picked up, but through the registry's alias list rather than a
           * hand-kept guess.
           */
          const dailySeries = (dailyKey: string, itemKey?: string) => {
            const dailyNames = [dailyKey, ...(METRIC_CATALOG[dailyKey]?.aliases ?? [])];
            const itemNames = itemKey ? [itemKey, ...(METRIC_CATALOG[itemKey]?.aliases ?? [])] : [];

            return timestamps.map((ts) => {
              const onDay = points.filter((p: Point) => formatDate(p.timestamp) === ts);

              const daily = onDay.find((p: Point) => dailyNames.includes(p.metric_type));
              if (daily) return daily.value || 0;

              // Only when the day has no total of its own: summing both would count
              // every meal twice.
              return onDay
                .filter((p: Point) => itemNames.includes(p.metric_type))
                .reduce((acc: number, p: Point) => acc + (p.value || 0), 0);
            });
          };

          setCalorieValues(dailySeries("nutrition_energy", "nutrition_item_energy"));
          setProteinValues(dailySeries("nutrition_protein"));
          setCarbValues(dailySeries("nutrition_carbohydrates"));
          setFatValues(dailySeries("nutrition_fat"));
          setSleepValues(dailySeries("sleep_duration"));
          setReadinessValues(dailySeries("whoop_recovery_score"));
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
    // Export uploads run here, above every tab and outside every dialog: an archive
    // takes minutes to send, and closing the dialog that started it used to cancel
    // the transfer. `UploadBanner` is what a minimised upload looks like.
    <UploadProvider>
      <div className="min-h-screen bg-slate-200/60 p-2 sm:p-4 lg:p-6 flex items-center justify-center">
        {/* Main Outer App Window Shell */}
        <div className="w-full max-w-[1600px] min-h-[900px] bg-[#f8fafc] rounded-3xl shadow-2xl border border-slate-200/80 flex flex-col md:flex-row overflow-hidden">
          {/* Sidebar Navigation with URL Sync */}
          <Sidebar
            activeTab={activeTab}
            onTabChange={handleTabChange}
            onLogout={handleLogout}
          />

          {/* Main Content Area */}
          <main className="flex-1 p-6 lg:p-8 overflow-y-auto">
            <TopHeader
              userName={userName}
              userEmail={userEmail}
              onOpenConfigureModal={() => handleOpenConfigureModal()}
              onNavigateToProfile={() => handleTabChange("profile")}
              onRefresh={triggerRefresh}
            />

            {/* Configuration and credential problems, on every tab. Previously
              these lived only in a startup log and docs/operations.md. */}
            <SystemWarnings apiBase={API_BASE} />

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
              // Refresh connector data through the prop so an open import dialog
              // survives a visibility refresh.
              <ConnectorsPage
                apiBase={API_BASE}
                tenantId={tenantId}
                refreshTrigger={refreshTrigger}
                onOpenConfigureModal={(c, st) => handleOpenConfigureModal(c, st)}
              />
            )}

            {activeTab === "quality" && <DataQualityTab apiBase={API_BASE} tenantId={tenantId} />}

            {activeTab === "analysis" && (
              <AnalysisTab apiBase={API_BASE} tenantId={tenantId} refreshTrigger={refreshTrigger} />
            )}

            {activeTab === "chat" && <ChatTab apiBase={API_BASE} />}

            {activeTab === "profile" && (
              <ProfileTab
                apiBase={API_BASE}
                tenantId={tenantId}
                userName={userName}
                userEmail={userEmail}
                userRole={userRole}
                tenantName={tenantName}
                onUpdateProfile={(name: string, email: string, workspaceName: string) => {
                  // React state only. These used to be mirrored into localStorage
                  // to survive a reload; the reload now asks /auth/me instead, so
                  // the copy had nothing left reading it.
                  setUserName(name);
                  setUserEmail(email);
                  setTenantName(workspaceName);
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
              // Which instance is being edited. Without it the modal would create a
              // new connector every time, instead of updating the one clicked.
              initialSourceId={selectedModalConnector?.id}
              initialDisplayName={selectedModalConnector?.display_name}
              initialPollInterval={selectedModalConnector?.poll_interval_hours || 6}
              initialLookbackDays={selectedModalConnector?.lookback_days || 7}
              initialLookbackHours={
                selectedModalConnector?.lookback_hours ||
                (selectedModalConnector?.lookback_days
                  ? selectedModalConnector.lookback_days * 24
                  : 168)
              }
              // Which kind of connector this is, so editing one fed by uploads does
              // not silently turn it back into a polled one.
              initialImportMode={selectedModalConnector?.import_mode}
              isEditing={Boolean(selectedModalConnector?.id)}
              tenantId={tenantId}
              onSaved={triggerRefresh}
            />

            <LegalFooter />
          </main>
        </div>

        <UploadBanner />
      </div>
    </UploadProvider>
  );
}
