"use client";

import ChatTab from "../../components/ChatTab";
import { useShell } from "../shell";

export default function ChatPage() {
  const { apiBase } = useShell();
  return <ChatTab apiBase={apiBase} />;
}
