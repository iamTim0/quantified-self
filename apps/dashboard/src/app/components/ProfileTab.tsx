"use client";

import React, { useState } from "react";
import { User, Mail, Shield, Key, Building, Check, Copy, CheckCircle2, Lock, HardDrive, Database, AlertCircle, LogOut } from "lucide-react";

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

  // Password Change State
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState("");

  const [copiedTenantId, setCopiedTenantId] = useState(false);
  const [copiedToken, setCopiedToken] = useState(false);

  const getInitials = (name: string) => {
    if (!name) return "QS";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  };

  const handleCopy = (text: string, setFn: (v: boolean) => void) => {
    navigator.clipboard.writeText(text);
    setFn(true);
    setTimeout(() => setFn(false), 2000);
  };

  const handleSaveProfile = (e: React.FormEvent) => {
    e.preventDefault();
    onUpdateProfile(nameInput, emailInput);
    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 3000);
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError("");
    setPasswordSuccess("");

    if (newPassword !== confirmPassword) {
      setPasswordError("Die neuen Passwörter stimmen nicht überein.");
      return;
    }

    if (newPassword.length < 6) {
      setPasswordError("Das neue Passwort muss mindestens 6 Zeichen lang sein.");
      return;
    }

    setPasswordLoading(true);
    try {
      const res = await fetch(`${apiBase}/api/v1/auth/change-password`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          "X-Tenant-ID": tenantId,
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Passwortänderung fehlgeschlagen.");
      }

      setPasswordSuccess("Passwort wurde erfolgreich aktualisiert!");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: any) {
      setPasswordError(err.message || "Fehler beim Ändern des Passworts.");
    } finally {
      setPasswordLoading(false);
    }
  };

  const parseJwtPayload = (jwtToken: string) => {
    try {
      const parts = jwtToken.split(".");
      if (parts.length < 2) return {};
      const base64Url = parts[1];
      const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
      const jsonPayload = decodeURIComponent(
        atob(base64)
          .split("")
          .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
          .join("")
      );
      return JSON.parse(jsonPayload);
    } catch {
      return {};
    }
  };

  const jwtPayload = parseJwtPayload(token);

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* Header Banner (Emerald SaaS Theme) */}
      <div className="dark-emerald-card p-8 rounded-3xl shadow-xl relative overflow-hidden">
        <div className="absolute top-0 right-0 p-8 opacity-10 pointer-events-none">
          <Shield className="w-64 h-64 text-emerald-100" />
        </div>

        <div className="relative flex flex-col sm:flex-row items-center sm:items-start gap-6">
          {/* Avatar Circle */}
          <div className="w-20 h-20 rounded-3xl bg-emerald-500/20 border border-emerald-400/30 flex items-center justify-center text-white text-2xl font-black shadow-inner shrink-0">
            {getInitials(userName)}
          </div>

          <div className="space-y-2 text-center sm:text-left flex-1">
            <div className="flex flex-wrap items-center justify-center sm:justify-start gap-2">
              <h2 className="text-2xl font-bold text-white">{userName}</h2>
              <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-400/30 text-emerald-100 text-xs font-bold uppercase tracking-wider">
                {userRole}
              </span>
              <span className="px-2.5 py-0.5 rounded-full bg-emerald-400/20 text-emerald-100 text-xs font-bold uppercase tracking-wider flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3 text-emerald-300" /> Tenant Isoliert
              </span>
            </div>

            <p className="text-xs text-emerald-100/90 flex items-center justify-center sm:justify-start gap-1.5 font-mono">
              <Mail className="w-3.5 h-3.5 text-emerald-300" />
              <span>{userEmail}</span>
            </p>

            <div className="flex flex-wrap items-center justify-center sm:justify-start gap-3 pt-2 text-xs text-emerald-100">
              <div className="flex items-center gap-1.5 bg-black/20 border border-white/10 rounded-xl px-3 py-1.5">
                <Building className="w-3.5 h-3.5 text-emerald-300" />
                <span className="text-white font-medium">{tenantName}</span>
              </div>
              <div className="flex items-center gap-1.5 bg-black/20 border border-white/10 rounded-xl px-3 py-1.5 font-mono text-[11px]">
                <HardDrive className="w-3.5 h-3.5 text-emerald-300" />
                <span>{tenantId.slice(0, 18)}...</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Column: Personal Information & Password Form */}
        <div className="lg:col-span-2 space-y-6">
          {/* Profile Card */}
          <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-6">
            <div className="flex items-center justify-between border-b border-slate-100 pb-4">
              <div className="flex items-center gap-2">
                <User className="w-5 h-5 text-[#0d5c3a]" />
                <h3 className="text-base font-bold text-slate-900">Profil & Konto-Einstellungen</h3>
              </div>
              <span className="text-xs text-slate-400">Persönliche Informationen</span>
            </div>

            <form onSubmit={handleSaveProfile} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    Anzeigename / Name
                  </label>
                  <input
                    type="text"
                    value={nameInput}
                    onChange={(e) => setNameInput(e.target.value)}
                    required
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    E-Mail-Adresse
                  </label>
                  <input
                    type="email"
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                    required
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                  />
                </div>
              </div>

              {saveSuccess && (
                <div className="p-3 rounded-2xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                  <span>Profil-Änderungen erfolgreich lokal gespeichert!</span>
                </div>
              )}

              <div className="flex justify-end pt-2">
                <button
                  type="submit"
                  className="px-5 py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all shadow-md shadow-[#0d5c3a]/20"
                >
                  Änderungen Speichern
                </button>
              </div>
            </form>
          </div>

          {/* Password Change Card */}
          <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-6">
            <div className="flex items-center justify-between border-b border-slate-100 pb-4">
              <div className="flex items-center gap-2">
                <Lock className="w-5 h-5 text-[#0d5c3a]" />
                <h3 className="text-base font-bold text-slate-900">Passwort Ändern</h3>
              </div>
              <span className="text-xs text-slate-400">Sicherheits-Aktualisierung</span>
            </div>

            <form onSubmit={handleChangePassword} className="space-y-4">
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                  Aktuelles Passwort
                </label>
                <input
                  type="password"
                  placeholder="••••••••"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                  className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    Neues Passwort
                  </label>
                  <input
                    type="password"
                    placeholder="Mindestens 6 Zeichen"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    minLength={6}
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-1.5">
                    Neues Passwort Wiederholen
                  </label>
                  <input
                    type="password"
                    placeholder="Wiederholen"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    minLength={6}
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                  />
                </div>
              </div>

              {passwordError && (
                <div role="alert" className="p-3 rounded-2xl bg-rose-50 border border-rose-200 text-xs text-rose-700">
                  {passwordError}
                </div>
              )}

              {passwordSuccess && (
                <div className="p-3 rounded-2xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                  <span>{passwordSuccess}</span>
                </div>
              )}

              <div className="flex justify-end pt-2">
                <button
                  type="submit"
                  disabled={passwordLoading}
                  className="px-5 py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all disabled:opacity-50 shadow-md shadow-[#0d5c3a]/20"
                >
                  {passwordLoading ? "Wird geändert..." : "Passwort Ändern"}
                </button>
              </div>
            </form>
          </div>

          {/* Workspace & Security Settings Card */}
          <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-6">
            <div className="flex items-center justify-between border-b border-slate-100 pb-4">
              <div className="flex items-center gap-2">
                <Building className="w-5 h-5 text-[#0d5c3a]" />
                <h3 className="text-base font-bold text-slate-900">Workspace & Mandanten-Sicherheit</h3>
              </div>
              <span className="text-xs text-slate-400">Multi-Tenant Status</span>
            </div>

            <div className="space-y-4">
              <div className="p-4 rounded-2xl bg-slate-50 border border-slate-200 space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-xs text-slate-500 font-bold uppercase tracking-wider">
                    Workspace Tenant ID (UUID)
                  </span>
                  <button
                    onClick={() => handleCopy(tenantId, setCopiedTenantId)}
                    className="flex items-center gap-1 text-[11px] text-[#0d5c3a] hover:underline font-mono transition-colors"
                  >
                    {copiedTenantId ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedTenantId ? "Kopiert!" : "Kopieren"}</span>
                  </button>
                </div>
                <p className="text-xs text-slate-900 font-mono bg-white p-2.5 rounded-xl border border-slate-200 break-all select-all">
                  {tenantId}
                </p>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Alle Datenbank-Abfragen im PostgreSQL Core Service werden strikt nach dieser <code className="text-[#0d5c3a]">tenant_id</code> gefiltered.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                <div className="p-4 rounded-2xl bg-slate-50 border border-slate-200 space-y-1.5">
                  <div className="flex items-center gap-2 text-xs font-bold text-slate-900">
                    <Lock className="w-4 h-4 text-[#0d5c3a]" />
                    <span>Fernet AES-256 Verschlüsselung</span>
                  </div>
                  <p className="text-[11px] text-slate-500 leading-snug">
                    Connector API-Token werden vor der Speicherung in PostgreSQL mit AES-256 symmetrisch verschlüsselt.
                  </p>
                </div>

                <div className="p-4 rounded-2xl bg-slate-50 border border-slate-200 space-y-1.5">
                  <div className="flex items-center gap-2 text-xs font-bold text-slate-900">
                    <Database className="w-4 h-4 text-[#0d5c3a]" />
                    <span>TimescaleDB Ownership</span>
                  </div>
                  <p className="text-[11px] text-slate-500 leading-snug">
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
          <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Key className="w-4 h-4 text-[#0d5c3a]" />
                <h3 className="text-sm font-bold text-slate-900">JWT Session Claim Inspector</h3>
              </div>
              <button
                onClick={() => handleCopy(token, setCopiedToken)}
                className="text-slate-400 hover:text-slate-900 transition-colors"
                title="Token kopieren"
              >
                {copiedToken ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>

            <div className="space-y-2 text-xs">
              <div className="p-3 rounded-2xl bg-slate-50 border border-slate-200 space-y-1.5 font-mono text-[11px]">
                <div className="flex justify-between text-slate-500">
                  <span>sub (User ID):</span>
                  <span className="text-slate-900 font-bold">{jwtPayload.sub || "user_owner"}</span>
                </div>
                <div className="flex justify-between text-slate-500">
                  <span>tenant_id:</span>
                  <span className="text-[#0d5c3a] font-bold">{tenantId.slice(0, 12)}...</span>
                </div>
                <div className="flex justify-between text-slate-500">
                  <span>role:</span>
                  <span className="text-emerald-700 font-bold">{userRole}</span>
                </div>
                <div className="flex justify-between text-slate-500">
                  <span>Algorithm:</span>
                  <span className="text-slate-700 font-bold">HS256</span>
                </div>
              </div>

              <p className="text-[10px] text-slate-400 leading-tight pt-1">
                Token wird bei jeder API-Anfrage im <code className="text-slate-600">Authorization: Bearer</code> Header mitgesendet.
              </p>
            </div>
          </div>

          {/* Account Actions & Danger Zone */}
          <div className="glass-card p-6 bg-white border border-rose-200 rounded-3xl space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
              <AlertCircle className="w-4 h-4 text-rose-500" />
              <h3 className="text-sm font-bold text-slate-900">Sitzung & Abmeldung</h3>
            </div>

            <p className="text-xs text-slate-500 leading-snug">
              Melde dich von diesem Gerät ab oder setze lokale Session-Daten zurück.
            </p>

            <button
              onClick={onLogout}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-600 text-xs font-bold transition-all"
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
