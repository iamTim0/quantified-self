"use client";

import React, { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import {
  Bot,
  Check,
  Clipboard,
  ExternalLink,
  LoaderCircle,
  MessageCirclePlus,
  Send,
  ShieldCheck,
  User,
} from "lucide-react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { apiFetch, apiJson } from "../lib/api";
import { type MessageKey, useT } from "../lib/i18n/provider";

interface ChatStatus {
  available: boolean;
  authenticated: boolean;
  plan_type: string | null;
  code: "READY" | "LOGIN_REQUIRED" | "CODEX_UNAVAILABLE" | "SUBSCRIPTION_REQUIRED";
}

interface DeviceLogin {
  login_id: string;
  user_code: string;
  verification_url: string;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

type StreamEvent =
  | { type: "thread"; thread_token: string }
  | { type: "delta"; delta: string }
  | { type: "done" }
  | { type: "error"; code: string };

const MARKDOWN_ELEMENTS = [
  "a",
  "blockquote",
  "br",
  "code",
  "del",
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "hr",
  "li",
  "ol",
  "p",
  "pre",
  "strong",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "ul",
];

const MARKDOWN_COMPONENTS: Components = {
  a: ({ children, href, title }) => (
    <a
      href={href}
      title={title}
      target="_blank"
      rel="noreferrer noopener"
      className="font-medium text-emerald-700 underline decoration-emerald-300 underline-offset-2 hover:text-emerald-900"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-4 border-emerald-200 pl-4 text-slate-600 italic">
      {children}
    </blockquote>
  ),
  code: ({ children, className }) => (
    <code
      className={`${className ?? ""} rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[0.85em] text-slate-800`}
    >
      {children}
    </code>
  ),
  h1: ({ children }) => (
    <h1 className="mb-2 mt-4 text-lg font-bold text-slate-900 first:mt-0">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2 mt-4 text-base font-bold text-slate-900 first:mt-0">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-3 font-bold text-slate-900 first:mt-0">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="mb-2 mt-3 font-semibold text-slate-900 first:mt-0">{children}</h4>
  ),
  hr: () => <hr className="my-4 border-slate-200" />,
  li: ({ children }) => <li className="my-1 pl-1">{children}</li>,
  ol: ({ children }) => <ol className="my-3 list-decimal space-y-1 pl-6">{children}</ol>,
  p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
  pre: ({ children }) => (
    <pre className="my-3 overflow-x-auto rounded-xl bg-slate-900 p-4 text-xs leading-5 text-slate-100 [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-inherit">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs">{children}</table>
    </div>
  ),
  td: ({ children }) => <td className="border border-slate-200 px-3 py-2 align-top">{children}</td>,
  th: ({ children }) => (
    <th className="border border-slate-200 bg-slate-100 px-3 py-2 font-semibold text-slate-800">
      {children}
    </th>
  ),
  ul: ({ children }) => <ul className="my-3 list-disc space-y-1 pl-6">{children}</ul>,
};

function AssistantMarkdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      allowedElements={MARKDOWN_ELEMENTS}
      components={MARKDOWN_COMPONENTS}
      remarkPlugins={[remarkGfm]}
      skipHtml
    >
      {content}
    </ReactMarkdown>
  );
}

function messageId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

