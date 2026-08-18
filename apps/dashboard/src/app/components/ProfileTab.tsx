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
  Palette,
} from "lucide-react";
import { apiFetch } from "../lib/api";
import LanguageSwitcher from "./LanguageSwitcher";
import OidcProviderAdmin from "./OidcProviderAdmin";
import ThemeSwitcher from "./ThemeSwitcher";
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
        data?.session_refreshed ? t("profile.savedAndSessionRefreshed") : t("profile.saved"),
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
          <h1 className="text-3xl font-extrabold text-ink tracking-tight">
            {t("profile.title")}
          </h1>
          <p className="text-xs text-ink-muted mt-1">{t("profile.subtitle")}</p>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs font-bold uppercase tracking-wider bg-ok-soft text-ok-ink border border-ok-line px-3.5 py-1.5 rounded-full flex items-center gap-1.5">
            <ShieldCheck className="w-4 h-4 text-ok" />
            <span>{t("profile.tenantIsolated")}</span>
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left 2 Columns: User Info, Password & 1-Click Delete */}
        <div className="lg:col-span-2 space-y-6">
          {/* User Profile Info Card */}
          <div className="glass-card p-6 bg-surface border border-line rounded-3xl space-y-6">
            <div className="flex items-center gap-4 border-b border-line pb-4">
              <div className="w-14 h-14 rounded-2xl bg-brand text-brand-ink flex items-center justify-center font-extrabold text-xl shadow-lg shadow-brand/20">
                {userName ? userName[0].toUpperCase() : t("profile.defaultInitial")}
              </div>
              <div>
                <h2 className="text-lg font-extrabold text-ink">
                  {userName || t("profile.defaultUser")}
                </h2>
                <p className="text-xs text-ink-muted">{userEmail}</p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-meta font-bold uppercase tracking-wider bg-surface-muted text-ink-secondary px-2.5 py-0.5 rounded-full border border-line">
                    {t("profile.role", { role: userRole })}
                  </span>
                  <span className="text-meta font-bold uppercase tracking-wider bg-ok-soft text-ok-ink px-2.5 py-0.5 rounded-full border border-ok-line">
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
                    className="block text-xs font-bold uppercase tracking-wider text-ink-muted mb-1"
                  >
                    {t("profile.username")}
                  </label>
                  <div className="relative">
                    <User className="absolute left-3.5 top-3 w-4 h-4 text-ink-muted" />
                    <input
                      id="profile-name"
                      type="text"
                      value={profileName}
                      onChange={(e) => setProfileName(e.target.value)}
                      maxLength={128}
                      required
                      className="w-full pl-10 pr-4 py-2.5 rounded-2xl bg-surface border border-line text-ink text-sm focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 outline-none transition-colors"
                    />
                  </div>
                </div>

                <div>
                  <label
                    htmlFor="profile-email"
                    className="block text-xs font-bold uppercase tracking-wider text-ink-muted mb-1"
                  >
                    {t("profile.email")}
                  </label>
                  <div className="relative">
                    <Mail className="absolute left-3.5 top-3 w-4 h-4 text-ink-muted" />
                    <input
                      id="profile-email"
                      type="email"
                      value={profileEmail}
                      onChange={(e) => setProfileEmail(e.target.value)}
                      maxLength={320}
                      required
                      className="w-full pl-10 pr-4 py-2.5 rounded-2xl bg-surface border border-line text-ink text-sm focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 outline-none transition-colors"
                    />
                  </div>
                </div>
              </div>

              <div>
                <label
                  htmlFor="profile-workspace"
                  className="block text-xs font-bold uppercase tracking-wider text-ink-muted mb-1"
                >
                  {t("profile.workspaceName")}
                </label>
                <div className="relative">
                  <Building className="absolute left-3.5 top-3 w-4 h-4 text-ink-muted" />
                  <input
                    id="profile-workspace"
                    type="text"
                    value={profileWorkspaceName}
                    onChange={(e) => setProfileWorkspaceName(e.target.value)}
                    maxLength={128}
                    required
                    disabled={userRole === "member"}
                    className="w-full pl-10 pr-4 py-2.5 rounded-2xl bg-surface border border-line text-ink text-sm focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 outline-none transition-colors disabled:bg-surface-muted disabled:text-ink-muted"
                  />
                </div>
                {userRole === "member" && (
                  <p className="mt-1 text-meta text-ink-muted">
                    {t("profile.workspaceAdminOnly")}
                  </p>
                )}
              </div>

              {profileError && (
                <div
                  role="alert"
                  className="p-3 rounded-2xl bg-danger-soft border border-danger-line text-xs text-danger-ink-on-soft font-semibold"
                >
                  {profileError}
                </div>
              )}

              {profileSuccess && (
                <div className="p-3 rounded-2xl bg-ok-soft border border-ok-line text-xs text-ok-ink flex items-center gap-2 font-semibold">
                  <CheckCircle2 className="w-4 h-4 text-ok shrink-0" />
                  <span>{profileSuccess}</span>
                </div>
              )}

              <div className="flex justify-end pt-1">
                <button
                  type="submit"
                  disabled={profileLoading}
                  className="px-5 py-2.5 text-xs font-bold rounded-2xl bg-brand hover:bg-brand-hover text-brand-ink [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] disabled:opacity-50 shadow-md shadow-brand/20"
                >
                  {profileLoading ? t("profile.saving") : t("profile.save")}
                </button>
              </div>
            </form>
          </div>

          {/* 1-Click Data Deletion & GDPR Art. 17 Card */}
          <div className="glass-card p-6 bg-surface border border-danger-line rounded-3xl space-y-4 shadow-sm">
            <div className="flex items-center justify-between border-b border-danger-line pb-3">
              <div className="flex items-center gap-2">
                <Trash2 className="w-5 h-5 text-danger-ink-on-soft" />
                <h3 className="text-base font-extrabold text-ink">
                  {t("profile.gdprTitle")}
                </h3>
              </div>
              <span className="text-meta font-bold uppercase tracking-wider bg-danger-soft text-danger-ink-on-soft px-2.5 py-0.5 rounded-full border border-danger-line">
                {t("profile.gdprBadge")}
              </span>
            </div>

            <p className="text-xs text-ink-muted leading-relaxed">{t("profile.gdprBody")}</p>

            {wipeSuccess && (
              <div className="p-3 rounded-2xl bg-ok-soft border border-ok-line text-xs text-ok-ink font-semibold flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-ok shrink-0" />
                <span>{wipeSuccess}</span>
              </div>
            )}

            {wipeError && (
              <div className="p-3 rounded-2xl bg-danger-soft border border-danger-line text-xs text-danger-ink-on-soft font-semibold">
                {wipeError}
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
              <button
                onClick={() => setShowWipeModal(true)}
                className="py-3 px-4 rounded-2xl bg-warn-soft hover:bg-warn-soft border border-warn-line text-warn-ink text-xs font-bold transition-colors flex items-center justify-center gap-2"
              >
                <RefreshCw className="w-4 h-4 text-warn-ink" />
                <span>{t("profile.wipeButton")}</span>
              </button>

              <button
                onClick={() => setShowAccountModal(true)}
                className="py-3 px-4 rounded-2xl bg-danger hover:bg-danger/90 text-danger-ink text-xs font-bold [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] flex items-center justify-center gap-2 shadow-md shadow-danger/20"
              >
                <Trash2 className="w-4 h-4" />
                <span>{t("profile.deleteAccountButton")}</span>
              </button>
            </div>
          </div>

          {/* Change Password Card */}
          <div className="glass-card p-6 bg-surface border border-line rounded-3xl space-y-4">
            <div className="flex items-center gap-2 border-b border-line pb-3">
              <Lock className="w-5 h-5 text-brand" />
              <h3 className="text-base font-bold text-ink">{t("profile.changePassword")}</h3>
            </div>

            <form onSubmit={handlePasswordChange} className="space-y-4">
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-ink-muted mb-1">
                  {t("profile.currentPassword")}
                </label>
                <input
                  type="password"
                  placeholder={t("profile.passwordPlaceholder")}
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                  className="w-full px-4 py-2.5 rounded-2xl bg-surface border border-line text-ink text-sm focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 outline-none transition-colors"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-ink-muted mb-1">
                    {t("profile.newPassword")}
                  </label>
                  <input
                    type="password"
                    placeholder={t("profile.passwordMinimum")}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    minLength={6}
                    className="w-full px-4 py-2.5 rounded-2xl bg-surface border border-line text-ink text-sm focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 outline-none transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-ink-muted mb-1">
                    {t("profile.confirm")}
                  </label>
                  <input
                    type="password"
                    placeholder={t("profile.passwordRepeat")}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    minLength={6}
                    className="w-full px-4 py-2.5 rounded-2xl bg-surface border border-line text-ink text-sm focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/20 outline-none transition-colors"
                  />
                </div>
              </div>

              {passwordError && (
                <div
                  role="alert"
                  className="p-3 rounded-2xl bg-danger-soft border border-danger-line text-xs text-danger-ink-on-soft font-semibold"
                >
                  {passwordError}
                </div>
              )}

              {passwordSuccess && (
                <div className="p-3 rounded-2xl bg-ok-soft border border-ok-line text-xs text-ok-ink flex items-center gap-2 font-semibold">
                  <CheckCircle2 className="w-4 h-4 text-ok shrink-0" />
                  <span>{passwordSuccess}</span>
                </div>
              )}

              <div className="flex justify-end pt-2">
                <button
                  type="submit"
                  disabled={passwordLoading}
                  className="px-5 py-2.5 text-xs font-bold rounded-2xl bg-brand hover:bg-brand-hover text-brand-ink [transition-property:color,background-color,border-color,text-decoration-color,fill,stroke,box-shadow] disabled:opacity-50 shadow-md shadow-brand/20"
                >
                  {passwordLoading ? t("profile.changing") : t("profile.changePassword")}
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* Right Column: Appearance, Workspace & JWT Inspection */}
        <div className="space-y-6">
          {/*
            Language and theme, which used to sit in the header of every screen.

            Both are set once and then never again, so they were occupying the
            most valuable row in the application — above every page, on every
            visit — to serve a decision most readers make in their first minute.
            Settings is where a once-ever choice belongs.
          */}
          <div className="glass-card space-y-4 rounded-3xl border border-line bg-surface p-6">
            <div className="flex items-center gap-2 border-b border-line pb-3">
              <Palette className="h-5 w-5 text-brand" />
              <h3 className="text-sm font-bold text-ink">{t("profile.appearance")}</h3>
            </div>
            <div className="space-y-3">
              <div className="space-y-1.5">
                <p className="text-meta font-semibold text-ink-secondary">
                  {t("profile.language")}
                </p>
                <LanguageSwitcher />
              </div>
              <div className="space-y-1.5">
                <p className="text-meta font-semibold text-ink-secondary">{t("profile.theme")}</p>
                <ThemeSwitcher />
              </div>
            </div>
          </div>

          {/* Workspace Security Info Card */}
          <div className="glass-card p-6 bg-surface border border-line rounded-3xl space-y-4">
            <div className="flex items-center gap-2 border-b border-line pb-3">
              <Building className="w-5 h-5 text-brand" />
              <h3 className="text-sm font-bold text-ink">{t("profile.workspaceDetails")}</h3>
            </div>

            <div className="space-y-3">
              <div className="p-3 rounded-2xl bg-page border border-line space-y-1.5">
                <div className="flex justify-between items-center">
                  <span className="text-meta text-ink-muted font-bold uppercase tracking-wider">
                    {t("profile.tenantId")}
                  </span>
                  <button
                    onClick={() => handleCopy(tenantId, setCopiedTenantId)}
                    className="-mx-1 flex min-h-6 items-center gap-1 rounded px-1 text-meta font-mono text-brand transition-colors hover:underline"
                  >
                    {copiedTenantId ? (
                      <Check className="w-3.5 h-3.5 text-ok" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                    <span>{copiedTenantId ? t("profile.copied") : t("profile.copy")}</span>
                  </button>
                </div>
                <p className="text-meta text-ink font-mono bg-surface p-2 rounded-xl border border-line break-all select-all">
                  {tenantId}
                </p>
              </div>

              <div className="p-3.5 rounded-2xl bg-page border border-line space-y-1">
                <div className="flex items-center gap-2 text-xs font-bold text-ink">
                  <Lock className="w-4 h-4 text-brand" />
                  <span>{t("profile.encryptedSecrets")}</span>
                </div>
                <p className="text-meta text-ink-muted leading-snug">
                  {t("profile.encryptionNote")}
                </p>
              </div>
            </div>
          </div>

          {/* Session & Logout */}
          <div className="glass-card p-6 bg-surface border border-danger-line rounded-3xl space-y-4">
            <div className="flex items-center gap-2 border-b border-line pb-3">
              <AlertCircle className="w-4 h-4 text-danger-ink-on-soft" />
              <h3 className="text-sm font-bold text-ink">{t("profile.sessionTitle")}</h3>
            </div>

            <button
              onClick={onLogout}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-danger-soft hover:bg-danger-soft/70 border border-danger-line text-danger-ink-on-soft text-xs font-bold transition-colors"
            >
              <LogOut className="w-4 h-4" />
              <span>{t("profile.signOut")}</span>
            </button>
          </div>
        </div>
      </div>

      {/* 1-Click Data Points Wipe Confirmation Modal */}
      {showWipeModal && (
        <div className="fixed inset-0 bg-scrim backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-surface border border-line rounded-3xl p-6 max-w-md w-full space-y-4 shadow-2xl">
            <div className="flex items-center gap-3 text-warn">
              <div className="p-2.5 rounded-2xl bg-warn-soft border border-warn-line">
                <AlertTriangle className="w-6 h-6" />
              </div>
              <h3 className="text-lg font-extrabold text-ink">
                {t("profile.wipeConfirmTitle")}
              </h3>
            </div>
            <p className="text-xs text-ink-muted leading-relaxed">{t("profile.wipeConfirmBody")}</p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowWipeModal(false)}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-surface-muted text-ink-secondary hover:bg-surface-muted transition-colors"
              >
                {t("common.cancel")}
              </button>
              <button
                onClick={handleWipeDataPoints}
                disabled={wipeLoading}
                className="px-4 py-2 text-xs font-bold rounded-xl bg-warn text-white hover:bg-warn/90 transition-colors disabled:opacity-50"
              >
                {wipeLoading ? t("profile.wipeRunning") : t("profile.wipeConfirmAction")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Full Account & Data Wipe Confirmation Modal */}
      {showAccountModal && (
        <div className="fixed inset-0 bg-scrim backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-surface border border-danger-line rounded-3xl p-6 max-w-md w-full space-y-4 shadow-2xl">
            <div className="flex items-center gap-3 text-danger-ink-on-soft">
              <div className="p-2.5 rounded-2xl bg-danger-soft border border-danger-line">
                <Trash2 className="w-6 h-6" />
              </div>
              <h3 className="text-lg font-extrabold text-ink">
                {t("profile.deleteAccountTitle")}
              </h3>
            </div>
            <p className="text-xs text-ink-muted leading-relaxed">
              {t("profile.deleteAccountBody")}
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowAccountModal(false)}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-surface-muted text-ink-secondary hover:bg-surface-muted transition-colors"
              >
                {t("common.cancel")}
              </button>
              <button
                onClick={handleAccountWipe}
                disabled={wipeLoading}
                className="px-4 py-2 text-xs font-bold rounded-xl bg-danger text-danger-ink hover:bg-danger/90 transition-colors disabled:opacity-50"
              >
                {wipeLoading ? t("profile.deleteAccountRunning") : t("profile.deleteAccountAction")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Owner/admin only in practice: the endpoint returns 403 for a member and
          the component renders that as an explanation rather than an error. */}
      <div className="rounded-3xl border border-line bg-surface p-5">
        <OidcProviderAdmin apiBase={apiBase} />
      </div>

      <div className="pt-2">
        <h3 className="mb-1.5 text-xs font-bold uppercase tracking-wider text-ink-muted">
          {t("profile.legalTitle")}
        </h3>
        <p className="mb-2 text-xs text-ink-muted">{t("profile.privacyLead")}</p>
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
          <a href="/legal/datenschutz" className="text-brand underline hover:text-brand-hover">
            {t("footer.privacy")}
          </a>
          <a href="/legal/impressum" className="text-brand underline hover:text-brand-hover">
            {t("footer.imprint")}
          </a>
          <a
            href="/docs/"
            target="_blank"
            rel="noreferrer"
            className="text-brand underline hover:text-brand-hover"
          >
            {t("profile.documentation")}
          </a>
        </div>
      </div>
    </div>
  );
}
