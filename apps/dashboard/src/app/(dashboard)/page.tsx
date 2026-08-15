"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import OverviewTab from "../components/OverviewTab";
import { SummaryMetrics } from "../components/MetricCards";
import { METRIC_CATALOG } from "../lib/metrics/catalog";
import { apiFetch } from "../lib/api";
import { useShell } from "./shell";

/**
 * The overview, and the only route that loads the overview's data.
 *
 * The two queries below — a whole-history metric summary and a thousand recent
 * points — used to run in the shell, which meant every route paid for them:
 * opening the connector list or the chat ran a full summary aggregation over the
 * tenant's data points server-side, for numbers no visible element used. They
 * belong to the page that draws them.
 */
export default function OverviewPage() {
  const { apiBase, tenantId, refreshTrigger, triggerRefresh, onUnauthorized } = useShell();
  const router = useRouter();

  const [summary, setSummary] = useState<SummaryMetrics>({});
  const [chartLabels, setChartLabels] = useState<string[]>([]);
  const [sleepValues, setSleepValues] = useState<number[]>([]);
  const [readinessValues, setReadinessValues] = useState<number[]>([]);
  const [calorieValues, setCalorieValues] = useState<number[]>([]);
  const [proteinValues, setProteinValues] = useState<number[]>([]);
  const [carbValues, setCarbValues] = useState<number[]>([]);
  const [fatValues, setFatValues] = useState<number[]>([]);

  useEffect(() => {
    if (!tenantId) return;

    let isMounted = true;
    const activeTenant = tenantId;

    async function loadDashboardData() {
      try {
        const [summaryRes, metricsRes] = await Promise.all([
          apiFetch(`${apiBase}/api/v1/data/metrics/summary`, {
            cache: "no-store",
            headers: { "X-Tenant-ID": activeTenant },
          }),
          // Fetch the newest points first so large histories do not hide current data
          // behind the endpoint's result limit. The chart is rendered chronologically below.
          apiFetch(`${apiBase}/api/v1/data/metrics?limit=1000&sort=desc`, {
            cache: "no-store",
            headers: { "X-Tenant-ID": activeTenant },
          }),
        ]);

        // A rejected token means the session is over — do not keep polling with it.
        if ((summaryRes.status === 401 || metricsRes.status === 401) && isMounted) {
          onUnauthorized();
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
  }, [apiBase, tenantId, refreshTrigger, onUnauthorized]);

  return (
    <OverviewTab
      summary={summary}
      chartLabels={chartLabels}
      sleepValues={sleepValues}
      readinessValues={readinessValues}
      calorieValues={calorieValues}
      proteinValues={proteinValues}
      carbValues={carbValues}
      fatValues={fatValues}
      apiBase={apiBase}
      tenantId={tenantId}
      refreshTrigger={refreshTrigger}
      onRefresh={triggerRefresh}
      onNavigateToConnectors={() => router.push("/connectors")}
    />
  );
}
