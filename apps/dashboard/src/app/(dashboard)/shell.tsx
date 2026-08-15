"use client";

import { createContext, useContext } from "react";
import type { ConnectorItem } from "../components/ConnectorsPage";

/**
 * What the persistent dashboard shell offers the page rendered inside it.
 *
 * The shell lives in `layout.tsx`, which the App Router keeps mounted across
 * navigations; the pages are what change. Anything a page needs that the shell
 * already knows — who is signed in, which API to talk to, when data was last
 * asked to refresh — travels through here rather than being fetched again per
 * route, because fetching it again per route is what made every menu click cost
 * a session check, a warning query and a full metric summary.
 */
export interface ShellValue {
  apiBase: string;
  tenantId: string;
  userName: string;
  userEmail: string;
  userRole: string;
  tenantName: string;
  /** Bumped when something asks the visible page to reload its data. */
  refreshTrigger: number;
  triggerRefresh: () => void;
  /** Opens the connector dialog, for an existing instance or a new one of a type. */
  openConfigureModal: (connector?: ConnectorItem, sourceType?: string) => void;
  /** A page saved the profile; keep the header and sidebar in step. */
  applyProfileUpdate: (name: string, email: string, workspaceName: string) => void;
  /** Ends the session, including the identity provider's where there is one. */
  logout: () => Promise<void>;
  /** A 401 that survived `apiFetch`'s refresh: the session is over. */
  onUnauthorized: () => void;
}

const ShellContext = createContext<ShellValue | null>(null);

export const ShellProvider = ShellContext.Provider;

export function useShell(): ShellValue {
  const value = useContext(ShellContext);
  if (!value) {
    throw new Error("useShell was called outside the dashboard layout");
  }
  return value;
}
