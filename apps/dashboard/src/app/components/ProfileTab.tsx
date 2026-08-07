"use client";

import React, { useState } from "react";
import { 
  User, 
  Mail, 
  Lock, 
  Building, 
  ShieldCheck, 
  Key, 
  LogOut, 
  Check, 
  Copy, 
  AlertCircle, 
  CheckCircle2, 
  Database,
  Trash2,
  AlertTriangle,
  RefreshCw
} from "lucide-react";
import { apiFetch } from "../lib/api";

interface ProfileTabProps {
  apiBase: string;
  tenantId: string;
  userName: string;
  userEmail: string;
  userRole: string;
  tenantName: string;
  onUpdateProfile?: (name: string, email: string) => void;
  onLogout: () => void;
}

export default function ProfileTab({
  apiBase,
  tenantId,
  userName,
  userEmail,
  userRole,
  tenantName,
  onLogout,
}: ProfileTabProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState("");

  const [copiedTenantId, setCopiedTenantId] = useState(false);
  const [copiedToken, setCopiedToken] = useState(false);

  // 1-Click Deletion States
  const [wipeLoading, setWipeLoading] = useState(false);
  const [wipeSuccess, setWipeSuccess] = useState("");
  const [wipeError, setWipeError] = useState("");
  const [showWipeModal, setShowWipeModal] = useState(false);
  const [showAccountModal, setShowAccountModal] = useState(false);

  const handleCopy = (text: string, setFn: (val: boolean) => void) => {
    navigator.clipboard.writeText(text);
    setFn(true);
    setTimeout(() => setFn(false), 2000);
  };

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError("");
    setPasswordSuccess("");

    if (newPassword !== confirmPassword) {
      setPasswordError("Die neuen Passwörter stimmen nicht überein.");
      return;
    }

    setPasswordLoading(true);
    try {
      const res = await apiFetch(`${apiBase}/api/v1/auth/me/password`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
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

      setPasswordSuccess("Passwort erfolgreich geändert!");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: unknown) {
      setPasswordError(err instanceof Error ? err.message : String(err));
    } finally {
      setPasswordLoading(false);
    }
  };

  // 1-Click Data Points Wipe (Wipes all data_points table entries for tenant)
  const handleWipeDataPoints = async () => {
    setWipeLoading(true);
    setWipeError("");
    setWipeSuccess("");
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/wipe`, {
        method: "DELETE",
        headers: {
          "X-Tenant-ID": tenantId,
        },
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Datenpunkt-Reset fehlgeschlagen.");
      }
      setWipeSuccess(`Erfolgreich ${data.deleted_count || 0} Datenpunkte im Workspace gelöscht!`);
      setShowWipeModal(false);
    } catch (err: unknown) {
      setWipeError(err instanceof Error ? err.message : String(err));
    } finally {
      setWipeLoading(false);
    }
  };

  // 1-Click Full Account & Data Wipe (Wipes data_points, data_sources, tenant_shares)
  const handleAccountWipe = async () => {
    setWipeLoading(true);
    setWipeError("");
    try {
      const res = await apiFetch(`${apiBase}/api/v1/data/account`, {
        method: "DELETE",
        headers: {
          "X-Tenant-ID": tenantId,
        },
      });
      if (res.ok) {
        setShowAccountModal(false);
        onLogout();
      } else {
        const data = await res.json();
        throw new Error(data.detail || "Kontolöschung fehlgeschlagen.");
      }
    } catch (err: unknown) {
      setWipeError(err instanceof Error ? err.message : String(err));
    } finally {
      setWipeLoading(false);
    }
  };


  return (
    <div className="space-y-8">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Konto- & Profileinstellungen</h1>
          <p className="text-xs text-slate-500 mt-1">
            Verwalte deine Benutzerdaten, Sicherheitseinstellungen und die 1-Klick-Datenlöschung.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs font-bold uppercase tracking-wider bg-emerald-50 text-emerald-800 border border-emerald-200 px-3.5 py-1.5 rounded-full flex items-center gap-1.5">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            <span>Multi-Tenant Isoliert</span>
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left 2 Columns: User Info, Password & 1-Click Delete */}
        <div className="lg:col-span-2 space-y-6">
          {/* User Profile Info Card */}
          <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-6">
            <div className="flex items-center gap-4 border-b border-slate-100 pb-4">
              <div className="w-14 h-14 rounded-2xl bg-[#0d5c3a] text-white flex items-center justify-center font-extrabold text-xl shadow-lg shadow-[#0d5c3a]/20">
                {userName ? userName[0].toUpperCase() : "U"}
              </div>
              <div>
                <h2 className="text-lg font-extrabold text-slate-900">{userName || "Benutzer"}</h2>
                <p className="text-xs text-slate-500">{userEmail}</p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] font-bold uppercase tracking-wider bg-slate-100 text-slate-700 px-2.5 py-0.5 rounded-full border border-slate-200">
                    Rolle: {userRole}
                  </span>
                  <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-50 text-emerald-800 px-2.5 py-0.5 rounded-full border border-emerald-200">
                    {tenantName}
                  </span>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">
                  Benutzername
                </label>
                <div className="flex items-center gap-2 p-3 bg-slate-50 border border-slate-200 rounded-2xl text-slate-900 text-xs font-semibold">
                  <User className="w-4 h-4 text-slate-400" />
                  <span>{userName}</span>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">
                  E-Mail Adresse
                </label>
                <div className="flex items-center gap-2 p-3 bg-slate-50 border border-slate-200 rounded-2xl text-slate-900 text-xs font-semibold">
                  <Mail className="w-4 h-4 text-slate-400" />
                  <span>{userEmail}</span>
                </div>
              </div>
            </div>
          </div>

          {/* 1-Click Data Deletion & GDPR Art. 17 Card */}
          <div className="glass-card p-6 bg-white border border-rose-200 rounded-3xl space-y-4 shadow-sm">
            <div className="flex items-center justify-between border-b border-rose-100 pb-3">
              <div className="flex items-center gap-2">
                <Trash2 className="w-5 h-5 text-rose-600" />
                <h3 className="text-base font-extrabold text-slate-900">1-Klick Datenlöschung (DSGVO Art. 17)</h3>
              </div>
              <span className="text-[10px] font-bold uppercase tracking-wider bg-rose-50 text-rose-700 px-2.5 py-0.5 rounded-full border border-rose-200">
                Löschrecht Aktiv
              </span>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Gemäß DSGVO Art. 17 (Recht auf Vergessenwerden) kannst du alle in der Plattform gespeicherten Datenpunkte oder dein Konto vollständig mit 1 Klick löschen.
            </p>

            {wipeSuccess && (
              <div className="p-3 rounded-2xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 font-semibold flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>{wipeSuccess}</span>
              </div>
            )}

            {wipeError && (
              <div className="p-3 rounded-2xl bg-rose-50 border border-rose-200 text-xs text-rose-700 font-semibold">
                {wipeError}
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
              <button
                onClick={() => setShowWipeModal(true)}
                className="py-3 px-4 rounded-2xl bg-amber-50 hover:bg-amber-100 border border-amber-200 text-amber-900 text-xs font-bold transition-all flex items-center justify-center gap-2"
              >
                <RefreshCw className="w-4 h-4 text-amber-700" />
                <span>1-Klick Datenpunkt Reset</span>
              </button>

              <button
                onClick={() => setShowAccountModal(true)}
                className="py-3 px-4 rounded-2xl bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold transition-all flex items-center justify-center gap-2 shadow-md shadow-rose-600/20"
              >
                <Trash2 className="w-4 h-4" />
                <span>Konto & Alle Daten Löschen</span>
              </button>
            </div>
          </div>

          {/* Change Password Card */}
          <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
              <Lock className="w-5 h-5 text-[#0d5c3a]" />
              <h3 className="text-base font-bold text-slate-900">Passwort Ändern</h3>
            </div>

            <form onSubmit={handlePasswordChange} className="space-y-4">
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">
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
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">
                    Neues Passwort
                  </label>
                  <input
                    type="password"
                    placeholder="Mind. 6 Zeichen"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    minLength={6}
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">
                    Bestätigen
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
                <div role="alert" className="p-3 rounded-2xl bg-rose-50 border border-rose-200 text-xs text-rose-700 font-semibold">
                  {passwordError}
                </div>
              )}

              {passwordSuccess && (
                <div className="p-3 rounded-2xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 flex items-center gap-2 font-semibold">
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
        </div>

        {/* Right Column: Workspace & JWT Inspection */}
        <div className="space-y-6">
          {/* Workspace Security Info Card */}
          <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
              <Building className="w-5 h-5 text-[#0d5c3a]" />
              <h3 className="text-sm font-bold text-slate-900">Workspace & Mandanten-ID</h3>
            </div>

            <div className="space-y-3">
              <div className="p-3 rounded-2xl bg-slate-50 border border-slate-200 space-y-1.5">
                <div className="flex justify-between items-center">
                  <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">
                    Tenant ID (UUID)
                  </span>
                  <button
                    onClick={() => handleCopy(tenantId, setCopiedTenantId)}
                    className="flex items-center gap-1 text-[11px] text-[#0d5c3a] hover:underline font-mono transition-colors"
                  >
                    {copiedTenantId ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copiedTenantId ? "Kopiert!" : "Kopieren"}</span>
                  </button>
                </div>
                <p className="text-[11px] text-slate-900 font-mono bg-white p-2 rounded-xl border border-slate-200 break-all select-all">
                  {tenantId}
                </p>
              </div>

              <div className="p-3.5 rounded-2xl bg-slate-50 border border-slate-200 space-y-1">
                <div className="flex items-center gap-2 text-xs font-bold text-slate-900">
                  <Lock className="w-4 h-4 text-[#0d5c3a]" />
                  <span>AES-256 Encrypted Secrets</span>
                </div>
                <p className="text-[11px] text-slate-500 leading-snug">
                  Connector-Tokens werden vor der Speicherung in PostgreSQL mit Fernet AES-256 verschlüsselt.
                </p>
              </div>
            </div>
          </div>

          {/* Session & Logout */}
          <div className="glass-card p-6 bg-white border border-rose-200 rounded-3xl space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
              <AlertCircle className="w-4 h-4 text-rose-500" />
              <h3 className="text-sm font-bold text-slate-900">Sitzung & Abmeldung</h3>
            </div>

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

      {/* 1-Click Data Points Wipe Confirmation Modal */}
      {showWipeModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white border border-slate-200 rounded-3xl p-6 max-w-md w-full space-y-4 shadow-2xl">
            <div className="flex items-center gap-3 text-amber-600">
              <div className="p-2.5 rounded-2xl bg-amber-50 border border-amber-200">
                <AlertTriangle className="w-6 h-6" />
              </div>
              <h3 className="text-lg font-extrabold text-slate-900">1-Klick Datenpunkt-Reset?</h3>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed">
              Möchtest du wirklich **alle importierten Datenpunkte** in deinem Workspace löschen? 
              Deine verbundenen Datenquellen und Tokens bleiben dabei erhalten.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowWipeModal(false)}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
              >
                Abbrechen
              </button>
              <button
                onClick={handleWipeDataPoints}
                disabled={wipeLoading}
                className="px-4 py-2 text-xs font-bold rounded-xl bg-amber-600 text-white hover:bg-amber-700 transition-all disabled:opacity-50"
              >
                {wipeLoading ? "Lösche Daten..." : "Ja, alle Datenpunkte löschen"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Full Account & Data Wipe Confirmation Modal */}
      {showAccountModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white border border-rose-200 rounded-3xl p-6 max-w-md w-full space-y-4 shadow-2xl">
            <div className="flex items-center gap-3 text-rose-600">
              <div className="p-2.5 rounded-2xl bg-rose-50 border border-rose-200">
                <Trash2 className="w-6 h-6" />
              </div>
              <h3 className="text-lg font-extrabold text-slate-900">Vollständige Kontolöschung?</h3>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed">
              Dieser Vorgang löscht **alle Datenpunkte, Connector-Tokens und Freigaben** deines Kontos unwiderruflich aus PostgreSQL (DSGVO Art. 17).
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowAccountModal(false)}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
              >
                Abbrechen
              </button>
              <button
                onClick={handleAccountWipe}
                disabled={wipeLoading}
                className="px-4 py-2 text-xs font-bold rounded-xl bg-rose-600 text-white hover:bg-rose-700 transition-all disabled:opacity-50"
              >
                {wipeLoading ? "Lösche Konto..." : "Unwiderruflich Löschen"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="pt-2">
        <h3 className="mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">
          Rechtliches
        </h3>
        <p className="mb-2 text-xs text-slate-500">
          Welche Daten wir verarbeiten, auf welcher Grundlage und wie du sie löschen
          kannst.
        </p>
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
          <a
            href="/legal/datenschutz"
            className="text-[#0d5c3a] underline hover:text-[#08432a]"
          >
            Datenschutzerklärung
          </a>
          <a
            href="/legal/impressum"
            className="text-[#0d5c3a] underline hover:text-[#08432a]"
          >
            Impressum
          </a>
          <a
            href="/docs/"
            target="_blank"
            rel="noreferrer"
            className="text-[#0d5c3a] underline hover:text-[#08432a]"
          >
            Dokumentation
          </a>
        </div>
      </div>
    </div>
  );
}
