"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Cpu, Search } from "lucide-react";
import { useI18n } from "../lib/i18n/provider";
import { plural } from "../lib/i18n/translate";
import { describeMetric } from "../lib/metrics/catalog";

/**
 * Which metrics the chart draws and the raw table shows, as a dropdown.
 *
 * It replaces a flat wall of toggle chips that grew with the tenant's data: with a
 * few dozen metric types stored, the chips filled a scrolling box taller than the
 * chart underneath and the selection was impossible to read at a glance. A closed
 * dropdown states the count, an open one is searchable, and neither pushes the
 * view it belongs to off the screen.
 */
export interface MetricOption {
  /** Canonical `metric_type`, or a namespaced name the registry resolves. */
  key: string;
  /** Points carrying it. From the summary, so it counts the whole history. */
  count: number;
}

interface ExplorerMetricSelectProps {
  options: MetricOption[];
  selected: string[];
  onChange: (next: string[]) => void;
}

export default function ExplorerMetricSelect({
  options,
  selected,
  onChange,
}: ExplorerMetricSelectProps) {
  const { t, locale, formatNumber } = useI18n();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const container = useRef<HTMLDivElement>(null);

  // Closing on an outside click and on Escape both matter: this sits inside a
  // filter bar, so a dropdown left open covers the controls beside it.
  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // Matched against the label *and* the canonical key: the label is what the
  // reader sees, the key is what they would put in an API call, and someone who
  // knows one does not necessarily know the other.
  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return options;
    return options.filter(({ key }) => {
      const { label } = describeMetric(key, locale);
      return key.toLowerCase().includes(needle) || label.toLowerCase().includes(needle);
    });
  }, [options, filter, locale]);

  const toggle = (key: string) => {
    onChange(selected.includes(key) ? selected.filter((item) => item !== key) : [...selected, key]);
  };

  const summary = () => {
    if (selected.length === 0) return t("explorer.metricsNone");
    if (selected.length === 1) return describeMetric(selected[0], locale).label;
    return t(
      plural(selected.length, "explorer.metricsSelected_one", "explorer.metricsSelected_other"),
      { count: formatNumber(selected.length) },
    );
  };

  return (
    <div className="flex items-center gap-2">
      <span className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-400">
        <Cpu className="h-3.5 w-3.5 text-[#0d5c3a]" /> {t("explorer.metrics")}
      </span>

      <div className="relative" ref={container}>
        <button
          type="button"
          onClick={() => setOpen((previous) => !previous)}
          aria-expanded={open}
          aria-haspopup="listbox"
          className="flex sm:min-w-[13rem] items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-bold text-slate-900 outline-none transition-colors hover:border-slate-300 focus-visible:border-[#0d5c3a]"
        >
          <span className="truncate">{summary()}</span>
          <ChevronDown
            className={`h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform ${
              open ? "rotate-180" : ""
            }`}
          />
        </button>

        {open && (
          <div className="absolute left-0 z-30 mt-2 w-80 rounded-2xl border border-slate-200 bg-white shadow-xl">
            <div className="border-b border-slate-100 p-2.5">
              <div className="relative">
                <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-400" />
                <input
                  type="text"
                  autoFocus
                  value={filter}
                  onChange={(event) => setFilter(event.target.value)}
                  placeholder={t("explorer.metricFilterPlaceholder")}
                  className="w-full rounded-xl border border-slate-200 bg-white py-1.5 pl-8 pr-2.5 text-xs text-slate-900 outline-none focus-visible:border-[#0d5c3a]"
                />
              </div>
              <div className="mt-2 flex items-center justify-between px-0.5 text-[11px] font-bold">
                <button
                  type="button"
                  onClick={() => onChange(visible.map(({ key }) => key))}
                  className="text-[#0d5c3a] hover:underline"
                >
                  {t("explorer.selectAll")}
                </button>
                <button
                  type="button"
                  onClick={() => onChange([])}
                  className="text-slate-400 hover:text-slate-900"
                >
                  {t("explorer.clearSelection")}
                </button>
              </div>
            </div>

            <div className="max-h-72 overflow-y-auto p-1.5" role="listbox" aria-multiselectable>
              {options.length === 0 ? (
                <p className="px-2 py-3 text-xs text-slate-400">{t("explorer.metricsEmpty")}</p>
              ) : visible.length === 0 ? (
                <p className="px-2 py-3 text-xs text-slate-400">{t("explorer.metricsNoMatch")}</p>
              ) : (
                visible.map(({ key, count }) => {
                  const isSelected = selected.includes(key);
                  const { label, unit } = describeMetric(key, locale);
                  return (
                    <button
                      type="button"
                      key={key}
                      role="option"
                      aria-selected={isSelected}
                      onClick={() => toggle(key)}
                      className={`flex w-full items-center gap-2.5 rounded-xl px-2 py-1.5 text-left transition-colors ${
                        isSelected ? "bg-emerald-50" : "hover:bg-slate-50"
                      }`}
                    >
                      <span
                        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                          isSelected ? "border-[#0d5c3a] bg-[#0d5c3a]" : "border-slate-300 bg-white"
                        }`}
                      >
                        {isSelected && <Check className="h-3 w-3 text-white" />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-bold text-slate-900">
                          {label}
                          {unit && <span className="ml-1 font-normal text-slate-400">{unit}</span>}
                        </span>
                        {/* The canonical key stays visible: this is the raw-data
                            explorer, so the name an API call needs must be readable
                            without hovering. */}
                        <span className="block truncate font-mono text-[10px] text-slate-400">
                          {key}
                        </span>
                      </span>
                      <span className="shrink-0 rounded-full bg-slate-100 px-1.5 text-[10px] font-bold text-slate-500">
                        {formatNumber(count)}
                      </span>
                    </button>
                  );
                })
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
