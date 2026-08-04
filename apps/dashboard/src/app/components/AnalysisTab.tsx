"use client";

import { useEffect, useState } from "react";
import { BrainCircuit, RefreshCw } from "lucide-react";

type Props = { apiBase: string; token: string; tenantId: string };
type Correlation = { metric_a: string; metric_b: string; coefficient: number; sample_size: number };

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

  return <section className="space-y-6">
    <div className="flex items-end justify-between">
      <div><p className="text-xs font-bold uppercase tracking-widest text-emerald-700">Analysis Center</p><h1 className="text-3xl font-extrabold text-slate-900">Zusammenhänge</h1><p className="mt-2 text-sm text-slate-500">Erkunde, welche Metriken sich gemeinsam verändern.</p></div>
      {loading && <RefreshCw className="h-5 w-5 animate-spin text-emerald-700" />}
    </div>
    <article className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-5 flex items-center gap-3"><BrainCircuit className="h-6 w-6 text-emerald-700" /><div><h2 className="font-bold text-slate-900">Stärkste Korrelationen</h2><p className="text-xs text-slate-400">Pearson-Koeffizient · mindestens drei gemeinsame Tage</p></div></div>
      {correlations.length === 0 ? <p className="text-sm text-slate-400">Noch nicht genügend gemeinsame Messwerte für eine Analyse.</p> : <div className="divide-y divide-slate-100">{correlations.map(item => <div key={`${item.metric_a}-${item.metric_b}`} className="flex items-center justify-between gap-4 py-3 text-sm"><span className="font-medium text-slate-700">{item.metric_a} ↔ {item.metric_b}</span><span className="shrink-0 font-bold text-emerald-700">{item.coefficient.toFixed(2)} · n={item.sample_size}</span></div>)}</div>}
    </article>
  </section>;
}
