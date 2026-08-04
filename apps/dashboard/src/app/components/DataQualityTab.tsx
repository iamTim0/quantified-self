"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, BrainCircuit, CalendarX2, RefreshCw } from "lucide-react";

type Props = { apiBase: string; token: string; tenantId: string };
type Gap = { metric_type: string; missing_dates: string[] };
type Correlation = { metric_a: string; metric_b: string; coefficient: number; sample_size: number };

export default function DataQualityTab({ apiBase, token, tenantId }: Props) {
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [conflicts, setConflicts] = useState<number>(0);
  const [correlations, setCorrelations] = useState<Correlation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const end = new Date();
    const start = new Date(end);
    start.setDate(end.getDate() - 29);
    const headers = { Authorization: `Bearer ${token}`, "X-Tenant-ID": tenantId };
    Promise.all([
      fetch(`${apiBase}/api/v1/data/quality/gaps?start_date=${start.toISOString().slice(0, 10)}&end_date=${end.toISOString().slice(0, 10)}`, { headers }),
      fetch(`${apiBase}/api/v1/data/quality/conflicts`, { headers }),
      fetch(`${apiBase}/api/v1/data/analysis/correlations`, { headers }),
    ]).then(async ([gapResponse, conflictResponse, correlationResponse]) => {
      if (gapResponse.ok) setGaps((await gapResponse.json()).gaps ?? []);
      if (conflictResponse.ok) setConflicts(((await conflictResponse.json()).conflicts ?? []).length);
      if (correlationResponse.ok) setCorrelations((await correlationResponse.json()).correlations ?? []);
    }).finally(() => setLoading(false));
  }, [apiBase, tenantId, token]);

  const cards = [
    { title: "Datenlücken", value: gaps.reduce((sum, gap) => sum + gap.missing_dates.length, 0), icon: CalendarX2, detail: `${gaps.length} Metriken im 30-Tage-Fenster` },
    { title: "Quellkonflikte", value: conflicts, icon: AlertTriangle, detail: "Abweichungen über 5 %" },
    { title: "Korrelationen", value: correlations.length, icon: BrainCircuit, detail: "Mindestens drei gemeinsame Tage" },
  ];

  return <section className="space-y-6">
    <div className="flex items-end justify-between">
      <div><p className="text-xs font-bold uppercase tracking-widest text-emerald-700">Data Quality Center</p><h1 className="text-3xl font-extrabold text-slate-900">Lücken, Konflikte & Insights</h1></div>
      {loading && <RefreshCw className="h-5 w-5 animate-spin text-emerald-700" />}
    </div>
    <div className="grid gap-4 md:grid-cols-3">{cards.map(({ title, value, icon: Icon, detail }) => <article key={title} className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"><Icon className="mb-5 h-6 w-6 text-emerald-700"/><p className="text-sm font-semibold text-slate-500">{title}</p><p className="text-4xl font-black text-slate-900">{value}</p><p className="mt-2 text-xs text-slate-400">{detail}</p></article>)}</div>
    <div className="grid gap-5 lg:grid-cols-2">
      <article className="rounded-3xl border border-slate-200 bg-white p-6"><h2 className="mb-4 font-bold text-slate-900">Größte Datenlücken</h2>{gaps.slice(0, 6).map(gap => <div key={gap.metric_type} className="flex justify-between border-b border-slate-100 py-3 text-sm"><span className="font-medium text-slate-700">{gap.metric_type}</span><span className="font-bold text-amber-600">{gap.missing_dates.length} Tage</span></div>)}</article>
      <article className="rounded-3xl border border-slate-200 bg-white p-6"><h2 className="mb-4 font-bold text-slate-900">Stärkste Zusammenhänge</h2>{correlations.slice(0, 6).map(item => <div key={`${item.metric_a}-${item.metric_b}`} className="flex justify-between border-b border-slate-100 py-3 text-sm"><span className="font-medium text-slate-700">{item.metric_a} ↔ {item.metric_b}</span><span className="font-bold text-emerald-700">{item.coefficient.toFixed(2)} · n={item.sample_size}</span></div>)}</article>
    </div>
  </section>;
}
