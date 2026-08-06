"use client";

import React, { useState } from "react";
import { Activity, Lock, Mail, User, ArrowRight, AlertCircle } from "lucide-react";

export interface UserAuthData {
  token: string;
  /** Opaque rotating refresh token; absent only if the server did not issue one. */
  refreshToken: string | null;
  tenantId: string;
  userName: string;
  userEmail: string;
  userRole: string;
  tenantName: string;
}

interface AuthScreenProps {
  apiBase: string;
  onLogin: (data: UserAuthData) => void;
}

export default function AuthScreen({ apiBase, onLogin }: AuthScreenProps) {
  const [isLogin, setIsLogin] = useState(true);
  const [allowRegistration, setAllowRegistration] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  React.useEffect(() => {
    fetch(`${apiBase}/api/v1/auth/config`)
      .then((res) => res.json())
      .then((data) => {
        if (typeof data.allow_registration === "boolean") {
          setAllowRegistration(data.allow_registration);
          if (!data.allow_registration) {
            setIsLogin(true);
          }
        }
      })
      .catch(() => {});
  }, [apiBase]);

  const formatErrorMessage = (detail: unknown): string => {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return JSON.stringify(item);
        })
        .join("; ");
    }
    if (detail && typeof detail === "object") {
      if ("msg" in detail) return String((detail as { msg: unknown }).msg);
      return JSON.stringify(detail);
    }
    return "Authentifizierung fehlgeschlagen";
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    const endpoint = isLogin ? "/api/v1/auth/login" : "/api/v1/auth/signup";
    const body = isLogin 
      ? { email, password }
      : { email, password, name };

    try {
      const res = await fetch(`${apiBase}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(formatErrorMessage(data.detail));
      }

      if (isLogin) {
        onLogin({
          token: data.access_token,
          refreshToken: data.refresh_token ?? null,
          tenantId: data.tenant_id,
          userName: data.name || email.split("@")[0],
          userEmail: data.email || email,
          userRole: data.role || "owner",
          tenantName: `${data.name || email.split("@")[0]}'s Workspace`,
        });
      } else {
        const loginRes = await fetch(`${apiBase}/api/v1/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        const loginData = await loginRes.json();
        if (!loginRes.ok) {
          throw new Error(formatErrorMessage(loginData.detail));
        }

        onLogin({
          token: loginData.access_token,
          refreshToken: loginData.refresh_token ?? null,
          tenantId: loginData.tenant_id,
          userName: loginData.name || name,
          userEmail: loginData.email || email,
          userRole: loginData.role || "owner",
          tenantName: `${loginData.name || name}'s Workspace`,
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const isAlreadyRegistered = error.toLowerCase().includes("already registered") || error.toLowerCase().includes("bereits registriert");

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col justify-center items-center p-4 relative overflow-hidden">
      {/* Background Orbs */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-emerald-500/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-teal-500/10 rounded-full blur-[120px] pointer-events-none" />

      <div className="z-10 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center p-3.5 rounded-3xl bg-[#0d5c3a] text-white mb-4 shadow-xl shadow-[#0d5c3a]/20">
            <Activity className="w-8 h-8" />
          </div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Quantified Self</h1>
          <p className="text-slate-500 text-xs mt-1.5 font-medium">Deine persönliche Gesundheits- & Analytics-Plattform.</p>
        </div>

        <div className="glass-card bg-white border border-slate-200/80 rounded-3xl p-8 shadow-xl">
          <h2 className="text-xl font-extrabold text-slate-900 mb-6">
            {isLogin ? "Willkommen zurück" : "Konto erstellen"}
          </h2>
          
          {error && (
            <div role="alert" className="mb-4 p-3 rounded-2xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium space-y-1">
              <div className="flex items-center gap-1.5 font-bold">
                <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
                <span>{error}</span>
              </div>
              {isAlreadyRegistered && (
                <button
                  type="button"
                  onClick={() => {
                    setIsLogin(true);
                    setError("");
                  }}
                  className="mt-1 text-xs font-bold text-[#0d5c3a] hover:underline block"
                >
                  ➜ Hier klicken, um dich direkt mit dieser E-Mail anzumelden.
                </button>
              )}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {!isLogin && (
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">Name</label>
                <div className="relative">
                  <User className="absolute left-3.5 top-3 w-4 h-4 text-slate-400" />
                  <input 
                    type="text" 
                    value={name}
                    onChange={e => setName(e.target.value)}
                    required 
                    className="w-full bg-white border border-slate-200 rounded-2xl py-2.5 pl-10 pr-4 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                    placeholder="Jane Doe"
                  />
                </div>
              </div>
            )}
            
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">E-Mail</label>
              <div className="relative">
                <Mail className="absolute left-3.5 top-3 w-4 h-4 text-slate-400" />
                <input 
                  type="email" 
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required 
                  className="w-full bg-white border border-slate-200 rounded-2xl py-2.5 pl-10 pr-4 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                  placeholder="you@example.com"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">Passwort</label>
              <div className="relative">
                <Lock className="absolute left-3.5 top-3 w-4 h-4 text-slate-400" />
                <input 
                  type="password" 
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required 
                  className="w-full bg-white border border-slate-200 rounded-2xl py-2.5 pl-10 pr-4 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                  placeholder="••••••••"
                />
              </div>
            </div>

            <button 
              type="submit" 
              disabled={loading}
              className="w-full bg-[#0d5c3a] hover:bg-[#08432a] text-white font-bold rounded-2xl py-3 px-4 mt-2 transition-all flex items-center justify-center gap-2 group disabled:opacity-50 shadow-md shadow-[#0d5c3a]/20"
            >
              {loading ? "Bitte warten..." : isLogin ? "Anmelden" : "Konto Registrieren"}
              {!loading && <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />}
            </button>
          </form>

          <div className="mt-6 text-center text-xs font-medium space-y-2">
            {allowRegistration ? (
              <div>
                <span className="text-slate-500">
                  {isLogin ? "Noch kein Konto?" : "Bereits registriert?"}
                </span>
                <button 
                  onClick={() => { setIsLogin(!isLogin); setError(""); }}
                  className="ml-2 text-[#0d5c3a] hover:underline font-bold transition-colors"
                >
                  {isLogin ? "Jetzt Registrieren" : "Hier Anmelden"}
                </button>
              </div>
            ) : (
              <div className="text-slate-400 text-xs italic">
                Neuregistrierung vom Administrator deaktiviert.
              </div>
            )}
            <div>
              <a href="/privacy" className="text-slate-400 hover:text-slate-600 transition-colors underline">
                Datenschutzerklärung
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
