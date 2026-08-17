"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar, { TabType } from "../components/Sidebar";
import { TAB_PATHS } from "../components/navigation";
import MobileTabBar from "../components/MobileTabBar";
import TopHeader from "../components/TopHeader";
import ConnectorModal from "../components/ConnectorModal";
import { ConnectorItem } from "../components/ConnectorsPage";
import AuthScreen, { UserAuthData } from "../components/AuthScreen";
import LegalFooter from "../components/LegalFooter";
import SystemWarnings from "../components/SystemWarnings";
import UploadBanner from "../components/UploadBanner";
import { UploadProvider } from "../lib/uploads/provider";
import { useT } from "../lib/i18n/provider";
import { SessionUser, endSession, fetchSession } from "../lib/session";
import { ShellProvider } from "./shell";

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
 * layout wraps every dashboard route, and a `useSearchParams` call in it would
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

/**
 * The application shell: sidebar, header, warnings, connector dialog.
 *
 * This is a **layout** rather than a page, and that is the whole point. Every
 * dashboard route used to be its own page component rendering the same shell, so
 * moving between two menu entries unmounted the entire tree and built it again:
 * a fresh session check, a fresh warning query, a fresh metric summary and a
 * fresh thousand-point metric query, on every click, whether or not the tab the
 * user landed on had any use for them. The App Router keeps a layout mounted
 * across navigations within its segment — so this now runs once per session, and
 * a page loads only what that page shows.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const t = useT();
  const API_BASE = getApiBase();
  const [mounted, setMounted] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  const getTabFromPathname = (path: string): TabType => {
    // Match the detail routes too, so the parent tab stays lit while a session
    // or connector is open. The explicit root check avoids every path matching
    // the overview prefix.
    if (path === "/" || path === "/dashboard") return "overview";
    const match = (Object.entries(TAB_PATHS) as Array<[TabType, string]>).find(
      ([tab, target]) => tab !== "overview" && (path === target || path.startsWith(`${target}/`)),
    );
    if (match) return match[0];
    if (path.startsWith("/settings")) return "profile";
    return "overview";
  };

  const activeTab = getTabFromPathname(pathname);

  const handleTabChange = useCallback(
    (tab: TabType) => {
      router.push(TAB_PATHS[tab]);
    },
    [router],
  );

  // No access token in component state: the credential is an httpOnly cookie the
  // browser attaches itself, and nothing here can (or should) read it.
  const [tenantId, setTenantId] = useState("");
  const [userName, setUserName] = useState("");
  const [userEmail, setUserEmail] = useState("");
  const [userRole, setUserRole] = useState("member");
  const [tenantName, setTenantName] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  const [selectedModalConnector, setSelectedModalConnector] = useState<ConnectorItem | undefined>(
    undefined,
  );
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const triggerRefresh = useCallback(() => setRefreshTrigger((prev) => prev + 1), []);

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

  // Coming back to the tab does two things, in one listener and in this order.
  //
  // There were two listeners here, registered separately on the same event: one
  // re-checked the session, the other re-fetched every child. Returning to the
  // tab therefore fired a round trip *and* a full refresh with no ordering
  // between them, so a signed-out tab spent a page's worth of requests before
  // finding out it was signed out. Confirm first, then refresh.
  //
  // Logging out in one tab must sign the others out too: the cookie is shared
  // across tabs but its removal fires no event, so a tab that regains focus
  // re-checks with the server rather than trusting what it last rendered.
  //
  // Not on a timer. There was a 30s interval here once, and nothing on this page
  // changes every 30 seconds — the scheduler checks for due connectors every
  // five minutes, and an import that lands writes history, not a live figure. So
  // it mostly re-fetched the same numbers and moved the page under whoever was
  // reading it. Regaining focus is the moment the data might actually be stale.
  useEffect(() => {
    if (!isAuthenticated) return;
    const onVisible = async () => {
      if (document.visibilityState !== "visible") return;
      const user = await fetchSession(API_BASE);
      if (!user) {
        resetToSignedOut();
        return;
      }
      triggerRefresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [API_BASE, isAuthenticated, resetToSignedOut, triggerRefresh]);

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

  const handleOpenConfigureModal = useCallback(
    (connector?: ConnectorItem, sourceType?: string) => {
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
    },
    [tenantId],
  );

  const applyProfileUpdate = useCallback((name: string, email: string, workspaceName: string) => {
    // React state only. These used to be mirrored into localStorage to survive a
    // reload; the reload now asks /auth/me instead, so the copy had nothing left
    // reading it.
    setUserName(name);
    setUserEmail(email);
    setTenantName(workspaceName);
  }, []);

  const shellValue = useMemo(
    () => ({
      apiBase: API_BASE,
      tenantId,
      userName,
      userEmail,
      userRole,
      tenantName,
      refreshTrigger,
      triggerRefresh,
      openConfigureModal: handleOpenConfigureModal,
      applyProfileUpdate,
      logout: handleLogout,
      onUnauthorized: resetToSignedOut,
    }),
    [
      API_BASE,
      tenantId,
      userName,
      userEmail,
      userRole,
      tenantName,
      refreshTrigger,
      triggerRefresh,
      handleOpenConfigureModal,
      applyProfileUpdate,
      handleLogout,
      resetToSignedOut,
    ],
  );

  // The shell, drawn before we know whether anyone is signed in.
  //
  // This was a bare grey rectangle, and it covered a longer stretch than it
  // looks: download the JS, hydrate, *then* an effect fires `fetchSession()` and
  // a round trip has to come back before `mounted` flips. Everything up to that
  // point rendered nothing at all, and then the entire page appeared at once.
  //
  // Painting the frame — the window, the sidebar's footprint, the header's — is
  // most of the perceived fix, and it costs nothing: the layout is fixed and
  // known before any data is. It also removes the layout shift, because the real
  // shell drops into the space this one already occupies rather than replacing
  // an empty box.
  //
  // Deliberately not the children: they need a tenant, and a signed-out visitor
  // must not see even the outline of a workspace.
  if (!mounted) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-200/60 p-0 sm:p-4 lg:p-6">
        <div
          className="flex w-full max-w-[1600px] flex-col overflow-hidden border-slate-200/80 bg-[#f8fafc] shadow-2xl sm:min-h-[900px] sm:rounded-3xl sm:border md:flex-row"
          // A frame, not a claim about content. Nothing here is real yet, so
          // nothing here should be announced.
          aria-hidden="true"
        >
          <div className="hidden w-64 shrink-0 border-r border-slate-200/80 bg-white md:block" />
          <div className="flex-1 p-4 sm:px-6 sm:pt-6 md:p-6 lg:p-8">
            <div className="h-10 w-56 rounded-xl bg-slate-200/70" />
          </div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <AuthScreen onLogin={handleLogin} apiBase={API_BASE} />;
  }

  return (
    // Export uploads run here, above every tab and outside every dialog: an archive
    // takes minutes to send, and closing the dialog that started it used to cancel
    // the transfer. `UploadBanner` is what a minimised upload looks like.
    <UploadProvider>
      <ShellProvider value={shellValue}>
        {/*
          Past the sidebar in one keystroke (WCAG 2.4.1).
          Seven navigation targets sit before the content of every page, and a
          keyboard or screen-reader user re-traversed all of them on every
          navigation. Visually hidden until focused, which is the whole
          convention: it is the first thing Tab reaches and invisible to
          everyone who never presses it.
        */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-100 focus:rounded-xl focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-bold focus:text-slate-900 focus:shadow-lg focus:outline-2 focus:outline-[#0d5c3a]"
        >
          {t("nav.skipToContent")}
        </a>
        <div className="flex min-h-screen items-center justify-center bg-slate-200/60 p-0 sm:p-4 lg:p-6">
          {/* Main Outer App Window Shell */}
          <div className="flex w-full max-w-[1600px] flex-col overflow-hidden border-slate-200/80 bg-[#f8fafc] shadow-2xl sm:min-h-[900px] sm:rounded-3xl sm:border md:flex-row">
            {/* Sidebar Navigation with URL Sync. Hidden on phones, where a
                column of icons sits outside the thumb's reach — `MobileTabBar`
                takes over below `md`. */}
            <div className="hidden md:flex">
              <Sidebar
                activeTab={activeTab}
                onTabChange={handleTabChange}
                onLogout={handleLogout}
              />
            </div>

            {/* Main Content Area. The bottom padding on small screens is the tab
                bar's height plus the home-indicator inset: without it the last
                element of every page is unreachable behind the bar. */}
            <main
              id="main-content"
              tabIndex={-1}
              className="min-w-0 flex-1 overflow-y-auto p-4 pb-[calc(6rem+env(safe-area-inset-bottom))] sm:px-6 sm:pt-6 md:p-6 md:pb-6 lg:p-8"
            >
              <TopHeader
                userName={userName}
                userEmail={userEmail}
                onOpenConfigureModal={() => handleOpenConfigureModal()}
                onNavigateToProfile={() => handleTabChange("profile")}
                onRefresh={triggerRefresh}
              />

              {/* Configuration and credential problems, on every tab. Previously
                these lived only in a startup log and docs/operations.md. */}
              <SystemWarnings apiBase={API_BASE} userRole={userRole} />

              {children}

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

          <MobileTabBar
            activeTab={activeTab}
            onTabChange={handleTabChange}
            onLogout={handleLogout}
          />
        </div>
      </ShellProvider>
    </UploadProvider>
  );
}
