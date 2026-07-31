"use client";

import React, { useState } from "react";
import {
  User,
  Shield,
  Key,
  Copy,
  Check,
  Building,
  Mail,
  Lock,
  Database,
  LogOut,
  RefreshCw,
  Flame,
  CheckCircle2,
  AlertCircle,
  HardDrive
} from "lucide-react";

interface ProfileTabProps {
  apiBase: string;
  token: string;
  tenantId: string;
  userName: string;
  userEmail: string;
  userRole: string;
  tenantName: string;
  onUpdateProfile: (name: string, email: string) => void;
  onLogout: () => void;
}

export default function ProfileTab({
  apiBase,
  token,
  tenantId,
  userName,
  userEmail,
  userRole,
  tenantName,
  onUpdateProfile,
  onLogout,
}: ProfileTabProps) {
  const [nameInput, setNameInput] = useState(userName);
  const [emailInput, setEmailInput] = useState(userEmail);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [copiedTenantId, setCopiedTenantId] = useState(false);
  const [copiedToken, setCopiedToken] = useState(false);

  const getInitials = (name: string) => {
    if (!name) return "QS";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return name.slice(0, 2).toUpperCase();
  };

  const handleCopy = (text: string, setCopied: (v: boolean) => void) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSaveProfile = (e: React.FormEvent) => {
    e.preventDefault();
    onUpdateProfile(nameInput.trim(), emailInput.trim());
    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 2500);
  };

  // Decode mock or actual JWT token payload safely
  const parseJwtPayload = (jwtToken: string) => {
    try {
      const parts = jwtToken.split(".");
      if (parts.length === 3) {
        const payload = JSON.parse(atob(parts[1]));
        return payload;
      }
    } catch {
      // Fallback
    }
    return {
      sub: "user_owner_001",
      tenant_id: tenantId,
      role: userRole,
      exp: "2026-08-30T00:00:00Z",
    };
  };

  const jwtPayload = parseJwtPayload(token);

  return (
    <div className="max-w-5xl mx-auto space-y-8 animate-in fade-in duration-200">
      {/* Header Banner */}
      <div className="relative rounded-3xl border border-neutral-800 bg-gradient-to-r from-purple-900/40 via-neutral-900/90 to-blue-900/40 p-8 backdrop-blur-xl shadow-2xl overflow-hidden">
        <div className="absolute top-0 right-0 p-8 opacity-10 pointer-events-none">
          <Shield className="w-64 h-64 text-purple-400" />
        </div>

        <div className="relative flex flex-col sm:flex-row items-center sm:items-start gap-6">
          {/* Avatar Circle */}
          <div className="w-24 h-24 rounded-3xl bg-gradient-to-br from-purple-500 via-indigo-600 to-blue-600 flex items-center justify-center text-white text-2xl font-black shadow-xl shadow-purple-500/25 border border-white/20 shrink-0">
            {getInitials(userName)}
          </div>

          <div className="space-y-2 text-center sm:text-left flex-1">
            <div className="flex flex-wrap items-center justify-center sm:justify-start gap-2">
              <h2 className="text-2xl font-bold text-white">{userName}</h2>
              <span className="px-2.5 py-0.5 rounded-full bg-purple-500/20 border border-purple-500/30 text-purple-300 text-xs font-bold uppercase tracking-wider">
                {userRole}
              </span>
              <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-bold uppercase tracking-wider flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> Tenant Isoliert
              </span>
            </div>

            <p className="text-sm text-neutral-400 flex items-center justify-center sm:justify-start gap-1.5">
              <Mail className="w-4 h-4 text-purple-400" />
              <span>{userEmail}</span>
            </p>

            <div className="flex flex-wrap items-center justify-center sm:justify-start gap-4 pt-2 text-xs text-neutral-400">
              <div className="flex items-center gap-1.5 bg-neutral-950/60 border border-neutral-800 rounded-xl px-3 py-1.5">
                <Building className="w-3.5 h-3.5 text-blue-400" />
                <span className="text-white font-medium">{tenantName}</span>
              </div>
              <div className="flex items-center gap-1.5 bg-neutral-950/60 border border-neutral-800 rounded-xl px-3 py-1.5 font-mono text-[11px]">
                <HardDrive className="w-3.5 h-3.5 text-emerald-400" />
                <span>{tenantId.slice(0, 18)}...</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Column: Personal Information Form */}
        <div className="lg:col-span-2 space-y-6">
          <div className="rounded-3xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md space-y-6">
            <div className="flex items-center justify-between border-b border-neutral-800 pb-4">
              <div className="flex items-center gap-2">
                <User className="w-5 h-5 text-purple-400" />
                <h3 className="text-base font-bold text-white">Profil & Konto-Einstellungen</h3>
              </div>
              <span className="text-xs text-neutral-500">Persönliche Informationen</span>
            </div>

            <form onSubmit={handleSaveProfile} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-neutral-400 mb-1.5">
                    Anzeigename / Name
                  </label>
                  <input
                    type="text"
                    value={nameInput}
                    onChange={(e) => setNameInput(e.target.value)}
                    required
                    className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-purple-500 outline-none transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider text-neutral-400 mb-1.5">
                    E-Mail-Adresse
                  </label>
                  <input
                    type="email"
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                    required
                    className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:border-purple-500 outline-none transition-colors"
                  />
                </div>
              </div>

              {saveSuccess && (
                <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300 flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>Profil-Änderungen erfolgreich lokal gespeichert!</span>
                </div>
              )}

              <div className="flex justify-end pt-2">
                <button
                  type="submit"
                  className="px-5 py-2.5 text-xs font-semibold rounded-xl bg-purple-600 hover:bg-purple-500 text-white transition-colors shadow-lg shadow-purple-600/20"
                >
                  Änderungen Speichern
                </button>
              </div>
            </form>
          </div>

          {/* Workspace & Security Settings Card */}
          <div className="rounded-3xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md space-y-6">
            <div className="flex items-center justify-between border-b border-neutral-800 pb-4">
              <div className="flex items-center gap-2">
                <Building className="w-5 h-5 text-blue-400" />
                <h3 className="text-base font-bold text-white">Workspace & Mandanten-Sicherheit</h3>
              </div>
              <span className="text-xs text-neutral-500">Multi-Tenant Status</span>
            </div>

            <div className="space-y-4">
              <div className="p-4 rounded-2xl bg-neutral-950 border border-neutral-800 space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-xs text-neutral-400 font-semibold uppercase tracking-wider">
                    Workspace Tenant ID (UUID)
                  </span>
                  <button
                    onClick={() => handleCopy(tenantId, setCopiedTenantId)}
                    className="flex items-center gap-1 text-[11px] text-purple-400 hover:text-purple-300 font-mono transition-colors"
                  >
                    {copiedTenantId ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedTenantId ? "Kopiert!" : "Kopieren"}</span>
                  </button>
                </div>
                <p className="text-xs text-white font-mono bg-neutral-900 p-2.5 rounded-xl border border-neutral-800/80 break-all select-all">
                  {tenantId}
                </p>
                <p className="text-[11px] text-neutral-500 leading-relaxed">
                  Alle Datenbank-Abfragen im PostgreSQL Core Service werden strikt nach dieser <code className="text-purple-400">tenant_id</code> gefiltert.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                <div className="p-4 rounded-2xl bg-neutral-950 border border-neutral-800 space-y-1.5">
                  <div className="flex items-center gap-2 text-xs font-bold text-white">
                    <Lock className="w-4 h-4 text-emerald-400" />
                    <span>Fernet AES-256 Verschlüsselung</span>
                  </div>
                  <p className="text-[11px] text-neutral-400 leading-snug">
                    Connector API-Token werden vor der Speicherung in PostgreSQL mit AES-256 symmetrisch verschlüsselt.
                  </p>
                </div>

                <div className="p-4 rounded-2xl bg-neutral-950 border border-neutral-800 space-y-1.5">
                  <div className="flex items-center gap-2 text-xs font-bold text-white">
                    <Database className="w-4 h-4 text-purple-400" />
                    <span>TimescaleDB Ownership</span>
                  </div>
                  <p className="text-[11px] text-neutral-400 leading-snug">
                    Ausschließlich der Core Service besitzt Datenbank-Zugriff. Importer & Dashboard kommunizieren entkoppelt.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: JWT Token Inspector & Danger Zone */}
        <div className="space-y-6">
          {/* JWT Token Inspector Card */}
          <div className="rounded-3xl border border-neutral-800 bg-neutral-900/60 p-6 backdrop-blur-md space-y-4">
            <div className="flex items-center justify-between border-b border-neutral-800 pb-3">
              <div className="flex items-center gap-2">
                <Key className="w-4 h-4 text-amber-400" />
                <h3 className="text-sm font-bold text-white">JWT Session Claim Inspector</h3>
              </div>
              <button
                onClick={() => handleCopy(token, setCopiedToken)}
                className="text-neutral-400 hover:text-white transition-colors"
                title="Token kopieren"
              >
                {copiedToken ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>

            <div className="space-y-2 text-xs">
              <div className="p-3 rounded-xl bg-neutral-950 border border-neutral-800 space-y-1.5 font-mono text-[11px]">
                <div className="flex justify-between text-neutral-400">
                  <span>sub (User ID):</span>
                  <span className="text-purple-300 font-bold">{jwtPayload.sub || "user_owner"}</span>
                </div>
                <div className="flex justify-between text-neutral-400">
                  <span>tenant_id:</span>
                  <span className="text-emerald-300">{tenantId.slice(0, 12)}...</span>
                </div>
                <div className="flex justify-between text-neutral-400">
                  <span>role:</span>
                  <span className="text-amber-300">{userRole}</span>
                </div>
                <div className="flex justify-between text-neutral-400">
                  <span>Algorithm:</span>
                  <span className="text-blue-300">HS256</span>
                </div>
              </div>

              <p className="text-[10px] text-neutral-500 leading-tight pt-1">
                Token wird bei jeder API-Anfrage im <code className="text-neutral-400">Authorization: Bearer</code> Header mitgesendet.
              </p>
            </div>
          </div>

          {/* Account Actions & Danger Zone */}
          <div className="rounded-3xl border border-red-900/30 bg-neutral-900/60 p-6 backdrop-blur-md space-y-4">
            <div className="flex items-center gap-2 border-b border-neutral-800 pb-3">
              <AlertCircle className="w-4 h-4 text-red-400" />
              <h3 className="text-sm font-bold text-white">Sitzung & Abmeldung</h3>
            </div>

            <p className="text-xs text-neutral-400 leading-snug">
              Melde dich von diesem Gerät ab oder setze lokale Session-Daten zurück.
            </p>

            <button
              onClick={onLogout}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 text-xs font-bold transition-colors"
            >
              <LogOut className="w-4 h-4" />
              <span>Vom Konto Abmelden</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
