"use client";

import React, { useState } from "react";
import { Lock, Mail, User, ArrowRight, Activity } from "lucide-react";

interface AuthScreenProps {
  onLogin: (token: string, tenantId: string) => void;
  apiBase: string;
}

export default function AuthScreen({ onLogin, apiBase }: AuthScreenProps) {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

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
        throw new Error(data.detail || "Authentication failed");
      }

      if (isLogin) {
        onLogin(data.access_token, data.tenant_id);
      } else {
        // Automatically login after signup
        const loginRes = await fetch(`${apiBase}/api/v1/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        const loginData = await loginRes.json();
        if (!loginRes.ok) throw new Error(loginData.detail);
        onLogin(loginData.access_token, loginData.tenant_id);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-neutral-950 flex flex-col justify-center items-center p-4 relative overflow-hidden">
      {/* Dynamic Background Elements */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-purple-600/20 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-blue-600/20 rounded-full blur-[120px] pointer-events-none" />

      <div className="z-10 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center p-3 rounded-2xl bg-neutral-900 border border-neutral-800 mb-4 shadow-xl">
            <Activity className="w-8 h-8 text-purple-400" />
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Quantified Self</h1>
          <p className="text-neutral-400 mt-2">Unlock your personal data insights.</p>
        </div>

        <div className="bg-neutral-900/50 backdrop-blur-xl border border-neutral-800/50 rounded-2xl p-8 shadow-2xl">
          <h2 className="text-xl font-semibold text-white mb-6">
            {isLogin ? "Welcome back" : "Create your account"}
          </h2>
          
          {error && (
            <div className="mb-4 p-3 rounded-lg bg-red-900/30 border border-red-900/50 text-red-400 text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {!isLogin && (
              <div>
                <label className="block text-sm font-medium text-neutral-400 mb-1">Name</label>
                <div className="relative">
                  <User className="absolute left-3 top-3 w-5 h-5 text-neutral-500" />
                  <input 
                    type="text" 
                    value={name}
                    onChange={e => setName(e.target.value)}
                    required 
                    className="w-full bg-neutral-950 border border-neutral-800 rounded-xl py-2.5 pl-10 pr-4 text-white placeholder-neutral-500 focus:outline-none focus:ring-2 focus:ring-purple-500/50 focus:border-purple-500 transition-all"
                    placeholder="Jane Doe"
                  />
                </div>
              </div>
            )}
            
            <div>
              <label className="block text-sm font-medium text-neutral-400 mb-1">Email</label>
              <div className="relative">
                <Mail className="absolute left-3 top-3 w-5 h-5 text-neutral-500" />
                <input 
                  type="email" 
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required 
                  className="w-full bg-neutral-950 border border-neutral-800 rounded-xl py-2.5 pl-10 pr-4 text-white placeholder-neutral-500 focus:outline-none focus:ring-2 focus:ring-purple-500/50 focus:border-purple-500 transition-all"
                  placeholder="you@example.com"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-neutral-400 mb-1">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-3 w-5 h-5 text-neutral-500" />
                <input 
                  type="password" 
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required 
                  className="w-full bg-neutral-950 border border-neutral-800 rounded-xl py-2.5 pl-10 pr-4 text-white placeholder-neutral-500 focus:outline-none focus:ring-2 focus:ring-purple-500/50 focus:border-purple-500 transition-all"
                  placeholder="••••••••"
                />
              </div>
            </div>

            <button 
              type="submit" 
              disabled={loading}
              className="w-full bg-white hover:bg-neutral-200 text-black font-semibold rounded-xl py-2.5 px-4 mt-2 transition-all flex items-center justify-center gap-2 group disabled:opacity-50"
            >
              {loading ? "Please wait..." : isLogin ? "Sign In" : "Sign Up"}
              {!loading && <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />}
            </button>
          </form>

          <div className="mt-6 text-center text-sm">
            <span className="text-neutral-500">
              {isLogin ? "Don't have an account?" : "Already have an account?"}
            </span>
            <button 
              onClick={() => { setIsLogin(!isLogin); setError(""); }}
              className="ml-2 text-purple-400 hover:text-purple-300 font-medium transition-colors"
            >
              {isLogin ? "Sign up" : "Sign in"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
