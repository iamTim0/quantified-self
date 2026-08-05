"use client";

import { useEffect, useState } from "react";
import { BrainCircuit, RefreshCw, Network, Sparkles } from "lucide-react";

type Props = { apiBase: string; token: string; tenantId: string };
type Correlation = { metric_a: string; metric_b: string; coefficient: number; sample_size: number };

const describeStrength = (coefficient: number) => {
  const abs = Math.abs(coefficient);
  if (abs >= 0.8) return { label: "sehr stark", color: "text-emerald-800", bar: "bg-emerald-600" };
  if (abs >= 0.6) return { label: "stark", color: "text-emerald-700", bar: "bg-emerald-500" };
  if (abs >= 0.4) return { label: "moderat", color: "text-amber-700", bar: "bg-amber-500" };
  if (abs >= 0.2) return { label: "niedrig", color: "text-sky-700", bar: "bg-sky-500" };
  return { label: "sehr niedrig", color: "text-slate-500", bar: "bg-slate-300" };
};

export default function AnalysisTab({ apiBase, token, tenantId }: Props) {
  const [correlations, setCorrelations] = useState<Correlation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${apiBase}/api/v1/data/analysis/correlations`, {
      headers: { Authorization: `Bearer ${token}`, "X-Tenant-ID": tenantId },
    })
      .then(async (response) => {
        if (response.ok) setCorrelations((await response.json()).correlations ?? []);
      })
      .finally(() => setLoading(false));
  }, [apiBase, tenantId, token]);

  const strongest = correlations[0];

  return <section className="space-y-6">
    <div className="flex items-end justify-between">
      <div><p className="text-xs font-bold uppercase tracking-widest text-emerald-700">Analysis Center</p><h1 className="text-3xl font-extrabold text-slate-900">Korrelationen</h1><p className="mt-2 text-sm text-slate-500">Pearson-basierte Einordnung gemeinsamer Tagesverläufe. Hinweis: Korrelation ist keine Kausalität.</p></div>
      {loading && <RefreshCw className="h-5 w-5 animate-spin text-emerald-700" />}
    </div>
    <div className="grid gap-4 lg:grid-cols-3">
      <article className="rounded-3xl border border-emerald-200 bg-emerald-50 p-5"><BrainCircuit className="mb-4 h-6 w-6 text-emerald-700"/><p className="text-xs font-bold uppercase tracking-widest text-emerald-700">Top-Signal</p><p className="mt-2 text-sm font-semibold text-slate-800">{strongest ? `${strongest.metric_a} ↔ ${strongest.metric_b}` : "Noch keine stabile Paarung"}</p></article>
      <article className="rounded-3xl border border-slate-200 bg-white p-5"><Network className="mb-4 h-6 w-6 text-slate-700"/><p className="text-xs font-bold uppercase tracking-widest text-slate-500">Einstufung</p><p className="mt-2 text-sm text-slate-600">0.2 niedrig · 0.4 moderat · 0.6 stark · 0.8 sehr stark</p></article>
      <article className="rounded-3xl border border-slate-200 bg-white p-5"><Sparkles className="mb-4 h-6 w-6 text-amber-600"/><p className="text-xs font-bold uppercase tracking-widest text-slate-500">Nächste ML-Schritte</p><p className="mt-2 text-sm text-slate-600">Spearman, Rolling Correlation und leichte Ausreißer-Erkennung ohne DB-Zugriff im Analysis Service.</p></article>
    </div>
    <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-5 flex items-center gap-3"><BrainCircuit className="h-6 w-6 text-emerald-700" /><div><h2 className="font-bold text-slate-900">Korrelationen im eigenen Tab</h2><p className="text-xs text-slate-400">Pearson-Koeffizient · mindestens drei gemeinsame Tage</p></div></div>
      {correlations.length === 0 ? <p className="text-sm text-slate-400">Noch nicht genügend gemeinsame Messwerte für eine Analyse.</p> : <div className="space-y-3">{correlations.map(item => { const strength = describeStrength(item.coefficient); const width = `${Math.round(Math.abs(item.coefficient) * 100)}%`; return <div key={`${item.metric_a}-${item.metric_b}`} className="rounded-2xl border border-slate-100 p-4"><div className="flex items-center justify-between gap-4 text-sm"><span className="font-semibold text-slate-700">{item.metric_a} ↔ {item.metric_b}</span><span className={`shrink-0 font-black ${strength.color}`}>{item.coefficient.toFixed(2)} · {strength.label} · n={item.sample_size}</span></div><div className="mt-3 h-2 rounded-full bg-slate-100"><div className={`h-2 rounded-full ${strength.bar}`} style={{ width }} /></div><p className="mt-2 text-xs text-slate-500">{item.coefficient >= 0 ? "Positiver Zusammenhang: beide Metriken steigen/fallen tendenziell gemeinsam." : "Negativer Zusammenhang: eine Metrik steigt tendenziell, während die andere fällt."}</p></div>})}</div>}
    </article>
  </section>;
}