export default function ChatTab({ apiBase }: { apiBase: string }) {
  const t = useT();
  const [status, setStatus] = useState<ChatStatus | null>(null);
  const [checking, setChecking] = useState(true);
  const [login, setLogin] = useState<DeviceLogin | null>(null);
  const [copied, setCopied] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [threadToken, setThreadToken] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [errorKey, setErrorKey] = useState<MessageKey | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const refreshStatus = async (): Promise<ChatStatus | null> => {
    const next = await apiJson<ChatStatus>(`${apiBase}/api/v1/chat/status`, {
      cache: "no-store",
    });
    setStatus(next);
    setChecking(false);
    if (!next) setErrorKey("chat.errorStatus");
    return next;
  };

  useEffect(() => {
    void refreshStatus();
    // apiBase is stable for the lifetime of this shell.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

  useEffect(() => {
    if (!login) return;
    const timer = window.setInterval(async () => {
      const next = await refreshStatus();
      if (next?.authenticated) {
        setLogin(null);
        setErrorKey(null);
      }
    }, 2_000);
    return () => window.clearInterval(timer);
    // refreshStatus deliberately reads no changing state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [login, apiBase]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const beginLogin = async () => {
    setErrorKey(null);
    const challenge = await apiJson<DeviceLogin>(`${apiBase}/api/v1/chat/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!challenge) {
      setErrorKey("chat.errorLogin");
      return;
    }
    setLogin(challenge);
  };

  const copyCode = async () => {
    if (!login) return;
    try {
      await navigator.clipboard.writeText(login.user_code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2_000);
    } catch {
      setErrorKey("chat.errorCopy");
    }
  };

  const newConversation = () => {
    setThreadToken(null);
    setMessages([]);
    setInput("");
    setErrorKey(null);
  };

  const sendMessage = async (event?: FormEvent) => {
    event?.preventDefault();
    const message = input.trim();
    if (!message || sending || !status?.authenticated) return;

    const userMessage: ChatMessage = { id: messageId(), role: "user", content: message };
    const assistantId = messageId();
    setMessages((current) => [
      ...current,
      userMessage,
      { id: assistantId, role: "assistant", content: "" },
    ]);
    setInput("");
    setSending(true);
    setErrorKey(null);

    try {
      const response = await apiFetch(`${apiBase}/api/v1/chat/turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
        body: JSON.stringify({ message, thread_token: threadToken }),
      });
      if (!response.ok || !response.body) {
        setErrorKey(response.status === 409 ? "chat.errorLoginRequired" : "chat.errorResponse");
        setMessages((current) => current.filter((item) => item.id !== assistantId));
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finished = false;
      let receivedDelta = false;
      while (!finished) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line) continue;
          const streamEvent = JSON.parse(line) as StreamEvent;
          if (streamEvent.type === "thread") setThreadToken(streamEvent.thread_token);
          if (streamEvent.type === "delta") {
            receivedDelta = true;
            setMessages((current) =>
              current.map((item) =>
                item.id === assistantId
                  ? { ...item, content: item.content + streamEvent.delta }
                  : item,
              ),
            );
          }
          if (streamEvent.type === "error") {
            setErrorKey("chat.errorResponse");
            if (!receivedDelta) {
              setMessages((current) => current.filter((item) => item.id !== assistantId));
            }
          }
          if (streamEvent.type === "done") {
            finished = true;
            if (!receivedDelta) {
              setErrorKey("chat.errorResponse");
              setMessages((current) => current.filter((item) => item.id !== assistantId));
            }
          }
        }
        if (done) break;
      }
    } catch {
      setErrorKey("chat.errorStream");
      setMessages((current) => current.filter((item) => item.id !== assistantId || item.content));
    } finally {
      setSending(false);
    }
  };

  const onInputKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  };

  if (checking) {
    return (
      <div className="mt-8 flex min-h-[520px] items-center justify-center rounded-3xl border border-slate-200 bg-white">
        <LoaderCircle className="h-6 w-6 animate-spin text-emerald-700" aria-hidden="true" />
        <span className="ml-3 text-sm font-medium text-slate-600">{t("chat.statusChecking")}</span>
      </div>
    );
  }

  return (
    <section className="mt-8 overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
      <header className="flex flex-col gap-4 border-b border-slate-100 px-6 py-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-emerald-700" aria-hidden="true" />
            <h1 className="text-xl font-bold text-slate-900">{t("chat.title")}</h1>
          </div>
          <p className="mt-1 text-sm text-slate-500">{t("chat.subtitle")}</p>
        </div>
        {status?.authenticated && (
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-800">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
              {t("chat.statusReady", { plan: status.plan_type ?? t("common.unknown") })}
            </span>
            <button
              type="button"
              onClick={newConversation}
              disabled={sending}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <MessageCirclePlus className="h-4 w-4" aria-hidden="true" />
              {t("chat.newConversation")}
            </button>
          </div>
        )}
      </header>

      {!status?.authenticated ? (
        <div className="mx-auto max-w-2xl px-6 py-16 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700">
            <Bot className="h-7 w-7" aria-hidden="true" />
          </div>
          <h2 className="mt-5 text-lg font-bold text-slate-900">
            {status?.code === "CODEX_UNAVAILABLE"
              ? t("chat.unavailableTitle")
              : t("chat.loginTitle")}
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            {status?.code === "CODEX_UNAVAILABLE" ? t("chat.unavailableBody") : t("chat.loginBody")}
          </p>

          {login ? (
            <div className="mt-7 rounded-2xl border border-slate-200 bg-slate-50 p-5 text-left">
              <p className="text-sm font-semibold text-slate-700">{t("chat.deviceInstruction")}</p>
              <div className="mt-4 flex items-center justify-between rounded-xl bg-white px-4 py-3 ring-1 ring-slate-200">
                <div>
                  <span className="block text-xs font-medium text-slate-400">
                    {t("chat.deviceCodeLabel")}
                  </span>
                  <code className="text-lg font-bold tracking-widest text-slate-900">
                    {login.user_code}
                  </code>
                </div>
                <button
                  type="button"
                  onClick={copyCode}
                  title={t("chat.copyCode")}
                  aria-label={t("chat.copyCode")}
                  className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"
                >
                  {copied ? <Check className="h-5 w-5" /> : <Clipboard className="h-5 w-5" />}
                </button>
              </div>
              <a
                href={login.verification_url}
                target="_blank"
                rel="noreferrer"
                className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#0d5c3a] px-4 py-3 text-sm font-semibold text-white hover:bg-[#0a4a2f]"
              >
                {t("chat.openLogin")}
                <ExternalLink className="h-4 w-4" aria-hidden="true" />
              </a>
              <p className="mt-3 text-center text-xs text-slate-400">{t("chat.waitingForLogin")}</p>
            </div>
          ) : (
            status?.available && (
              <button
                type="button"
                onClick={beginLogin}
                className="mt-7 rounded-xl bg-[#0d5c3a] px-5 py-3 text-sm font-semibold text-white hover:bg-[#0a4a2f]"
              >
                {t("chat.loginAction")}
              </button>
            )
          )}
          {errorKey && <p className="mt-4 text-sm font-medium text-rose-600">{t(errorKey)}</p>}
        </div>
      ) : (
        <>
          <div className="h-[540px] overflow-y-auto bg-slate-50/60 px-5 py-6 sm:px-8">
            {messages.length === 0 && (
              <div className="mx-auto mt-24 max-w-xl text-center">
                <h2 className="text-lg font-bold text-slate-800">{t("chat.welcomeTitle")}</h2>
                <p className="mt-2 text-sm leading-6 text-slate-500">{t("chat.welcomeBody")}</p>
              </div>
            )}
            <div className="mx-auto max-w-3xl space-y-5">
              {messages.map((message) => (
                <article
                  key={message.id}
                  className={`flex gap-3 ${message.role === "user" ? "justify-end" : "justify-start"}`}
                  aria-label={
                    message.role === "user" ? t("chat.userMessage") : t("chat.assistantMessage")
                  }
                >
                  {message.role === "assistant" && (
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-emerald-100 text-emerald-800">
                      <Bot className="h-5 w-5" aria-hidden="true" />
                    </div>
                  )}
                  <div
                    className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-6 ${
                      message.role === "user"
                        ? "whitespace-pre-wrap bg-[#0d5c3a] text-white"
                        : "border border-slate-200 bg-white text-slate-700 shadow-sm"
                    }`}
                  >
                    {!message.content ? (
                      <LoaderCircle
                        className="h-4 w-4 animate-spin text-emerald-700"
                        aria-hidden="true"
                      />
                    ) : message.role === "assistant" ? (
                      <AssistantMarkdown content={message.content} />
                    ) : (
                      message.content
                    )}
                  </div>
                  {message.role === "user" && (
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-200 text-slate-600">
                      <User className="h-5 w-5" aria-hidden="true" />
                    </div>
                  )}
                </article>
              ))}
              <div ref={bottomRef} />
            </div>
          </div>

          <form onSubmit={sendMessage} className="border-t border-slate-100 px-5 py-4 sm:px-8">
            {errorKey && <p className="mb-3 text-sm font-medium text-rose-600">{t(errorKey)}</p>}
            <div className="flex items-end gap-3">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={onInputKeyDown}
                rows={2}
                maxLength={8000}
                disabled={sending}
                placeholder={t("chat.inputPlaceholder")}
                aria-label={t("chat.inputLabel")}
                className="min-h-12 flex-1 resize-none rounded-2xl border border-slate-200 px-4 py-3 text-sm text-slate-800 outline-none transition focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100 disabled:bg-slate-50"
              />
              <button
                type="submit"
                disabled={sending || !input.trim()}
                aria-label={sending ? t("chat.sending") : t("chat.send")}
                className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#0d5c3a] text-white hover:bg-[#0a4a2f] disabled:cursor-not-allowed disabled:opacity-40"
              >
                {sending ? (
                  <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" />
                ) : (
                  <Send className="h-5 w-5" aria-hidden="true" />
                )}
              </button>
            </div>
            <p className="mt-2 text-center text-xs text-slate-400">{t("chat.disclaimer")}</p>
          </form>
        </>
      )}
    </section>
  );
}
