import {
  BrainCircuit,
  LayoutDashboard,
  LineChart,
  MessagesSquare,
  Plug,
  ScanSearch,
  User,
  type LucideIcon,
} from "lucide-react";
import type { MessageKey } from "../lib/i18n/provider";

/**
 * The destinations, in one place, because there are two navigations.
 *
 * The sidebar (tablet and up) and the bottom tab bar (phones) each render this.
 * They used to hold their own lists, and a plain array satisfied by any subset
 * meant adding a destination to the sidebar compiled fine while leaving it
 * invisible on every phone — reachable by deep link, highlighted by nothing.
 *
 * `Record<TabType, …>` is what makes that a compile error instead: a new member
 * of the union has to be given a label, an icon and a group before anything
 * builds. `group` is a claim about frequency, not importance — a connector is
 * configured once and read from every day, so it is not worth a thumb position.
 */
export type TabType =
  | "overview"
  | "explorer"
  | "quality"
  | "analysis"
  | "chat"
  | "connectors"
  | "profile";

export interface NavEntry {
  labelKey: MessageKey;
  icon: LucideIcon;
  /** `primary` earns a slot in the phone tab bar; `secondary` lives in "More". */
  group: "primary" | "secondary";
}

export const NAV: Record<TabType, NavEntry> = {
  overview: { labelKey: "sidebar.overview", icon: LayoutDashboard, group: "primary" },
  explorer: { labelKey: "sidebar.explorer", icon: LineChart, group: "primary" },
  analysis: { labelKey: "sidebar.analysis", icon: BrainCircuit, group: "primary" },
  chat: { labelKey: "sidebar.chat", icon: MessagesSquare, group: "primary" },
  quality: { labelKey: "sidebar.quality", icon: ScanSearch, group: "secondary" },
  connectors: { labelKey: "sidebar.connectors", icon: Plug, group: "secondary" },
  profile: { labelKey: "sidebar.settings", icon: User, group: "secondary" },
};

/**
 * Reading order, which is not the same as grouping.
 *
 * `satisfies` rather than a bare annotation, so a destination missing from the
 * order is a compile error while the literal keeps its narrow type.
 */
export const NAV_ORDER = [
  "overview",
  "explorer",
  "quality",
  "analysis",
  "chat",
  "connectors",
  "profile",
] as const satisfies readonly TabType[];

export const PRIMARY_TABS = NAV_ORDER.filter((tab) => NAV[tab].group === "primary");
export const SECONDARY_TABS = NAV_ORDER.filter((tab) => NAV[tab].group === "secondary");
