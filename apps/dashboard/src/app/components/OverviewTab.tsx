"use client";

import React, { useState, useEffect } from "react";
import dynamic from "next/dynamic";
import MetricCards, { SummaryMetrics } from "./MetricCards";
import { RefreshCw, Calendar, CheckCircle2, Play, Pause, ArrowUpRight, Zap, Plug } from "lucide-react";

const TrendChart = dynamic(() => import("./TrendChart"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-80 rounded-3xl border border-slate-200 bg-white p-6 flex items-center justify-center text-xs text-slate-400">
      Lade Analytics Diagramm...
    </div>
  ),
});

interface OverviewTabProps {
  summary: SummaryMetrics;
  chartLabels: string[];
  sleepValues: number[];
  readinessValues: number[];
  calorieValues?: number[];
  proteinValues?: number[];
  carbValues?: number[];
  fatValues?: number[];
  onRefresh: () => void;
  onNavigateToConnectors: () => void;
}

export default function OverviewTab({
  summary,
  chartLabels,
  sleepValues,
  readinessValues,
  calorieValues = [],
  proteinValues = [],
  carbValues = [],
  fatValues = [],
  onRefresh,
  onNavigateToConnectors,
}: OverviewTabProps) {
  const hasData = Object.keys(summary).length > 0 || chartLabels.length > 0;
  const [timerSeconds, setTimerSeconds] = useState(5048); // Live tracker demo
  const [isRunning, setIsRunning] = useState(true);

  useEffect(() => {
    if (!isRunning) return;
    const interval = setInterval(() => {
      setTimerSeconds((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [isRunning]);

  const formatTimer = (totalSecs: number) => {
    const hrs = String(Math.floor(totalSecs / 3600)).padStart(2, "0");
    const mins = String(Math.floor((totalSecs % 3600) / 60)).padStart(2, "0");
    const secs = String(totalSecs % 60).padStart(2, "0");
    return `${hrs}:${mins}:${secs}`;
  };

  const todayFormatted = new Date().toLocaleDateString("de-DE", {
    weekday: "long",
    day: "2-digit",
    month: "long",
    year: "numeric",
  });

  return (
    <div className="space-y-6">
      {/* Hero Title & Actions Header (Reference Image Style) */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-2">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Dashboard</h1>
          <p className="text-xs text-slate-500 mt-1">
            Aggregierte Echtzeit-Analysen deiner verbundenen Sensoren und Ernährungs-Tracker.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-800 bg-emerald-50 border border-emerald-200/80 px-3 py-2 rounded-2xl">
            <Calendar className="w-3.5 h-3.5 text-[#0d5c3a]" />
            <span>{todayFormatted}</span>
          </span>
          <button
            onClick={onRefresh}
            className="flex items-center gap-2 text-xs font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 px-3.5 py-2 rounded-2xl shadow-sm transition-all"
          >
            <RefreshCw className="w-3.5 h-3.5 text-slate-500" />
            <span>Aktualisieren</span>
          </button>
        </div>
      </div>

      {/* Top 4 Hero Stat Cards */}
      <MetricCards metrics={summary} />

      {/* Middle Layout Grid: Chart (Span 2) + Right Side Cards (Span 1) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Chart Column */}
        <div className="lg:col-span-2">
          {hasData ? (
            <TrendChart
              labels={chartLabels}
              sleepValues={sleepValues}
              readinessValues={readinessValues}
              calorieValues={calorieValues}
              proteinValues={proteinValues}
              carbValues={carbValues}
              fatValues={fatValues}
              onRefresh={onRefresh}
            />
          ) : (
            <div className="glass-card p-10 text-center bg-white border border-slate-200 rounded-3xl">
              <p className="text-sm font-medium text-slate-500 mb-4">Noch keine Datenpunkte in PostgreSQL vorhanden.</p>
              <button
                onClick={onNavigateToConnectors}
                className="px-5 py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all shadow-md shadow-[#0d5c3a]/20"
              >
                Connectoren verknüpfen & Daten importieren
              </button>
            </div>
          )}
        </div>

        {/* Right Side Widgets (Reference Image Style) */}
        <div className="space-y-6">
          {/* Quick Reminders / Status Card */}
          <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl">
            <div className="flex justify-between items-center mb-3">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Automatisch Sync</span>
              <Zap className="w-4 h-4 text-amber-500" />
            </div>
            <h3 className="text-base font-extrabold text-slate-900 mb-1">
              Yazio & Sensor Ingestion
            </h3>
            <p className="text-xs text-slate-500 mb-4 leading-relaxed">
              NATS JetStream Ingestion Broker läuft aktiv im Hintergrund.
            </p>
            <button
              onClick={onRefresh}
              className="w-full py-2.5 px-4 rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white font-bold text-xs flex items-center justify-center gap-2 transition-all shadow-md shadow-[#0d5c3a]/20"
            >
              <Zap className="w-3.5 h-3.5" />
              <span>Jetzt Synchronisieren</span>
            </button>
          </div>

          {/* Active Connectors Summary Card */}
          <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900">Verbundene Tracker</h3>
              <button
                onClick={onNavigateToConnectors}
                className="text-[11px] font-bold text-[#0d5c3a] hover:underline flex items-center gap-0.5"
              >
                <span>Alle</span>
                <ArrowUpRight className="w-3 h-3" />
              </button>
            </div>

            <div className="space-y-3">
              {[
                { name: "Yazio Nutrition", status: "Aktiv", color: "bg-emerald-500", date: "Vor 10 Min." },
                { name: "Oura Ring Gen3", status: "Aktiv", color: "bg-emerald-500", date: "Heute 08:30" },
                { name: "Apple Health", status: "Bereit", color: "bg-blue-500", date: "Standby" },
              ].map((conn) => (
                <div
                  key={conn.name}
                  className="flex items-center justify-between p-3 rounded-2xl bg-slate-50 border border-slate-100"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-xl bg-white border border-slate-200 flex items-center justify-center text-slate-700 shadow-xs">
                      <Plug className="w-4 h-4 text-[#0d5c3a]" />
                    </div>
                    <div>
                      <div className="text-xs font-bold text-slate-800">{conn.name}</div>
                      <div className="text-[10px] text-slate-400">{conn.date}</div>
                    </div>
                  </div>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200">
                    {conn.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Layout Row: Breakdown List + Goal Gauge + Live Timer (Reference Image Style) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-2">
        {/* Widget 1: Team / Data Breakdown List */}
        <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900">Letzte Datenpunkte</h3>
            <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full">
              PostgreSQL Live
            </span>
          </div>

          <div className="space-y-3">
            {[
              { item: "Mittagessen (Hähnchen & Reis)", type: "Kalorien", detail: "+ 680 kcal", status: "Ingested" },
              { item: "Abendessen (Protein Shake)", type: "Protein", detail: "+ 45g Protein", status: "Ingested" },
              { item: "Snack (Edamame Bohnen)", type: "Mikros", detail: "+ 387 kcal", status: "Ingested" },
            ].map((row, i) => (
              <div key={i} className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0">
                <div>
                  <div className="text-xs font-bold text-slate-800">{row.item}</div>
                  <div className="text-[10px] text-slate-400">{row.type}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs font-mono font-bold text-[#0d5c3a]">{row.detail}</div>
                  <span className="text-[9px] font-semibold text-emerald-600">✓ {row.status}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Widget 2: Semi-Circle Progress Gauge (Reference Image 41% Gauge Style) */}
        <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl flex flex-col justify-between">
          <div className="flex justify-between items-center mb-2">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900">Tagesziel Kalorien</h3>
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
          </div>

          <div className="flex flex-col items-center justify-center my-4">
            <div className="relative w-36 h-20 flex items-end justify-center">
              {/* Semi-circle SVG Gauge */}
              <svg className="w-36 h-36 -rotate-90 transform" viewBox="0 0 100 100">
                <circle
                  cx="50"
                  cy="50"
                  r="40"
                  stroke="#e2e8f0"
                  strokeWidth="10"
                  fill="transparent"
                  strokeDasharray="125 125"
                  strokeLinecap="round"
                />
                <circle
                  cx="50"
                  cy="50"
                  r="40"
                  stroke="#0d5c3a"
                  strokeWidth="10"
                  fill="transparent"
                  strokeDasharray="100 125"
                  strokeLinecap="round"
                />
              </svg>
              <div className="absolute bottom-0 text-center">
                <div className="text-3xl font-extrabold text-slate-900 leading-none">82%</div>
                <div className="text-[10px] font-medium text-slate-400 mt-0.5">Erreicht</div>
              </div>
            </div>
          </div>

          <div className="flex justify-around text-center border-t border-slate-100 pt-3">
            <div>
              <div className="text-[10px] text-slate-400 font-semibold">Ziel</div>
              <div className="text-xs font-bold text-slate-800 font-mono">2.200 kcal</div>
            </div>
            <div>
              <div className="text-[10px] text-slate-400 font-semibold">Erfasst</div>
              <div className="text-xs font-bold text-[#0d5c3a] font-mono">1.805 kcal</div>
            </div>
          </div>
        </div>

        {/* Widget 3: Live Time Tracker Widget (Reference Image Dark Green Style) */}
        <div className="dark-emerald-card p-6 rounded-3xl flex flex-col justify-between relative overflow-hidden">
          <div className="flex justify-between items-center mb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-emerald-200">
              Live Ingestion Clock
            </span>
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
          </div>

          <div className="my-6">
            <div className="text-4xl font-extrabold text-white tracking-tight font-mono">
              {formatTimer(timerSeconds)}
            </div>
            <div className="text-[11px] text-emerald-200/80 mt-1">
              Aktiver NATS Event Consumer Status: Running
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setIsRunning(!isRunning)}
              className="w-10 h-10 rounded-full bg-white text-slate-950 flex items-center justify-center hover:bg-emerald-100 transition-colors shadow-md"
            >
              {isRunning ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
            </button>
            <div className="text-xs font-semibold text-emerald-100">
              {isRunning ? "Laufende Überwachung" : "Pausiert"}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
