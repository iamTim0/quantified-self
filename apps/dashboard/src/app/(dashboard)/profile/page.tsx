"use client";

import ProfileTab from "../../components/ProfileTab";
import { useShell } from "../shell";

export default function ProfileRoutePage() {
  const { apiBase, tenantId, userName, userEmail, userRole, tenantName, applyProfileUpdate, logout } =
    useShell();

  return (
    <ProfileTab
      apiBase={apiBase}
      tenantId={tenantId}
      userName={userName}
      userEmail={userEmail}
      userRole={userRole}
      tenantName={tenantName}
      onUpdateProfile={applyProfileUpdate}
      onLogout={logout}
    />
  );
}
