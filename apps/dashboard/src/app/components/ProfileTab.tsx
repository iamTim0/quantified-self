"use client";

import React, { useEffect, useState } from "react";
import {
  User,
  Mail,
  Lock,
  Building,
  ShieldCheck,
  LogOut,
  Check,
  Copy,
  AlertCircle,
  CheckCircle2,
  Trash2,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import { apiFetch } from "../lib/api";
import OidcProviderAdmin from "./OidcProviderAdmin";
import { useT } from "../lib/i18n/provider";

interface ProfileTabProps {
  apiBase: string;
  tenantId: string;
  userName: string;
  userEmail: string;
  userRole: string;
  tenantName: string;
  onUpdateProfile?: (name: string, email: string, workspaceName: string) => void;
  onLogout: () => void;
}

export default function ProfileTab({
  apiBase,
  tenantId,
  userName,
  userEmail,
  userRole,
  tenantName,
  onUpdateProfile,
  onLogout,
}: ProfileTabProps) {
  const t = useT();
  const [profileName, setProfileName] = useState(userName);
  const [profileEmail, setProfileEmail] = useState(userEmail);
  const [profileWorkspaceName, setProfileWorkspaceName] = useState(tenantName);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [profileSuccess, setProfileSuccess] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState("");

  const [copiedTenantId, setCopiedTenantId] = useState(false);

  // 1-Click Deletion States
  const [wipeLoading, setWipeLoading] = useState(false);
  const [wipeSuccess, setWipeSuccess] = useState("");
  const [wipeError, setWipeError] = useState("");
  const [showWipeModal, setShowWipeModal] = useState(false);
  const [showAccountModal, setShowAccountModal] = useState(false);

  useEffect(() => {
    setProfileName(userName);
    setProfileEmail(userEmail);
    setProfileWorkspaceName(tenantName);
  }, [tenantName, userEmail, userName]);

  const handleCopy = (text: string, setFn: (val: boolean) => void) => {
    navigator.clipboard.writeText(text);
    setFn(true);
    setTimeout(() => setFn(false), 2000);
  };

  const handleProfileSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setProfileLoading(true);
    setProfileError("");
    setProfileSuccess("");
    try {
      const res = await apiFetch(`${apiBase}/api/v1/auth/me`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-ID": tenantId,
        },
        body: JSON.stringify({
          name: profileName,
          email: profileEmail,
          workspace_name: profileWorkspaceName,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        throw new Error(data?.detail || t("profile.saveFailed"));
      }
      const savedName = String(data?.name ?? profileName);
      const savedEmail = String(data?.email ?? profileEmail);
      const savedWorkspace = String(data?.workspace_name ?? profileWorkspaceName);
      setProfileName(savedName);
      setProfileEmail(savedEmail);
      setProfileWorkspaceName(savedWorkspace);
      onUpdateProfile?.(savedName, savedEmail, savedWorkspace);
      setProfileSuccess(
        data?.session_refreshed
          ? t("profile.savedAndSessionRefreshed")
          : t("profile.saved"),
      );
    } catch (err: unknown) {
      setProfileError(err instanceof Error ? err.message : String(err));
    } finally {
      setProfileLoading(false);
    }
  };

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError("");
    setPasswordSuccess("");

    if (newPassword !== confirmPassword) {
      setPasswordError(t("profile.passwordMismatch"));
      return;
    }

    setPasswordLoading(true);
    try {
      const res = await apiFetch(`${apiBase}/api/v1/auth/change-password`, {
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
        throw new Error(data.detail || t("profile.passwordFailed"));
      }

      setPasswordSuccess(t("profile.passwordChanged"));
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
        throw new Error(data.detail || t("profile.wipeFailed"));
      }
      setWipeSuccess(t("profile.wipeDone", { count: data.deleted_count || 0 }));
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
        throw new Error(data.detail || t("profile.deleteAccountFailed"));
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
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">
            {t("profile.title")}
          </h1>
          <p className="text-xs text-slate-500 mt-1">{t("profile.subtitle")}</p>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs font-bold uppercase tracking-wider bg-emerald-50 text-emerald-800 border border-emerald-200 px-3.5 py-1.5 rounded-full flex items-center gap-1.5">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            <span>{t("profile.tenantIsolated")}</span>
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
                {userName ? userName[0].toUpperCase() : t("profile.defaultInitial")}
              </div>
              <div>
                <h2 className="text-lg font-extrabold text-slate-900">
                  {userName || t("profile.defaultUser")}
                </h2>
                <p className="text-xs text-slate-500">{userEmail}</p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] font-bold uppercase tracking-wider bg-slate-100 text-slate-700 px-2.5 py-0.5 rounded-full border border-slate-200">
                    {t("profile.role", { role: userRole })}
                  </span>
                  <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-50 text-emerald-800 px-2.5 py-0.5 rounded-full border border-emerald-200">
                    {tenantName}
                  </span>
                </div>
              </div>
            </div>

            <form onSubmit={handleProfileSave} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="profile-name"
                    className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1"
                  >
                    {t("profile.username")}
                  </label>
                  <div className="relative">
                    <User className="absolute left-3.5 top-3 w-4 h-4 text-slate-400" />
                    <input
                      id="profile-name"
                      type="text"
                      value={profileName}
                      onChange={(e) => setProfileName(e.target.value)}
                      maxLength={128}
                      required
                      className="w-full pl-10 pr-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                    />
                  </div>
                </div>

                <div>
                  <label
                    htmlFor="profile-email"
                    className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1"
                  >
                    {t("profile.email")}
                  </label>
                  <div className="relative">
                    <Mail className="absolute left-3.5 top-3 w-4 h-4 text-slate-400" />
                    <input
                      id="profile-email"
                      type="email"
                      value={profileEmail}
                      onChange={(e) => setProfileEmail(e.target.value)}
                      maxLength={320}
                      required
                      className="w-full pl-10 pr-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                    />
                  </div>
                </div>
              </div>

              <div>
                <label
                  htmlFor="profile-workspace"
                  className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1"
                >
                  {t("profile.workspaceName")}
                </label>
                <div className="relative">
                  <Building className="absolute left-3.5 top-3 w-4 h-4 text-slate-400" />
                  <input
                    id="profile-workspace"
                    type="text"
                    value={profileWorkspaceName}
                    onChange={(e) => setProfileWorkspaceName(e.target.value)}
                    maxLength={128}
                    required
                    disabled={userRole === "member"}
                    className="w-full pl-10 pr-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500"
                  />
                </div>
                {userRole === "member" && (
                  <p className="mt-1 text-[11px] text-slate-500">{t("profile.workspaceAdminOnly")}</p>
                )}
              </div>

              {profileError && (
                <div
                  role="alert"
                  className="p-3 rounded-2xl bg-rose-50 border border-rose-200 text-xs text-rose-700 font-semibold"
                >
                  {profileError}
                </div>
              )}

              {profileSuccess && (
                <div className="p-3 rounded-2xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-800 flex items-center gap-2 font-semibold">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                  <span>{profileSuccess}</span>
                </div>
              )}

              <div className="flex justify-end pt-1">
                <button
                  type="submit"
                  disabled={profileLoading}
                  className="px-5 py-2.5 text-xs font-bold rounded-2xl bg-[#0d5c3a] hover:bg-[#08432a] text-white transition-all disabled:opacity-50 shadow-md shadow-[#0d5c3a]/20"
                >
                  {profileLoading ? t("profile.saving") : t("profile.save")}
                </button>
              </div>
            </form>
          </div>

          {/* 1-Click Data Deletion & GDPR Art. 17 Card */}
          <div className="glass-card p-6 bg-white border border-rose-200 rounded-3xl space-y-4 shadow-sm">
            <div className="flex items-center justify-between border-b border-rose-100 pb-3">
              <div className="flex items-center gap-2">
                <Trash2 className="w-5 h-5 text-rose-600" />
                <h3 className="text-base font-extrabold text-slate-900">
                  {t("profile.gdprTitle")}
                </h3>
              </div>
              <span className="text-[10px] font-bold uppercase tracking-wider bg-rose-50 text-rose-700 px-2.5 py-0.5 rounded-full border border-rose-200">
                {t("profile.gdprBadge")}
              </span>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">{t("profile.gdprBody")}</p>

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
                <span>{t("profile.wipeButton")}</span>
              </button>

              <button
                onClick={() => setShowAccountModal(true)}
                className="py-3 px-4 rounded-2xl bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold transition-all flex items-center justify-center gap-2 shadow-md shadow-rose-600/20"
              >
                <Trash2 className="w-4 h-4" />
                <span>{t("profile.deleteAccountButton")}</span>
              </button>
            </div>
          </div>

          {/* Change Password Card */}
          <div className="glass-card p-6 bg-white border border-slate-200/80 rounded-3xl space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
              <Lock className="w-5 h-5 text-[#0d5c3a]" />
              <h3 className="text-base font-bold text-slate-900">{t("profile.changePassword")}</h3>
            </div>

            <form onSubmit={handlePasswordChange} className="space-y-4">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">
                    {t("profile.currentPassword")}
                  </label>
                  <input
                    type="password"
                    placeholder={t("profile.passwordPlaceholder")}
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                  className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">
                    {t("profile.newPassword")}
                  </label>
                    <input
                      type="password"
                      placeholder={t("profile.passwordMinimum")}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    minLength={6}
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-1">
                    {t("profile.confirm")}
                  </label>
                    <input
                      type="password"
                      placeholder={t("profile.passwordRepeat")}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    minLength={6}
                    className="w-full px-4 py-2.5 rounded-2xl bg-white border border-slate-200 text-slate-900 text-sm focus:border-[#0d5c3a] focus:ring-2 focus:ring-[#0d5c3a]/20 outline-none transition-all"
                  />
                </div>
              </div>

              {passwordError && (
                <div
                  role="alert"
                  className="p-3 rounded-2xl bg-rose-50 border border-rose-200 text-xs text-rose-700 font-semibold"
                >
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
                  {passwordLoading ? t("profile.changing") : t("profile.changePassword")}
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
              <h3 className="text-sm font-bold text-slate-900">{t("profile.workspaceDetails")}</h3>
            </div>

            <div className="space-y-3">
              <div className="p-3 rounded-2xl bg-slate-50 border border-slate-200 space-y-1.5">
                <div className="flex justify-between items-center">
                  <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">
                    {t("profile.tenantId")}
                  </span>
                  <button
                    onClick={() => handleCopy(tenantId, setCopiedTenantId)}
                    className="flex items-center gap-1 text-[11px] text-[#0d5c3a] hover:underline font-mono transition-colors"
                  >
                    {copiedTenantId ? (
                      <Check className="w-3.5 h-3.5 text-emerald-600" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                    <span>{copiedTenantId ? t("profile.copied") : t("profile.copy")}</span>
                  </button>
                </div>
                <p className="text-[11px] text-slate-900 font-mono bg-white p-2 rounded-xl border border-slate-200 break-all select-all">
                  {tenantId}
                </p>
              </div>

              <div className="p-3.5 rounded-2xl bg-slate-50 border border-slate-200 space-y-1">
                <div className="flex items-center gap-2 text-xs font-bold text-slate-900">
                  <Lock className="w-4 h-4 text-[#0d5c3a]" />
                  <span>{t("profile.encryptedSecrets")}</span>
                </div>
                <p className="text-[11px] text-slate-500 leading-snug">
                  {t("profile.encryptionNote")}
                </p>
              </div>
            </div>
          </div>

          {/* Session & Logout */}
          <div className="glass-card p-6 bg-white border border-rose-200 rounded-3xl space-y-4">
            <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
              <AlertCircle className="w-4 h-4 text-rose-500" />
              <h3 className="text-sm font-bold text-slate-900">{t("profile.sessionTitle")}</h3>
            </div>

            <button
              onClick={onLogout}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-600 text-xs font-bold transition-all"
            >
              <LogOut className="w-4 h-4" />
              <span>{t("profile.signOut")}</span>
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
              <h3 className="text-lg font-extrabold text-slate-900">
                {t("profile.wipeConfirmTitle")}
              </h3>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed">{t("profile.wipeConfirmBody")}</p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowWipeModal(false)}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
              >
                {t("common.cancel")}
              </button>
              <button
                onClick={handleWipeDataPoints}
                disabled={wipeLoading}
                className="px-4 py-2 text-xs font-bold rounded-xl bg-amber-600 text-white hover:bg-amber-700 transition-all disabled:opacity-50"
              >
                {wipeLoading ? t("profile.wipeRunning") : t("profile.wipeConfirmAction")}
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
              <h3 className="text-lg font-extrabold text-slate-900">
                {t("profile.deleteAccountTitle")}
              </h3>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed">
              {t("profile.deleteAccountBody")}
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowAccountModal(false)}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
              >
                {t("common.cancel")}
              </button>
              <button
                onClick={handleAccountWipe}
                disabled={wipeLoading}
                className="px-4 py-2 text-xs font-bold rounded-xl bg-rose-600 text-white hover:bg-rose-700 transition-all disabled:opacity-50"
              >
                {wipeLoading ? t("profile.deleteAccountRunning") : t("profile.deleteAccountAction")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Owner/admin only in practice: the endpoint returns 403 for a member and
          the component renders that as an explanation rather than an error. */}
      <div className="rounded-3xl border border-slate-200 bg-white p-5">
        <OidcProviderAdmin apiBase={apiBase} />
      </div>

      <div className="pt-2">
        <h3 className="mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-500">
          {t("profile.legalTitle")}
        </h3>
        <p className="mb-2 text-xs text-slate-500">
          {t("profile.privacyLead")}
        </p>
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
          <a href="/legal/datenschutz" className="text-[#0d5c3a] underline hover:text-[#08432a]">
            {t("footer.privacy")}
          </a>
          <a href="/legal/impressum" className="text-[#0d5c3a] underline hover:text-[#08432a]">
            {t("footer.imprint")}
          </a>
          <a
            href="/docs/"
            target="_blank"
            rel="noreferrer"
            className="text-[#0d5c3a] underline hover:text-[#08432a]"
          >
            {t("profile.documentation")}
          </a>
        </div>
      </div>
    </div>
  );
}
